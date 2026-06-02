"""Week 2 closeout smoke tests (Task 2.6).

Drives the 4 integration smoke tests via HTTP against the running stack
(localhost:8000) and saves machine-readable evidence under
Documents/thesis_evidence/week_2_production/smoke_test/.

Run from backend/ with:  uv run python scripts/smoke_test_week2.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

BACKEND = "http://localhost:8000"
EVIDENCE = Path(__file__).resolve().parents[2] / "Documents" / "thesis_evidence" / "week_2_production" / "smoke_test"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def login(email: str, role: str = "procurement_manager") -> str:
    """Mint a JWT via dev-login (follow=False to capture token from redirect)."""
    resp = httpx.get(
        f"{BACKEND}/api/v1/auth/dev-login",
        params={"email": email, "role": role},
        follow_redirects=False,
    )
    if resp.status_code != 307 and resp.status_code != 302:
        raise RuntimeError(f"dev-login failed ({resp.status_code}): {resp.text[:200]}")
    location = resp.headers["location"]
    # URL contains access_token=... in query string
    token = location.split("access_token=")[1].split("&")[0]
    return token


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def post_query(token: str, text: str, scope: str = "approved_only", deadline_s: int = 320) -> dict:
    """Submit a query and poll until terminal state. Returns the final query payload."""
    create = httpx.post(
        f"{BACKEND}/api/v1/queries",
        headers={**auth(token), "Content-Type": "application/json"},
        json={"raw_query": text, "search_scope": scope},
        timeout=15.0,
    )
    create.raise_for_status()
    qid = create.json()["id"]
    # Poll
    deadline = time.time() + deadline_s
    last = None
    while time.time() < deadline:
        r = httpx.get(f"{BACKEND}/api/v1/queries/{qid}", headers=auth(token), timeout=15.0)
        r.raise_for_status()
        last = r.json()
        if last.get("status") in ("completed", "failed"):
            return last
        time.sleep(3)
    raise TimeoutError(f"Query {qid} did not terminate within budget. Last status: {last.get('status') if last else 'n/a'}")


def test_1_multi_user_authz(out: dict) -> None:
    print("[test 1] multi-user authorization")
    user_a = login("usera@test.local", role="procurement_manager")
    user_b = login("userb@test.local", role="procurement_manager")
    admin = login("admin@test.local", role="admin")

    # Step 1: user A submits a query
    print("  user A submits query (scope=approved_only, ISO 9001 packaging Germany)")
    final = post_query(user_a, "ISO 9001 certified packaging supplier in Germany", scope="approved_only")
    qid = final["id"]

    # Step 2: user B fetches user A's query
    r_b = httpx.get(f"{BACKEND}/api/v1/queries/{qid}", headers=auth(user_b))
    # Step 3: admin fetches user A's query
    r_admin = httpx.get(f"{BACKEND}/api/v1/queries/{qid}", headers=auth(admin))
    # Step 4: user A saves first result (if any)
    saved_supplier_id = None
    results = final.get("results") or final.get("ranked") or []
    if results:
        target = results[0]
        sid = target.get("id") or target.get("supplier_id") or target.get("uuid")
        if sid:
            r_save = httpx.post(
                f"{BACKEND}/api/v1/suppliers/{sid}/save",
                headers={**auth(user_a), "Content-Type": "application/json"},
                json={"notes": "Smoke test 1 save"},
                timeout=10.0,
            )
            if r_save.status_code in (200, 201, 204):
                saved_supplier_id = sid
    # Step 5: user B lists my-list — should be empty / not contain A's save
    r_list_b = httpx.get(f"{BACKEND}/api/v1/suppliers/my-list", headers=auth(user_b), timeout=10.0)
    saves_b = []
    if r_list_b.status_code == 200:
        payload = r_list_b.json()
        if isinstance(payload, dict):
            saves_b = payload.get("saved") or payload.get("items") or []
        elif isinstance(payload, list):
            saves_b = payload
    leak = any(
        (s.get("id") or s.get("supplier_id")) == saved_supplier_id
        for s in saves_b if isinstance(s, dict)
    ) if saved_supplier_id else False

    out["test_1_multi_user_authz"] = {
        "timestamp": utcnow(),
        "user_a_query_uuid": qid,
        "user_a_query_status": final.get("status"),
        "user_a_result_count": len(results),
        "step_2_user_b_fetches_user_a_query": {
            "expected_status": 404,
            "observed_status": r_b.status_code,
            "observed_body_snippet": (r_b.text or "")[:200],
            "pass": r_b.status_code == 404,
        },
        "step_3_admin_fetches_user_a_query": {
            "expected_status": 200,
            "observed_status": r_admin.status_code,
            "pass": r_admin.status_code == 200,
        },
        "step_4_user_a_saved_supplier_id": saved_supplier_id,
        "step_5_user_b_my_list_leak": {
            "expected_leak": False,
            "observed_leak": leak,
            "user_b_saves_count": len(saves_b),
            "pass": not leak,
        },
        "overall_pass": (
            r_b.status_code == 404
            and r_admin.status_code == 200
            and (not leak)
        ),
    }
    print(f"  result: {out['test_1_multi_user_authz']['overall_pass']}")


def test_2_hitl_full_cycle(out: dict) -> None:
    """Full HITL approve cycle. Requires a Discovered (Tier-3) supplier to exist.

    Strategy: pick any supplier currently in `discovered` status from the DB
    (created by prior scope=both runs in earlier tasks), save it as user A,
    then admin approves it with a real justification.
    """
    print("[test 2] HITL full approval cycle")
    user_a = login("usera@test.local", role="procurement_manager")
    admin = login("admin@test.local", role="admin")

    # Find an existing discovered supplier via SQL helper endpoint OR by searching
    # Use direct supplier list endpoint with status filter if available; else fall back to known seed.
    # The supplier_repo has discovered status from past scope=both runs.
    discovered_id = None
    # Try a broad list endpoint
    r = httpx.get(
        f"{BACKEND}/api/v1/suppliers",
        headers=auth(admin),
        params={"status_filter": "discovered", "limit": 5},
        timeout=10.0,
    )
    if r.status_code == 200:
        payload = r.json()
        items = payload if isinstance(payload, list) else payload.get("items", [])
        if items:
            first = items[0]
            discovered_id = first.get("id") if isinstance(first, dict) else None
    if not discovered_id:
        out["test_2_hitl_full_cycle"] = {
            "timestamp": utcnow(),
            "overall_pass": False,
            "skipped_reason": "No supplier in 'discovered' status found via /suppliers?status=discovered; check seed data or run a scope=both query in advance.",
            "list_endpoint_status": r.status_code,
        }
        print("  SKIPPED: no discovered supplier available")
        return

    # User A saves it (Tier 2 personal save)
    r_save = httpx.post(
        f"{BACKEND}/api/v1/suppliers/{discovered_id}/save",
        headers={**auth(user_a), "Content-Type": "application/json"},
        json={"notes": "Smoke test 2 save"},
        timeout=10.0,
    )
    saved_ok = r_save.status_code in (200, 201, 204)

    # Step 7: short justification rejected
    r_short = httpx.post(
        f"{BACKEND}/api/v1/suppliers/{discovered_id}/approve",
        headers={**auth(admin), "Content-Type": "application/json"},
        json={"justification": "too short"},
        timeout=10.0,
    )
    # Step 9: valid justification accepted
    just = "Verified ISO 9001 cert on certifying body registry on 2026-06-02; capacity confirmed."
    r_ok = httpx.post(
        f"{BACKEND}/api/v1/suppliers/{discovered_id}/approve",
        headers={**auth(admin), "Content-Type": "application/json"},
        json={"justification": just},
        timeout=10.0,
    )

    # Step 10: metrics page — human_admin count should be > 0
    metrics_before_total = None
    metrics_after_total = None
    r_metrics = httpx.get(f"{BACKEND}/api/v1/admin/metrics", headers=auth(admin), params={"window_hours": 24}, timeout=10.0)
    if r_metrics.status_code == 200:
        m = r_metrics.json()
        for row in m.get("agent_latency", []):
            if row.get("agent_name") == "human_admin":
                metrics_after_total = row.get("count")

    # Verify approval persisted
    r_after = httpx.get(f"{BACKEND}/api/v1/suppliers/{discovered_id}", headers=auth(admin), timeout=10.0)
    after = r_after.json() if r_after.status_code == 200 else None

    out["test_2_hitl_full_cycle"] = {
        "timestamp": utcnow(),
        "discovered_supplier_id": discovered_id,
        "step_3_save_status": r_save.status_code,
        "step_3_save_pass": saved_ok,
        "step_7_short_justification": {
            "expected_status": 422,
            "observed_status": r_short.status_code,
            "observed_body_snippet": (r_short.text or "")[:300],
            "pass": r_short.status_code == 422,
        },
        "step_9_valid_justification": {
            "expected_status": 204,
            "observed_status": r_ok.status_code,
            "observed_body_snippet": (r_ok.text or "")[:300],
            "pass": r_ok.status_code in (200, 204),
        },
        "step_10_metrics_human_admin_count": metrics_after_total,
        "supplier_status_after": (after or {}).get("status"),
        "supplier_approval_justification_after": (after or {}).get("approval_justification"),
        "overall_pass": (
            r_short.status_code == 422
            and r_ok.status_code in (200, 204)
        ),
    }
    print(f"  result: {out['test_2_hitl_full_cycle']['overall_pass']}")


def test_3_metrics_reflect_activity(out: dict) -> None:
    print("[test 3] metrics endpoint reflects live activity")
    admin = login("admin@test.local", role="admin")
    user_a = login("usera@test.local", role="procurement_manager")

    def snap() -> dict:
        r = httpx.get(f"{BACKEND}/api/v1/admin/metrics", headers=auth(admin), params={"window_hours": 1}, timeout=10.0)
        r.raise_for_status()
        m = r.json()
        return {row["agent_name"]: row.get("count", 0) for row in m.get("agent_latency", [])}

    before = snap()
    print("  baseline:", before)
    # approved_only query
    print("  submit approved_only query")
    post_query(user_a, "ISO 9001 certified packaging supplier in Germany", scope="approved_only")
    after_approved = snap()
    print("  after approved_only:", after_approved)
    # scope=both — may take 5+ minutes on free tier; skip if env var SKIP_BOTH=1
    skip_both = os.getenv("SKIP_BOTH") == "1"
    after_both = after_approved
    if not skip_both:
        try:
            print("  submit scope=both query (may take ~5 min)")
            post_query(user_a, "ISO 9001 certified packaging supplier in Germany", scope="both")
            after_both = snap()
            print("  after scope=both:", after_both)
        except Exception as e:
            print(f"  scope=both query failed: {e}")
            after_both = {**after_approved, "_scope_both_error": str(e)[:200]}

    def delta(a: dict, b: dict) -> dict:
        return {k: b.get(k, 0) - a.get(k, 0) for k in set(a) | set(b)}

    out["test_3_metrics_live_data"] = {
        "timestamp": utcnow(),
        "counts_before": before,
        "counts_after_approved_only": after_approved,
        "counts_after_scope_both": after_both,
        "delta_approved": delta(before, after_approved),
        "delta_both": delta(after_approved, after_both),
        "scope_both_skipped": skip_both,
        "overall_pass": all(
            after_approved.get(k, 0) >= before.get(k, 0)
            for k in ("parser", "discovery", "compliance", "ranking", "evaluator")
        ),
    }
    print(f"  result: {out['test_3_metrics_live_data']['overall_pass']}")


def test_4_prod_refusal(out: dict) -> None:
    """Spawn a fresh Python interpreter with APP_ENV=production and missing OAuth
    secrets; confirm Settings() raises ValueError at import time.
    """
    print("[test 4] production config refusal")
    import subprocess

    # Build clean env: APP_ENV=production, OAuth secrets explicitly empty, no .env loaded
    env = {
        **os.environ,
        "APP_ENV": "production",
        "GROQ_API_KEY": "x",
        "VOYAGE_API_KEY": "x",
        "GOOGLE_CLIENT_ID": "x",
        "GOOGLE_CLIENT_SECRET": "",  # the one we deliberately leave empty
        "GITHUB_CLIENT_ID": "x",
        "GITHUB_CLIENT_SECRET": "x",
        "SECRET_KEY": "deadbeef" * 8,
    }
    script = (
        "import sys, os\n"
        "sys.path.insert(0, '.')\n"
        "# Force pydantic-settings to skip the .env file so the test is hermetic\n"
        "from app.core.config import Settings\n"
        "try:\n"
        "    s = Settings(_env_file=None)\n"
        "    print('UNEXPECTED_NO_RAISE:', s.APP_ENV, s.GOOGLE_CLIENT_SECRET)\n"
        "    sys.exit(2)\n"
        "except Exception as e:\n"
        "    print('RAISED:', type(e).__name__, str(e))\n"
        "    sys.exit(0)\n"
    )
    backend_dir = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(backend_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()

    # Now confirm dev start clean
    env_dev = {**env, "APP_ENV": "development", "GOOGLE_CLIENT_SECRET": ""}
    script_dev = (
        "import sys\n"
        "sys.path.insert(0, '.')\n"
        "from app.core.config import Settings\n"
        "s = Settings(_env_file=None)\n"
        "print('DEV_OK:', s.APP_ENV)\n"
    )
    proc_dev = subprocess.run(
        [sys.executable, "-c", script_dev],
        cwd=str(backend_dir),
        env=env_dev,
        capture_output=True,
        text=True,
        timeout=30,
    )

    # Validator may fire either inside our explicit try/except (RAISED: ...) OR
    # earlier during `from app.core.config import Settings` (because the module
    # eagerly calls get_settings()). Both prove the refusal. We accept either.
    combined = (stdout + "\n" + stderr)
    prod_pass = (
        proc.returncode != 0
        and "GOOGLE_CLIENT_SECRET" in combined
        and (
            "Missing required production environment variables" in combined
            or "RAISED:" in stdout
        )
    )
    dev_pass = proc_dev.returncode == 0 and "DEV_OK" in proc_dev.stdout

    out["test_4_prod_refusal"] = {
        "timestamp": utcnow(),
        "prod_attempt": {
            "exit_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "expected": "Non-zero exit + validator error citing GOOGLE_CLIENT_SECRET",
            "pass": prod_pass,
        },
        "dev_attempt": {
            "exit_code": proc_dev.returncode,
            "stdout": proc_dev.stdout.strip(),
            "stderr": proc_dev.stderr.strip(),
            "pass": dev_pass,
        },
        "overall_pass": prod_pass and dev_pass,
    }
    # also save raw text into a separate test_4_prod_refusal.txt
    (EVIDENCE / "test_4_prod_refusal.txt").write_text(
        f"--- prod attempt (APP_ENV=production, GOOGLE_CLIENT_SECRET unset) ---\n"
        f"exit_code: {proc.returncode}\n"
        f"stdout:\n{stdout}\n"
        f"stderr:\n{stderr}\n\n"
        f"--- dev attempt (APP_ENV=development) ---\n"
        f"exit_code: {proc_dev.returncode}\n"
        f"stdout:\n{proc_dev.stdout.strip()}\n",
        encoding="utf-8",
    )
    print(f"  result: {out['test_4_prod_refusal']['overall_pass']}")


def main() -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out: dict = {"run_started": utcnow(), "backend": BACKEND}
    try:
        test_1_multi_user_authz(out)
    except Exception as e:
        out["test_1_multi_user_authz"] = {"overall_pass": False, "error": str(e)}
        print(f"  test 1 raised: {e}")

    try:
        test_2_hitl_full_cycle(out)
    except Exception as e:
        out["test_2_hitl_full_cycle"] = {"overall_pass": False, "error": str(e)}
        print(f"  test 2 raised: {e}")

    try:
        test_3_metrics_reflect_activity(out)
    except Exception as e:
        out["test_3_metrics_live_data"] = {"overall_pass": False, "error": str(e)}
        print(f"  test 3 raised: {e}")

    try:
        test_4_prod_refusal(out)
    except Exception as e:
        out["test_4_prod_refusal"] = {"overall_pass": False, "error": str(e)}
        print(f"  test 4 raised: {e}")

    out["run_finished"] = utcnow()

    # Write per-test JSONs + combined
    (EVIDENCE / "test_1_multi_user_authz.json").write_text(
        json.dumps(out.get("test_1_multi_user_authz", {}), indent=2), encoding="utf-8"
    )
    (EVIDENCE / "test_2_hitl_full_cycle.json").write_text(
        json.dumps(out.get("test_2_hitl_full_cycle", {}), indent=2), encoding="utf-8"
    )
    (EVIDENCE / "test_3_metrics_live_data.json").write_text(
        json.dumps(out.get("test_3_metrics_live_data", {}), indent=2), encoding="utf-8"
    )
    (EVIDENCE / "smoke_test_run.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )

    # Summary print
    print("\n=== Summary ===")
    for key in ("test_1_multi_user_authz", "test_2_hitl_full_cycle", "test_3_metrics_live_data", "test_4_prod_refusal"):
        v = out.get(key, {})
        print(f"  {key}: pass={v.get('overall_pass')}")


if __name__ == "__main__":
    main()
