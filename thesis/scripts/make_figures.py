"""Generate the dissertation bar charts (Figures 5.1-5.3) from the frozen results.

Reads thesis/results/10k/METRICS.json and thesis/results/10k/ABLATION.txt and
writes PNG + PDF (vector, for LaTeX) into thesis/figures/.

Run:  python thesis/scripts/make_figures.py
"""
import json
import re
from pathlib import Path

import matplotlib.pyplot as plt

THESIS = Path(__file__).resolve().parent.parent
RESULTS = THESIS / "results" / "10k"
FIGDIR = THESIS / "figures"
FIGDIR.mkdir(exist_ok=True)

# ---- palette (colour-blind friendly, print-safe) --------------------------
C_P3 = "#2A6F97"   # deep teal-blue  -> SupplierMind
C_P2 = "#E9973F"   # warm amber      -> RAG
C_P1 = "#B0B7BF"   # neutral grey    -> single-prompt
C_ABL = "#9B5DE5"  # violet          -> ablated rung
C_GOOD = "#2A9D8F"  # green           -> correct / desirable
C_BAD = "#E15554"   # coral-red       -> hallucination / undesirable
INK = "#22303C"
GRID = "#D9E0E6"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 12,
    "axes.edgecolor": INK,
    "axes.labelcolor": INK,
    "text.color": INK,
    "xtick.color": INK,
    "ytick.color": INK,
    "axes.linewidth": 0.9,
    "figure.dpi": 200,
})


def _style(ax, ymax=1.0, ylabel="Precision@5"):
    ax.set_ylim(0, ymax)
    ax.set_ylabel(ylabel, fontsize=12.5, labelpad=8)
    ax.yaxis.grid(True, color=GRID, linewidth=0.9, zorder=0)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)


def _label_bars(ax, bars, fmt="{:.3f}", dy=0.012, fs=11):
    for b in bars:
        h = b.get_height()
        ax.text(b.get_x() + b.get_width() / 2, h + dy, fmt.format(h),
                ha="center", va="bottom", fontsize=fs, fontweight="bold")


def save(fig, name):
    for ext in ("png", "pdf"):
        fig.savefig(FIGDIR / f"{name}.{ext}", bbox_inches="tight",
                    facecolor="white")
    plt.close(fig)
    print(f"  wrote figures/{name}.png  and  .pdf")


# ---------------------------------------------------------------------------
# Figure 5.1 — Precision@5 by paradigm, with 95% CI error bars
# ---------------------------------------------------------------------------
def fig_5_1(metrics):
    S = metrics["systems"]
    order = [("suppliermind", "P3\nSupplierMind", C_P3),
             ("p2_rag", "P2\nRAG", C_P2),
             ("p1_singleprompt", "P1\nsingle-prompt", C_P1)]
    means, los, his, labels, colours = [], [], [], [], []
    for key, lab, col in order:
        p5 = S[key]["p5"]
        m = p5["mean"]
        lo, hi = p5["ci95"]
        means.append(m)
        los.append(max(0.0, m - lo))
        his.append(max(0.0, hi - m))
        labels.append(lab)
        colours.append(col)

    fig, ax = plt.subplots(figsize=(7.2, 5.2))
    x = range(len(means))
    bars = ax.bar(x, means, width=0.62, color=colours, zorder=3,
                  edgecolor="white", linewidth=1.2)
    # error bars only where there is spread
    ax.errorbar(x, means, yerr=[los, his], fmt="none", ecolor=INK,
                elinewidth=1.4, capsize=6, capthick=1.4, zorder=4)
    _style(ax, ymax=1.0)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=12)
    _label_bars(ax, bars, dy=0.028)
    ax.set_title("Precision@5 by architecture",
                 fontsize=15, fontweight="bold", pad=14)
    ax.text(0.5, -0.16, "Error bars: 95% bootstrap confidence interval "
            "(mean of five runs). P1 = 0.000 — invented names absent from the corpus.",
            transform=ax.transAxes, ha="center", va="top", fontsize=9.5,
            color="#5B6770")
    save(fig, "figure_5_1_precision_by_paradigm")


