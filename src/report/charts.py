"""
Chart builders for the dashboard. Each returns an HTML-embeddable string:
line/bar/scatter as responsive inline SVG (crisp, print-clean, tiny), and dense
heatmaps as base64 PNG. Pure functions of arrays/DataFrames - matplotlib runs on
the headless Agg backend, so no display and full offline testability.

Every builder tolerates empty input by returning a small "no data" placeholder,
so a section never crashes on a thin warehouse.
"""
from __future__ import annotations

import base64
import io
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402
import pandas as pd               # noqa: E402

# --- palette (ledger-green family, matching the handbooks) ---
INK = "#1c2b24"
MUTED = "#6b7d73"
LEDGER = "#1b6b47"
LEDGER_SOFT = "#4a9a72"
AMBER = "#b8863b"
INFO = "#2f6f8f"
LINE = "#d8e0da"
PAPER = "#ffffff"
SERIES = [LEDGER, AMBER, INFO, "#9a4b7a", "#5a7d3a", "#b5563f", MUTED]

plt.rcParams.update({
    # Chart text uses a font that ships with matplotlib everywhere (the surrounding
    # HTML uses the IBM Plex web font); this keeps chart rendering deterministic and
    # warning-free regardless of what fonts a machine has installed.
    "font.family": ["DejaVu Sans", "sans-serif"],
    "font.size": 9,
    "axes.edgecolor": LINE, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.grid": True, "grid.color": LINE, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False,
    "figure.facecolor": PAPER, "axes.facecolor": PAPER, "savefig.facecolor": PAPER,
})


def _svg(fig) -> str:
    """matplotlib figure -> responsive inline SVG string."""
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    s = buf.getvalue()
    s = s[s.find("<svg"):]                                   # drop XML/doctype preamble
    # make it scale to its container while keeping aspect via viewBox
    s = re.sub(r'(<svg[^>]*?)\swidth="[^"]*"', r"\1", s, count=1)
    s = re.sub(r'(<svg[^>]*?)\sheight="[^"]*"', r"\1", s, count=1)
    s = s.replace("<svg", '<svg preserveAspectRatio="xMidYMid meet" '
                          'style="width:100%;height:auto;display:block"', 1)
    return f'<div class="chart">{s}</div>'


def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f'<div class="chart"><img alt="chart" style="width:100%;height:auto;display:block" ' \
           f'src="data:image/png;base64,{b64}"></div>'


def empty(msg="No data available") -> str:
    return f'<div class="chart chart-empty">{msg}</div>'


# ------------------------------------------------------------------ line chart
def line(df, x, ys, labels=None, height=2.4, rebase=False,
         shade_negative=None, band=None, ylabel=None):
    """Multi-line time series. `ys` a list of columns; `rebase` indexes each to 100
    at its first valid point; `shade_negative` shades where that column < 0;
    `band` = (lo, hi) draws a neutral band."""
    if df is None or len(df) == 0 or x not in df.columns:
        return empty()
    d = df.copy()
    d[x] = pd.to_datetime(d[x], errors="coerce")
    d = d.dropna(subset=[x]).sort_values(x)
    ys = [c for c in ys if c in d.columns and d[c].notna().any()]
    if not ys:
        return empty()
    labels = labels or ys
    fig, ax = plt.subplots(figsize=(6.2, height))
    if band is not None:
        ax.axhspan(band[0], band[1], color=LEDGER, alpha=0.06, lw=0)
        ax.axhline(0, color=LINE, lw=0.8)
    for i, c in enumerate(ys):
        series = d[c]
        if rebase:
            first = series.dropna()
            series = series / first.iloc[0] * 100 if len(first) else series
        ax.plot(d[x], series, color=SERIES[i % len(SERIES)], lw=1.4,
                label=labels[i] if i < len(labels) else c)
    if shade_negative and shade_negative in d.columns:
        ax.fill_between(d[x], 0, 1, where=(d[shade_negative] < 0),
                        transform=ax.get_xaxis_transform(),
                        color=AMBER, alpha=0.10, lw=0)
    if len(ys) > 1:
        ax.legend(loc="best", frameon=False, fontsize=8)
    if ylabel:
        ax.set_ylabel(ylabel)
    ax.margins(x=0.01)
    fig.autofmt_xdate(rotation=0, ha="center")
    return _svg(fig)


