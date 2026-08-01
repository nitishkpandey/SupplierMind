#!/usr/bin/env bash
# Re-render the mermaid diagrams (Figs 2.1-2.3, 4.1-4.2) from their .mmd sources
# in thesis/figures/ to PNG (2x) + PDF. Run after editing any figures/*.mmd.
#   bash thesis/scripts/render_diagrams.sh
set -euo pipefail
cd "$(dirname "$0")/../figures"

for mmd in figure_2_1_rag figure_2_2_hybrid figure_2_3_react \
           figure_4_1_architecture figure_4_2_workflow; do
    npx -y @mermaid-js/mermaid-cli -i "$mmd.mmd" -o "$mmd.png" -b white -s 2
    npx -y @mermaid-js/mermaid-cli -i "$mmd.mmd" -o "$mmd.pdf" -b white
    echo "  rendered $mmd"
done
echo "done."