# ---------------------------------------------------------------------------
# Figure 5.2 — Precision@5 by difficulty tier, grouped (P3 vs P2)
# ---------------------------------------------------------------------------
def fig_5_2(metrics):
    S = metrics["systems"]
    tiers = ["simple", "medium", "hard"]
    p3 = [S["suppliermind"]["p5_by_tier"][t] for t in tiers]
    p2 = [S["p2_rag"]["p5_by_tier"][t] for t in tiers]

    fig, ax = plt.subplots(figsize=(8.2, 5.2))
    x = range(len(tiers))
    w = 0.36
    b3 = ax.bar([i - w / 2 for i in x], p3, w, label="P3 SupplierMind",
                color=C_P3, zorder=3, edgecolor="white", linewidth=1.2)
    b2 = ax.bar([i + w / 2 for i in x], p2, w, label="P2 RAG",
                color=C_P2, zorder=3, edgecolor="white", linewidth=1.2)
    _style(ax, ymax=1.05)
    ax.set_xticks(list(x))
    ax.set_xticklabels([t.capitalize() for t in tiers], fontsize=12.5)
    ax.set_xlabel("Query difficulty tier", fontsize=12.5, labelpad=8)
    _label_bars(ax, b3, dy=0.014, fs=10.5)
    _label_bars(ax, b2, dy=0.014, fs=10.5)
    ax.legend(frameon=False, fontsize=11.5, loc="upper right",
              handlelength=1.1, handleheight=1.1)
    ax.set_title("Precision@5 widens with difficulty (H1)",
                 fontsize=15, fontweight="bold", pad=14)
    # annotate the widening gap, drawn in the gap between the two bars
    for i, (a, b) in enumerate(zip(p3, p2)):
        if a - b > 0.02:
            ax.annotate("", xy=(i, a), xytext=(i, b),
                        arrowprops=dict(arrowstyle="<->", color="#5B6770",
                                        lw=1.2))
            ax.text(i + 0.04, (a + b) / 2, f"+{a - b:.2f}", fontsize=10,
                    fontweight="bold", color="#5B6770", va="center", ha="left")
    ax.text(0.5, -0.17, "Level on simple queries; the agentic advantage grows "
            "as constraints stack. Mean of five runs.",
            transform=ax.transAxes, ha="center", va="top", fontsize=9.5,
            color="#5B6770")
    save(fig, "figure_5_2_precision_by_tier")


# ---------------------------------------------------------------------------
# Figure 5.3 — Auditability rubric (0-3) by paradigm
# ---------------------------------------------------------------------------
def fig_5_3_rubric():
    # Rubric scores from evaluation.md Table 5.3 (a curated 0-3 rubric, not a
    # computed metric): 3 = evidence-linked + queryable reasoning log; 1 =
    # grounded but no per-constraint reasoning; 0 = unstructured prose.
    order = [("P3\nSupplierMind", 3, C_P3),
             ("P2\nRAG", 1, C_P2),
             ("P1\nsingle-prompt", 0, C_P1)]
    labels = [o[0] for o in order]
    vals = [o[1] for o in order]
    cols = [o[2] for o in order]

    fig, ax = plt.subplots(figsize=(7.2, 5.0))
    x = range(len(vals))
    bars = ax.bar(x, vals, width=0.60, color=cols, zorder=3,
                  edgecolor="white", linewidth=1.2)
    ax.set_ylim(0, 3.35)
    ax.set_yticks([0, 1, 2, 3])
    ax.set_ylabel("Auditability rubric (0–3)", fontsize=12.5, labelpad=8)
    ax.yaxis.grid(True, color=GRID, linewidth=0.9, zorder=0)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=12)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.07, str(v),
                ha="center", va="bottom", fontsize=13, fontweight="bold")
    ax.set_title("Auditability by architecture (RQ2)",
                 fontsize=15, fontweight="bold", pad=14)
    ax.text(0.5, -0.15, "3 = every claim evidence-linked with a queryable reasoning "
            "log · 1 = grounded but no per-constraint trail · 0 = unstructured prose.",
            transform=ax.transAxes, ha="center", va="top", fontsize=9.3,
            color="#5B6770")
    save(fig, "figure_5_3_auditability_rubric")


