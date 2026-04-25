"""
Crucible database visualisation.

Generates 8 publication-ready PNGs in data/plots/:
  01_coverage_heatmap.png      — property fill-rate by source
  02_kic_vs_yield.png          — fracture toughness vs yield (primary design space)
  03_property_distributions.png — violin plots by steel family
  04_composition_pca.png       — alloy space coverage (PCA of compositions)
  05_fatigue_profile.png       — fatigue limit by route and carbon content
  06_yield_vs_uts.png          — UTS/yield relationship + data quality check
  07_grade_heatmap.png         — top 50 named grades × property coverage
  08_grade_distribution.png    — records-per-grade histogram + family property rates

Usage:
    uv run python -m data.visualize
    uv run python -m data.visualize --db path/to/steels.db
"""

from __future__ import annotations

import argparse
import sqlite3
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import seaborn as sns
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

DB_PATH   = Path(__file__).parent.parent / "steels.db"
PLOT_DIR  = Path(__file__).parent / "plots"

# ── consistent family colours ────────────────────────────────────────────────
FAMILY_COLORS = {
    "carbon":    "#6b6b6b",
    "low-alloy": "#2878b5",
    "HSLA":      "#3cb371",
    "stainless": "#e07b39",
    "maraging":  "#c03060",
    "tool":      "#8b3a8b",
    "other":     "#aaaaaa",
}

SOURCE_SHORT = {
    "src_ammrc_kic_1973":     "AMMRC-1973",
    "src_asm_vol1":           "ASM Vol.1",
    "src_asm_vol4":           "ASM Vol.4",
    "src_cheng_2024":         "Cheng-2024",
    "src_figshare_steel":     "Figshare",
    "src_mondal_appendix":    "Mondal",
    "src_nims_fatigue":       "NIMS-Fat.",
    "src_steelbench_emk":     "SteelBench-EMK",
    "src_steelbench_kaggle":  "SteelBench-Kag.",
    "src_steelbench_nims":    "SteelBench-NIMS",
    "src_zenodo_steel_grades":"Zenodo-Grades",
}

plt.rcParams.update({
    "font.family":  "sans-serif",
    "font.size":    10,
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "figure.dpi":        150,
})


