"""Render the bespoke HTML/CSS diagrams and infographics to high-resolution
white-background PNGs using headless Google Chrome, then auto-trim to content and
add a uniform white margin.

Each entry in JOBS has a matching ``thesis/figures/<name>.html`` source; the output
is ``thesis/figures/<name>.png``. Covers Figs 1.1, 2.1-2.3, 4.1 (layered
architecture) and 4.2 (workflow).

Run:  python thesis/scripts/render_infographics.py
"""
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops

FIGDIR = Path(__file__).resolve().parent.parent / "figures"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SCALE = 3          # device pixel ratio -> crisp when scaled into an A4 document
PAD = 120          # uniform white margin (device px) added after trimming

# (basename, css_width, generous_window_height) — portrait/near-square so text stays
# legible when the image is placed at A4 (portrait) column width in a Word document.
JOBS = [
    ("figure_1_1_at_a_glance", 720, 1240),
    ("figure_2_1_rag", 700, 940),
    ("figure_2_2_hybrid", 700, 1000),
    ("figure_2_3_react", 700, 640),
    ("figure_4_1_layered_architecture", 720, 1320),
    ("figure_4_2_workflow", 760, 920),
]


def render(basename, width, height):
    html = FIGDIR / f"{basename}.html"
    out = FIGDIR / f"{basename}.png"
    assert html.exists(), f"missing {html}"
    cmd = [
        CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        f"--force-device-scale-factor={SCALE}",
        f"--window-size={width},{height}",
        "--default-background-color=FFFFFFFF",
        "--virtual-time-budget=3000",
        f"--screenshot={out}",
        html.as_uri(),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    trim_pad(out)
    im = Image.open(out)
    print(f"  wrote figures/{basename}.png  ({im.width}x{im.height}px)")


def trim_pad(path):
    """Trim pure-white borders (keeping soft shadows), then re-pad uniformly."""
    im = Image.open(path).convert("RGB")
    bg = Image.new("RGB", im.size, (255, 255, 255))
    bbox = ImageChops.difference(im, bg).getbbox()
    if bbox:
        im = im.crop(bbox)
    canvas = Image.new("RGB", (im.width + 2 * PAD, im.height + 2 * PAD),
                       (255, 255, 255))
    canvas.paste(im, (PAD, PAD))
    canvas.save(path)


if __name__ == "__main__":
    if not Path(CHROME).exists():
        sys.exit(f"Google Chrome not found at {CHROME}")
    print("Rendering infographics ->", FIGDIR)
    for name, w, h in JOBS:
        render(name, w, h)
    print("done.")