# ---------------------------------------------------------------------------
# Figure 5.4 — Behaviour on impossible queries (Abstention-5)
# ---------------------------------------------------------------------------
def fig_5_4_abstention():
    # From analyze_abstention.py on the frozen results/10k_abstention run
    # (5 unsatisfiable queries, single deterministic run).
    systems = ["P2\nRAG", "P3\nSupplierMind", "P1\nsingle-prompt"]
    correct = [0.80, 0.40, 0.00]   # correctly returned nothing
    halluc = [0.20, 0.60, 1.00]    # returned a non-qualifying supplier

    fig, ax = plt.subplots(figsize=(8.4, 5.2))
    x = range(len(systems))
    w = 0.38
    bC = ax.bar([i - w / 2 for i in x], correct, w, label="Correct abstention (good)",
                color=C_GOOD, zorder=3, edgecolor="white", linewidth=1.1)
    bH = ax.bar([i + w / 2 for i in x], halluc, w,
                label="Returned a non-qualifying supplier (bad)",
                color=C_BAD, zorder=3, edgecolor="white", linewidth=1.1)
    _style(ax, ymax=1.12, ylabel="Fraction of the 5 impossible queries")
    ax.set_xticks(list(x))
    ax.set_xticklabels(systems, fontsize=12)
    _label_bars(ax, bC, fmt="{:.2f}", dy=0.015, fs=10.5)
    _label_bars(ax, bH, fmt="{:.2f}", dy=0.015, fs=10.5)
    ax.legend(frameon=False, fontsize=10.8, loc="upper center",
              ncol=2, bbox_to_anchor=(0.5, 1.02), handlelength=1.1,
              handleheight=1.1)
    ax.set_title("Behaviour on impossible queries — the honest negative result",
                 fontsize=13.8, fontweight="bold", pad=30)
    ax.text(0.5, -0.16, "RAG abstains best; the agentic system returns auditable "
            "near-misses rather than nothing. Five queries, one run — indicative.",
            transform=ax.transAxes, ha="center", va="top", fontsize=9.3,
            color="#5B6770")
    save(fig, "figure_5_4_abstention")


# ---------------------------------------------------------------------------
# Figure 5.5 — Component ablation ladder, grouped by tier
# ---------------------------------------------------------------------------
def parse_ablation(txt):
    """Pull the three rungs (overall/simple/medium/hard) out of ABLATION.txt."""
    rows = {}
    for line in txt.splitlines():
        m = re.match(r"\s*(P2 RAG|P3 no-compliance|P3 full)\b.*?"
                     r"([01]\.\d+)\s+([01]\.\d+)\s+([01]\.\d+)\s+([01]\.\d+)",
                     line)
        if m:
            rows[m.group(1)] = [float(m.group(i)) for i in range(2, 6)]
    return rows  # keys -> [overall, simple, medium, hard]


def fig_5_5_ablation(rows):
    groups = ["Overall", "Simple", "Medium", "Hard"]
    rag = rows["P2 RAG"]
    nogate = rows["P3 no-compliance"]
    full = rows["P3 full"]

    fig, ax = plt.subplots(figsize=(9.6, 5.4))
    x = range(len(groups))
    w = 0.26
    bR = ax.bar([i - w for i in x], rag, w, label="P2 RAG (semantic only)",
                color=C_P2, zorder=3, edgecolor="white", linewidth=1.1)
    bN = ax.bar(list(x), nogate, w, label="P3 without compliance gate",
                color=C_ABL, zorder=3, edgecolor="white", linewidth=1.1)
    bF = ax.bar([i + w for i in x], full, w, label="P3 full (gate restored)",
                color=C_P3, zorder=3, edgecolor="white", linewidth=1.1)
    _style(ax, ymax=1.08)
    ax.set_xticks(list(x))
    ax.set_xticklabels(groups, fontsize=12.5)
    for bars in (bR, bN, bF):
        _label_bars(ax, bars, dy=0.014, fs=9.5)
    ax.legend(frameon=False, fontsize=11, loc="upper right",
              handlelength=1.1, handleheight=1.1)
    ax.set_title("Component ablation: the compliance gate drives the advantage",
                 fontsize=14.5, fontweight="bold", pad=14)
    ax.text(0.5, -0.17, "Without the gate (violet) the agentic system falls below "
            "RAG; restoring it lifts hardest-tier precision from 0.08 to 0.58.",
            transform=ax.transAxes, ha="center", va="top", fontsize=9.5,
            color="#5B6770")
    save(fig, "figure_5_5_ablation_ladder")