def _conn(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(db)


# ── 1. Coverage heatmap ───────────────────────────────────────────────────────

def plot_coverage(conn: sqlite3.Connection, out: Path) -> None:
    df = pd.read_sql("""
        SELECT
            s.source_id,
            SUM(CASE WHEN p.yield_strength_MPa            IS NOT NULL THEN 1 ELSE 0 END) AS Yield,
            SUM(CASE WHEN p.uts_MPa                       IS NOT NULL THEN 1 ELSE 0 END) AS UTS,
            SUM(CASE WHEN p.fracture_tough_KIC_MPa_sqrt_m IS NOT NULL THEN 1 ELSE 0 END) AS KIC,
            SUM(CASE WHEN p.charpy_J                      IS NOT NULL THEN 1 ELSE 0 END) AS Charpy,
            SUM(CASE WHEN p.hardness_HB IS NOT NULL
                      OR p.hardness_HRC IS NOT NULL
                      OR p.hardness_HV  IS NOT NULL  THEN 1 ELSE 0 END) AS Hardness,
            SUM(CASE WHEN p.fatigue_limit_MPa             IS NOT NULL THEN 1 ELSE 0 END) AS Fatigue,
            SUM(CASE WHEN p.elongation_pct                IS NOT NULL THEN 1 ELSE 0 END) AS Elongation,
            COUNT(p.property_id) AS Total
        FROM steels s
        LEFT JOIN properties p ON s.steel_id = p.steel_id
        GROUP BY s.source_id
    """, conn)

    df["source_id"] = df["source_id"].map(SOURCE_SHORT).fillna(df["source_id"])
    df = df.set_index("source_id")
    totals = df["Total"]
    props  = ["Yield","UTS","KIC","Charpy","Hardness","Fatigue","Elongation"]
    pct    = df[props].div(totals, axis=0) * 100

    fig, ax = plt.subplots(figsize=(9, 5.5))
    im = ax.imshow(pct.T.values, aspect="auto", cmap="YlGn", vmin=0, vmax=100)

    ax.set_xticks(range(len(pct)))
    ax.set_xticklabels(pct.index, rotation=35, ha="right", fontsize=8.5)
    ax.set_yticks(range(len(props)))
    ax.set_yticklabels(props)

    for i in range(len(pct)):
        for j, prop in enumerate(props):
            v = pct.iloc[i][prop]
            n = int(df.iloc[i][prop])
            color = "white" if v > 60 else "black"
            if n > 0:
                ax.text(i, j, f"{n}", ha="center", va="center",
                        fontsize=7.5, color=color, fontweight="bold")

    plt.colorbar(im, ax=ax, label="Fill rate (%)", fraction=0.03, pad=0.02)
    ax.set_title("Property coverage by source  (cell = row count)", fontweight="bold", pad=10)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved {out.name}")


# ── 2. KIC vs yield ──────────────────────────────────────────────────────────

def plot_kic_yield(conn: sqlite3.Connection, out: Path) -> None:
    df = pd.read_sql("""
        SELECT s.steel_family, s.source_id,
               p.yield_strength_MPa  AS yield_MPa,
               p.fracture_tough_KIC_MPa_sqrt_m AS kic,
               p.test_temp_C
        FROM properties p
        JOIN steels s ON p.steel_id = s.steel_id
        WHERE p.fracture_tough_KIC_MPa_sqrt_m IS NOT NULL
          AND p.yield_strength_MPa IS NOT NULL
    """, conn)

    fig, ax = plt.subplots(figsize=(8, 6))

    for family, grp in df.groupby("steel_family"):
        color = FAMILY_COLORS.get(family, "#aaaaaa")
        rt    = grp[grp.test_temp_C >= 0]
        cryo  = grp[grp.test_temp_C < 0]
        ax.scatter(rt["yield_MPa"],   rt["kic"],   c=color, s=28, alpha=0.75,
                   label=family, zorder=3)
        ax.scatter(cryo["yield_MPa"], cryo["kic"], c=color, s=45, alpha=0.75,
                   marker="^", zorder=3)  # triangles = cryogenic

    # KIC × σy² = const toughness lines (plane-strain validity boundary bands)
    ys_range = np.linspace(200, 2500, 300)
    for toughness, ls in [(50, ":"), (100, "--"), (150, "-.")]:
        kic_line = np.sqrt(toughness * ys_range)   # illustrative: not ASTM E399 validity
        ax.plot(ys_range, toughness * np.ones_like(ys_range),
                color="gray", lw=0.8, ls=ls, alpha=0.5)

    # Legend — families
    handles = [mpatches.Patch(color=FAMILY_COLORS.get(f, "#aaa"), label=f)
               for f in df["steel_family"].unique()]
    cryo_h  = plt.scatter([], [], marker="^", c="gray", s=40, label="cryogenic test")
    rt_h    = plt.scatter([], [], marker="o", c="gray", s=20, label="room-temp test")
    ax.legend(handles=handles + [cryo_h, rt_h], fontsize=8, loc="upper right",
              framealpha=0.9)

    ax.set_xlabel("Yield Strength (MPa)")
    ax.set_ylabel("K$_{IC}$  (MPa√m)")
    ax.set_title("Fracture Toughness vs Yield Strength  —  primary design space",
                 fontweight="bold")
    ax.set_xlim(left=0); ax.set_ylim(bottom=0)
    ax.annotate(f"n = {len(df):,}  data points", xy=(0.03, 0.96),
                xycoords="axes fraction", fontsize=8, color="gray")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved {out.name}")


# ── 3. Property distributions by family ──────────────────────────────────────

def plot_distributions(conn: sqlite3.Connection, out: Path) -> None:
    df = pd.read_sql("""
        SELECT s.steel_family,
               p.yield_strength_MPa,
               p.uts_MPa,
               p.fracture_tough_KIC_MPa_sqrt_m AS kic,
               p.hardness_HB,
               p.fatigue_limit_MPa,
               p.charpy_J
        FROM properties p
        JOIN steels s ON p.steel_id = s.steel_id
    """, conn)

    props = [
        ("yield_strength_MPa", "Yield Strength (MPa)"),
        ("uts_MPa",            "UTS (MPa)"),
        ("kic",                "K$_{IC}$ (MPa√m)"),
        ("hardness_HB",        "Hardness (HB)"),
        ("fatigue_limit_MPa",  "Fatigue Limit (MPa)"),
        ("charpy_J",           "Charpy Energy (J)"),
    ]

    fig, axes = plt.subplots(2, 3, figsize=(13, 7))
    families  = sorted(df["steel_family"].dropna().unique())
    palette   = {f: FAMILY_COLORS.get(f, "#aaa") for f in families}

    for ax, (col, label) in zip(axes.flat, props):
        sub = df[df[col].notna()][["steel_family", col]]
        if sub.empty:
            ax.set_visible(False)
            continue
        order = (sub.groupby("steel_family")[col].median()
                    .sort_values(ascending=False).index.tolist())
        sns.violinplot(data=sub, x="steel_family", y=col, order=order,
                       palette=palette, ax=ax, inner="quartile",
                       scale="width", linewidth=0.8, cut=0)
        ax.set_xlabel(""); ax.set_ylabel(label)
        ax.set_xticklabels(ax.get_xticklabels(), rotation=25, ha="right", fontsize=8)
        n_by_fam = sub.groupby("steel_family")[col].count()
        ax.set_title(f"{label.split('(')[0].strip()}  (total n={len(sub):,})",
                     fontsize=9, fontweight="bold")

    fig.suptitle("Property distributions by steel family", fontsize=12,
                 fontweight="bold", y=1.01)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved {out.name}")


# ── 4. Composition PCA ────────────────────────────────────────────────────────

def plot_pca(conn: sqlite3.Connection, out: Path) -> None:
    df = pd.read_sql("""
        SELECT s.steel_family, s.source_id,
               c.C, c.Mn, c.Si, c.Cr, c.Ni, c.Mo,
               c.V, c.Co, c.W, c.Al, c.Ti, c.Nb, c.Cu, c.N
        FROM compositions c
        JOIN steels s ON c.steel_id = s.steel_id
    """, conn)

    elements = ["C","Mn","Si","Cr","Ni","Mo","V","Co","W","Al","Ti","Nb","Cu","N"]
    X = df[elements].fillna(0).values
    # Drop rows that are all-zero (no composition info stored)
    mask = X.sum(axis=1) > 0
    X, meta = X[mask], df[mask].reset_index(drop=True)

    scaler = StandardScaler()
    pca    = PCA(n_components=2, random_state=42)
    coords = pca.fit_transform(scaler.fit_transform(X))
    ev     = pca.explained_variance_ratio_ * 100

    fig, ax = plt.subplots(figsize=(8, 6.5))
    for family, grp_idx in meta.groupby("steel_family").groups.items():
        color = FAMILY_COLORS.get(family, "#aaa")
        ax.scatter(coords[grp_idx, 0], coords[grp_idx, 1],
                   c=color, s=12, alpha=0.45, label=family, rasterized=True)

    # Loading arrows for top contributors
    loadings = pca.components_.T * np.sqrt(pca.explained_variance_)
    scale    = 0.4 * max(abs(coords).max(axis=0))
    for i, el in enumerate(elements):
        lx, ly = loadings[i, 0] * scale, loadings[i, 1] * scale
        if np.hypot(lx, ly) < 0.15 * scale:
            continue
        ax.annotate("", xy=(lx, ly), xytext=(0, 0),
                    arrowprops=dict(arrowstyle="->", color="dimgray", lw=1.2))
        ax.text(lx * 1.12, ly * 1.12, el, fontsize=8, color="dimgray",
                ha="center", va="center")

    ax.set_xlabel(f"PC1  ({ev[0]:.1f}% var.)")
    ax.set_ylabel(f"PC2  ({ev[1]:.1f}% var.)")
    ax.set_title("Composition space — PCA of 14 elements", fontweight="bold")
    ax.legend(markerscale=2.5, fontsize=8, loc="best", framealpha=0.85)
    ax.axhline(0, color="lightgray", lw=0.6, zorder=0)
    ax.axvline(0, color="lightgray", lw=0.6, zorder=0)
    ax.annotate(f"n = {len(X):,}  steels  |  elements: {', '.join(elements)}",
                xy=(0.02, 0.02), xycoords="axes fraction", fontsize=7, color="gray")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", dpi=150)
    plt.close(fig)
    print(f"  saved {out.name}")


# ── 5. Fatigue profile ────────────────────────────────────────────────────────

def plot_fatigue(conn: sqlite3.Connection, out: Path) -> None:
    df = pd.read_sql("""
        SELECT p.fatigue_limit_MPa AS fatigue,
               pr.route_type, pr.temper_temp_C,
               c.C AS carbon
        FROM properties p
        JOIN steels s   ON p.steel_id    = s.steel_id
        LEFT JOIN processing pr ON p.processing_id = pr.processing_id
        LEFT JOIN compositions c ON s.steel_id = c.steel_id
        WHERE p.fatigue_limit_MPa IS NOT NULL
    """, conn)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # Left: strip + box by route type
    route_order = (df.groupby("route_type")["fatigue"]
                     .median().sort_values(ascending=False).index.tolist())
    route_colors = {
        "QT": "#2878b5", "case_harden": "#e07b39",
        "normalize": "#6b6b6b", "anneal": "#3cb371", "other": "#aaaaaa",
    }
    palette = {r: route_colors.get(r, "#aaa") for r in route_order}
    sns.boxplot(data=df, x="route_type", y="fatigue", order=route_order,
                palette=palette, ax=ax1, width=0.5, fliersize=3, linewidth=0.9)
    sns.stripplot(data=df, x="route_type", y="fatigue", order=route_order,
                  palette=palette, ax=ax1, size=3, alpha=0.4, jitter=True)
    ax1.set_xlabel("Processing route")
    ax1.set_ylabel("Fatigue Limit (MPa)")
    ax1.set_title("Fatigue limit by processing route", fontweight="bold")
    ax1.set_xticklabels(ax1.get_xticklabels(), rotation=20, ha="right")

    # Right: fatigue vs carbon content, colored by temper temp
    sub = df[df["carbon"].notna()].copy()
    sub["temper_bin"] = pd.cut(
        sub["temper_temp_C"].fillna(0),
        bins=[0, 200, 400, 600, 900],
        labels=["none/cold", "low (≤200°C)", "mid (200–400°C)", "high (>400°C)"],
    )
    temper_palette = {
        "none/cold":      "#aaaaaa",
        "low (≤200°C)":   "#f4a261",
        "mid (200–400°C)":"#e76f51",
        "high (>400°C)":  "#264653",
    }
    for label, grp in sub.groupby("temper_bin", observed=True):
        ax2.scatter(grp["carbon"], grp["fatigue"],
                    c=temper_palette.get(str(label), "#aaa"),
                    s=22, alpha=0.7, label=str(label))
    ax2.set_xlabel("Carbon content (wt%)")
    ax2.set_ylabel("Fatigue Limit (MPa)")
    ax2.set_title("Fatigue limit vs carbon  (colored by temper temp)", fontweight="bold")
    ax2.legend(title="Temper range", fontsize=8, title_fontsize=8)
    ax2.annotate(f"n = {len(sub):,}", xy=(0.97, 0.03), xycoords="axes fraction",
                 ha="right", fontsize=8, color="gray")

    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved {out.name}")


# ── 6. Yield vs UTS ──────────────────────────────────────────────────────────

def plot_yield_uts(conn: sqlite3.Connection, out: Path) -> None:
    df = pd.read_sql("""
        SELECT s.steel_family, s.source_id,
               p.yield_strength_MPa AS yield_MPa,
               p.uts_MPa
        FROM properties p
        JOIN steels s ON p.steel_id = s.steel_id
        WHERE p.yield_strength_MPa IS NOT NULL
          AND p.uts_MPa IS NOT NULL
    """, conn)

    fig, ax = plt.subplots(figsize=(7.5, 6))

    for family, grp in df.groupby("steel_family"):
        ax.scatter(grp["yield_MPa"], grp["uts_MPa"],
                   c=FAMILY_COLORS.get(family, "#aaa"),
                   s=14, alpha=0.5, label=family, rasterized=True)

    # 1:1 line (yield = UTS — physically impossible, flags bad data)
    lim = max(df["uts_MPa"].max(), df["yield_MPa"].max()) * 1.05
    ax.plot([0, lim], [0, lim], "k--", lw=1, alpha=0.4, label="yield = UTS")
    # Typical yield ratio band (0.6–0.95 UTS)
    xs = np.linspace(0, lim, 200)
    ax.fill_between(xs, xs * 0.6, xs * 0.95, alpha=0.06, color="steelblue",
                    label="typical ratio 0.60–0.95")

    ax.set_xlim(0, lim); ax.set_ylim(0, lim)
    ax.set_xlabel("Yield Strength (MPa)")
    ax.set_ylabel("Ultimate Tensile Strength (MPa)")
    ax.set_title("UTS vs Yield Strength  —  data quality & family coverage",
                 fontweight="bold")
    handles = [mpatches.Patch(color=FAMILY_COLORS.get(f, "#aaa"), label=f)
               for f in df["steel_family"].unique()]
    ax.legend(handles=handles, fontsize=8, loc="upper left", framealpha=0.9)
    ax.annotate(f"n = {len(df):,}  data points", xy=(0.97, 0.03),
                xycoords="axes fraction", ha="right", fontsize=8, color="gray")
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved {out.name}")


# ── 7. Grade coverage heatmap ────────────────────────────────────────────────

def plot_grade_heatmap(conn: sqlite3.Connection, out: Path, top_n: int = 50) -> None:
    df = pd.read_sql("""
        SELECT s.grade, s.steel_family,
               SUM(CASE WHEN p.yield_strength_MPa            IS NOT NULL THEN 1 ELSE 0 END) AS Yield,
               SUM(CASE WHEN p.uts_MPa                       IS NOT NULL THEN 1 ELSE 0 END) AS UTS,
               SUM(CASE WHEN p.fracture_tough_KIC_MPa_sqrt_m IS NOT NULL THEN 1 ELSE 0 END) AS KIC,
               SUM(CASE WHEN p.hardness_HB IS NOT NULL
                         OR p.hardness_HRC IS NOT NULL
                         OR p.hardness_HV  IS NOT NULL  THEN 1 ELSE 0 END) AS Hardness,
               SUM(CASE WHEN p.fatigue_limit_MPa             IS NOT NULL THEN 1 ELSE 0 END) AS Fatigue,
               SUM(CASE WHEN p.elongation_pct                IS NOT NULL THEN 1 ELSE 0 END) AS Elongation,
               SUM(CASE WHEN p.charpy_J                      IS NOT NULL THEN 1 ELSE 0 END) AS Charpy,
               COUNT(p.property_id) AS Total
        FROM steels s
        LEFT JOIN properties p ON s.steel_id = p.steel_id
        WHERE s.grade IS NOT NULL
        GROUP BY s.grade, s.steel_family
        ORDER BY Total DESC
        LIMIT ?
    """, conn, params=(top_n,))

    props = ["Yield", "UTS", "KIC", "Hardness", "Fatigue", "Elongation", "Charpy"]
    matrix = df[props].values.astype(float)  # shape: (grades, props)

    # Row labels: grade name + total count + family indicator
    row_labels = [
        f"{row.grade}  [{int(row.Total)}]"
        for _, row in df.iterrows()
    ]
    # Row colours from family
    row_colors = [FAMILY_COLORS.get(f, "#aaaaaa") for f in df["steel_family"]]

    fig_h = max(10, top_n * 0.32)
    fig, ax = plt.subplots(figsize=(10, fig_h))

    # Log-scaled counts → colour; use 0 as white
    log_mat = np.where(matrix > 0, np.log1p(matrix), 0)
    im = ax.imshow(log_mat, aspect="auto", cmap="Blues", vmin=0, vmax=log_mat.max())

    ax.set_xticks(range(len(props)))
    ax.set_xticklabels(props, fontsize=9, fontweight="bold")
    ax.xaxis.set_ticks_position("top")
    ax.xaxis.set_label_position("top")

    ax.set_yticks(range(len(row_labels)))
    ax.set_yticklabels(row_labels, fontsize=7.5)

    # Colour each y-tick label by family
    for ytick, color in zip(ax.get_yticklabels(), row_colors):
        ytick.set_color(color)

    # Annotate non-zero cells with count
    for i, row_vals in enumerate(matrix):
        for j, v in enumerate(row_vals):
            if v > 0:
                text_color = "white" if log_mat[i, j] > log_mat.max() * 0.6 else "steelblue"
                ax.text(j, i, int(v), ha="center", va="center",
                        fontsize=6.5, color=text_color, fontweight="bold")

    # Family legend
    seen = {}
    for fam, col in zip(df["steel_family"], row_colors):
        seen[fam] = col
    legend_handles = [mpatches.Patch(color=c, label=f) for f, c in seen.items()]
    ax.legend(handles=legend_handles, loc="lower right",
              bbox_to_anchor=(1.0, -0.04), fontsize=7.5,
              framealpha=0.9, ncol=min(4, len(seen)))

    ax.set_title(
        f"Top {top_n} named grades — property record counts  "
        f"(label colour = family, cell = n records)",
        fontsize=10, fontweight="bold", pad=14,
    )

    plt.colorbar(im, ax=ax, label="log(1 + n records)", fraction=0.015, pad=0.01)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", dpi=150)
    plt.close(fig)
    print(f"  saved {out.name}")


# ── 8. Grade distribution ─────────────────────────────────────────────────────

def plot_grade_distribution(conn: sqlite3.Connection, out: Path) -> None:
    # Records per named grade
    rec_df = pd.read_sql("""
        SELECT s.grade, s.steel_family, COUNT(p.property_id) AS n_records
        FROM steels s
        LEFT JOIN properties p ON s.steel_id = p.steel_id
        WHERE s.grade IS NOT NULL
        GROUP BY s.grade, s.steel_family
    """, conn)

    # Property availability per family (% of grades that have ≥1 record of each type)
    fam_df = pd.read_sql("""
        SELECT s.steel_family,
               COUNT(DISTINCT s.steel_id) AS n_grades,
               SUM(CASE WHEN p.yield_strength_MPa            IS NOT NULL THEN 1 ELSE 0 END) AS Yield,
               SUM(CASE WHEN p.uts_MPa                       IS NOT NULL THEN 1 ELSE 0 END) AS UTS,
               SUM(CASE WHEN p.fracture_tough_KIC_MPa_sqrt_m IS NOT NULL THEN 1 ELSE 0 END) AS KIC,
               SUM(CASE WHEN p.hardness_HB IS NOT NULL
                         OR p.hardness_HRC IS NOT NULL
                         OR p.hardness_HV  IS NOT NULL  THEN 1 ELSE 0 END) AS Hardness,
               SUM(CASE WHEN p.fatigue_limit_MPa             IS NOT NULL THEN 1 ELSE 0 END) AS Fatigue,
               SUM(CASE WHEN p.elongation_pct                IS NOT NULL THEN 1 ELSE 0 END) AS Elongation
        FROM steels s
        LEFT JOIN properties p ON s.steel_id = p.steel_id
        WHERE s.grade IS NOT NULL
        GROUP BY s.steel_family
    """, conn)

    props = ["Yield", "UTS", "KIC", "Hardness", "Fatigue", "Elongation"]
    for prop in props:
        fam_df[prop] = fam_df[prop] / fam_df["n_grades"] * 100

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # ── Left: records-per-grade histogram (log x-axis, stacked by family) ──
    bins = np.logspace(0, np.log10(rec_df["n_records"].max() + 1), 25)
    families_ordered = (
        rec_df.groupby("steel_family")["n_records"].sum()
        .sort_values(ascending=False).index.tolist()
    )
    bottom = np.zeros(len(bins) - 1)
    for fam in families_ordered:
        sub = rec_df[rec_df["steel_family"] == fam]["n_records"]
        counts, _ = np.histogram(sub, bins=bins)
        ax1.bar(
            bins[:-1], counts, width=np.diff(bins),
            bottom=bottom, color=FAMILY_COLORS.get(fam, "#aaa"),
            label=fam, align="edge", alpha=0.85, linewidth=0.3, edgecolor="white",
        )
        bottom += counts

    ax1.set_xscale("log")
    ax1.set_xlabel("Property records per grade  (log scale)")
    ax1.set_ylabel("Number of grades")
    ax1.set_title("Records-per-grade distribution", fontweight="bold")
    ax1.legend(fontsize=8, loc="upper right", framealpha=0.9)

    n_total   = len(rec_df)
    n_single  = (rec_df["n_records"] == 1).sum()
    n_rich    = (rec_df["n_records"] >= 10).sum()
    ax1.annotate(
        f"{n_total:,} named grades\n"
        f"{n_single:,} with exactly 1 record  ({n_single/n_total*100:.0f}%)\n"
        f"{n_rich:,} with ≥10 records  ({n_rich/n_total*100:.0f}%)",
        xy=(0.03, 0.97), xycoords="axes fraction", va="top", fontsize=8, color="gray",
    )

    # ── Right: property coverage rate per family (grouped bar) ──
    fam_order = fam_df.sort_values("n_grades", ascending=False)["steel_family"].tolist()
    x         = np.arange(len(fam_order))
    width     = 0.12
    prop_colors = ["#2878b5", "#e07b39", "#c03060", "#3cb371", "#8b3a8b", "#6b6b6b"]

    for k, (prop, color) in enumerate(zip(props, prop_colors)):
        vals = [fam_df.loc[fam_df["steel_family"] == f, prop].values[0]
                for f in fam_order]
        ax2.bar(x + k * width, vals, width, label=prop, color=color, alpha=0.85)

    ax2.set_xticks(x + width * (len(props) - 1) / 2)
    ax2.set_xticklabels(fam_order, rotation=20, ha="right", fontsize=8.5)
    ax2.set_ylabel("% of grades with ≥1 record")
    ax2.set_ylim(0, 105)
    ax2.set_title("Property availability by family\n(% of grades with at least one measurement)",
                  fontweight="bold")
    ax2.legend(fontsize=8, loc="upper right", framealpha=0.9)

    # Annotate n_grades above each group
    for k, fam in enumerate(fam_order):
        n = int(fam_df.loc[fam_df["steel_family"] == fam, "n_grades"].values[0])
        ax2.text(x[k] + width * (len(props) - 1) / 2, 101, f"n={n}",
                 ha="center", fontsize=6.5, color="gray")

    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight", dpi=150)
    plt.close(fig)
    print(f"  saved {out.name}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB_PATH)
    args = parser.parse_args()

    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    conn = _conn(args.db)

    print("Generating plots → data/plots/")
    plot_coverage(     conn, PLOT_DIR / "01_coverage_heatmap.png")
    plot_kic_yield(    conn, PLOT_DIR / "02_kic_vs_yield.png")
    plot_distributions(conn, PLOT_DIR / "03_property_distributions.png")
    plot_pca(          conn, PLOT_DIR / "04_composition_pca.png")
    plot_fatigue(      conn, PLOT_DIR / "05_fatigue_profile.png")
    plot_yield_uts(        conn, PLOT_DIR / "06_yield_vs_uts.png")
    plot_grade_heatmap(    conn, PLOT_DIR / "07_grade_heatmap.png")
    plot_grade_distribution(conn, PLOT_DIR / "08_grade_distribution.png")

    conn.close()
    print(f"\nDone. Open data/plots/ to view.")


if __name__ == "__main__":
    main()