# --------------------------------------------------------------- diverging bar
def diverging_bar(labels, values, height=None, pos_color=LEDGER, neg_color=AMBER,
                  xlabel=None):
    """Horizontal bars centred at zero, sorted by value - for z-scores / excess."""
    pairs = [(l, v) for l, v in zip(labels, values) if v is not None and pd.notna(v)]
    if not pairs:
        return empty()
    pairs.sort(key=lambda t: t[1])
    labs = [p[0] for p in pairs]
    vals = [p[1] for p in pairs]
    h = height or max(1.6, 0.32 * len(pairs) + 0.6)
    fig, ax = plt.subplots(figsize=(6.2, h))
    colors = [pos_color if v >= 0 else neg_color for v in vals]
    ax.barh(range(len(vals)), vals, color=colors, height=0.68)
    ax.set_yticks(range(len(labs)))
    ax.set_yticklabels(labs, fontsize=8)
    ax.axvline(0, color=MUTED, lw=0.8)
    ax.grid(axis="y", visible=False)
    if xlabel:
        ax.set_xlabel(xlabel)
    return _svg(fig)


# ------------------------------------------------------------------- h-bar
def hbar(labels, values, height=None, color=LEDGER, xlabel=None):
    pairs = [(l, v) for l, v in zip(labels, values) if v is not None and pd.notna(v)]
    if not pairs:
        return empty()
    pairs.sort(key=lambda t: t[1])
    labs = [p[0] for p in pairs]
    vals = [p[1] for p in pairs]
    h = height or max(1.6, 0.32 * len(pairs) + 0.6)
    fig, ax = plt.subplots(figsize=(6.2, h))
    ax.barh(range(len(vals)), vals, color=color, height=0.68)
    ax.set_yticks(range(len(labs)))
    ax.set_yticklabels(labs, fontsize=8)
    ax.grid(axis="y", visible=False)
    if xlabel:
        ax.set_xlabel(xlabel)
    return _svg(fig)


# ------------------------------------------------------------------ scatter
def scatter(xs, ys, labels=None, xlabel=None, ylabel=None, quadrants=False, height=3.2):
    pts = [(x, y, (labels[i] if labels else None))
           for i, (x, y) in enumerate(zip(xs, ys))
           if x is not None and y is not None and pd.notna(x) and pd.notna(y)]
    if not pts:
        return empty()
    fig, ax = plt.subplots(figsize=(6.2, height))
    ax.scatter([p[0] for p in pts], [p[1] for p in pts], s=42,
               color=LEDGER, alpha=0.8, edgecolor="white", linewidth=0.6, zorder=3)
    if labels:
        for x, y, lab in pts:
            ax.annotate(lab, (x, y), fontsize=7, color=INK,
                        xytext=(4, 3), textcoords="offset points")
    if quadrants:
        ax.axvline(0, color=LINE, lw=0.8)
        ax.axhline(0, color=LINE, lw=0.8)
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)
    return _svg(fig)


# ------------------------------------------------------------------- heatmap
def heatmap(matrix_df, height=None, cmap="RdYlGn", vmin=-2, vmax=2):
    """Dense grid (names x factors) -> PNG. Values expected as z-scores."""
    if matrix_df is None or matrix_df.empty:
        return empty()
    m = matrix_df.apply(pd.to_numeric, errors="coerce")
    h = height or max(1.8, 0.34 * len(m) + 1.0)
    fig, ax = plt.subplots(figsize=(6.2, h))
    im = ax.imshow(m.values, cmap=cmap, vmin=vmin, vmax=vmax, aspect="auto")
    ax.set_xticks(range(len(m.columns)))
    ax.set_xticklabels(m.columns, rotation=30, ha="right", fontsize=8)
    ax.set_yticks(range(len(m.index)))
    ax.set_yticklabels(m.index, fontsize=8)
    ax.grid(False)
    for i in range(len(m.index)):
        for j in range(len(m.columns)):
            v = m.values[i, j]
            if pd.notna(v):
                ax.text(j, i, f"{v:.1f}", ha="center", va="center", fontsize=6.5, color=INK)
    fig.colorbar(im, ax=ax, fraction=0.025, pad=0.02)
    return _png(fig)


# ------------------------------------------------------------------ sparkline
def sparkline(values, up=LEDGER, down=AMBER):
    v = [x for x in (values or []) if x is not None and pd.notna(x)]
    if len(v) < 2:
        return ""
    color = up if v[-1] >= v[0] else down
    fig, ax = plt.subplots(figsize=(1.4, 0.36))
    ax.plot(range(len(v)), v, color=color, lw=1.1)
    ax.fill_between(range(len(v)), v, min(v), color=color, alpha=0.10, lw=0)
    ax.axis("off")
    ax.margins(0)
    return _svg(fig).replace('class="chart"', 'class="spark"')