# ---------------------------------------------------------------------------
# Figure 5.6 — The cost of the agentic approach (cost + compute latency)
# ---------------------------------------------------------------------------
def parse_diagnostics(txt):
    """Pull compute_ms and llm_calls per system out of DIAGNOSTICS.txt."""
    out = {}
    for line in txt.splitlines():
        m = re.match(r"\s*(suppliermind|p2_rag|p1_singleprompt)\s+([\d.]+)"
                     r"\s+\d+\s+\d+\s+\d+\s+\S+\s+(\d+)", line)
        if m:
            out[m.group(1)] = {"llm_calls": float(m.group(2)),
                               "compute_ms": int(m.group(3))}
    return out


def fig_5_6_cost_latency(metrics, diag):
    S = metrics["systems"]
    order = [("suppliermind", "P3", C_P3),
             ("p2_rag", "P2", C_P2),
             ("p1_singleprompt", "P1", C_P1)]
    labels = [o[1] for o in order]
    cols = [o[2] for o in order]
    cost = [S[k]["cost"]["mean"] * 1000 for k, _, _ in order]        # $ per 1000 q
    lat = [diag[k]["compute_ms"] / 1000 for k, _, _ in order]        # seconds

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(11.0, 5.2))
    x = range(3)

    barsL = axL.bar(x, cost, width=0.62, color=cols, zorder=3,
                    edgecolor="white", linewidth=1.2)
    _style(axL, ymax=max(cost) * 1.28, ylabel="Cost per 1,000 queries (US$)")
    axL.set_xticks(list(x)); axL.set_xticklabels(labels, fontsize=12)
    _label_bars(axL, barsL, fmt="${:.2f}", dy=max(cost) * 0.02, fs=11)
    axL.set_title("Cost per query", fontsize=13.5, fontweight="bold", pad=10)

    barsR = axR.bar(x, lat, width=0.62, color=cols, zorder=3,
                    edgecolor="white", linewidth=1.2)
    _style(axR, ymax=max(lat) * 1.28, ylabel="Compute latency (seconds)")
    axR.set_xticks(list(x)); axR.set_xticklabels(labels, fontsize=12)
    _label_bars(axR, barsR, fmt="{:.1f} s", dy=max(lat) * 0.02, fs=11)
    axR.set_title("Latency (provider pacing removed)",
                  fontsize=13.5, fontweight="bold", pad=10)

    # ×N-vs-RAG annotation on the P3 bars
    axL.text(0, cost[0] * 1.13, f"≈{cost[0]/cost[1]:.1f}× RAG", ha="center",
             fontsize=10, fontweight="bold", color=C_P3)
    axR.text(0, lat[0] * 1.13, f"≈{lat[0]/lat[1]:.1f}× RAG", ha="center",
             fontsize=10, fontweight="bold", color=C_P3)

    fig.suptitle("The cost of the agentic approach (RQ3)", fontsize=15.5,
                 fontweight="bold", y=1.0)
    fig.text(0.5, -0.02, "P3 makes ~5 sequential model calls per query versus "
             "RAG's one — the source of both the dollar and the latency cost. "
             "Mean of five runs.", ha="center", va="top", fontsize=9.3,
             color="#5B6770")
    save(fig, "figure_5_6_cost_latency")


if __name__ == "__main__":
    metrics = json.loads((RESULTS / "METRICS.json").read_text())
    ablation = parse_ablation((RESULTS / "ABLATION.txt").read_text())
    diag = parse_diagnostics((RESULTS / "DIAGNOSTICS.txt").read_text())
    assert {"P2 RAG", "P3 no-compliance", "P3 full"} <= ablation.keys(), \
        f"ablation parse incomplete: {ablation.keys()}"
    assert {"suppliermind", "p2_rag", "p1_singleprompt"} <= diag.keys(), \
        f"diagnostics parse incomplete: {diag.keys()}"
    print("Generating figures ->", FIGDIR)
    fig_5_1(metrics)
    fig_5_2(metrics)
    fig_5_3_rubric()
    fig_5_4_abstention()
    fig_5_5_ablation(ablation)
    fig_5_6_cost_latency(metrics, diag)
    print("done.")
