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
# Figure 5.3 — Component ablation ladder, grouped by tier
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


def fig_5_3(rows):
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
    save(fig, "figure_5_3_ablation_ladder")


if __name__ == "__main__":
    metrics = json.loads((RESULTS / "METRICS.json").read_text())
    ablation = parse_ablation((RESULTS / "ABLATION.txt").read_text())
    assert {"P2 RAG", "P3 no-compliance", "P3 full"} <= ablation.keys(), \
        f"ablation parse incomplete: {ablation.keys()}"
    print("Generating figures ->", FIGDIR)
    fig_5_1(metrics)
    fig_5_2(metrics)
    fig_5_3(ablation)
    print("done.")
