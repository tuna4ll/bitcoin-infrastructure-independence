"""Common matplotlib settings for all figures (light background, fixed colour order)."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]  # first three slots validate all-pairs
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e4e3df", "#ffffff"

plt.rcParams.update({
    "figure.dpi": 150, "savefig.dpi": 300, "savefig.bbox": "tight",
    "font.family": "DejaVu Sans", "font.size": 9,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK2, "axes.titlecolor": INK,
    "axes.titlesize": 10, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "xtick.color": INK2, "ytick.color": INK2, "legend.frameon": False,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "lines.linewidth": 2,
})


def source_note(fig, text: str) -> None:
    """Puts the small data-source line under the figure, below everything else."""
    fig.canvas.draw()
    bb = fig.get_tightbbox(fig.canvas.get_renderer())
    y = bb.y0 / fig.get_figheight() - 0.02
    x = bb.x0 / fig.get_figwidth()
    fig.text(x, y, text, ha="left", va="top", fontsize=6.5, color=MUTED, wrap=True)
