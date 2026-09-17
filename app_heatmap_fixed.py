"""
Curve Correlation Explorer
---------------------------
Interactive Streamlit app for exploring trailing correlation across the
columns of a curve/spread dataset (Timestamp | col1 | col2 | ... | colN).

Run:
    pip install -r requirements.txt
    streamlit run app.py
"""

import io

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Curve Correlation Explorer", layout="wide")

PLOTLY_CONFIG = {"displaylogo": False, "toImageButtonOptions": {"format": "png", "scale": 2}}

MONTH_TICKVALS = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
MONTH_TICKTEXT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

DARK_CSS = """
<style>
.stApp { background-color: #0e1117; color: #e6e6e6; }
section[data-testid="stSidebar"] { background-color: #161a23; }
div[data-baseweb="select"] > div, .stTextInput input, .stNumberInput input {
    background-color: #1c2029; color: #e6e6e6;
}
.stDownloadButton button, .stButton button { background-color: #1c2029; color: #e6e6e6; }
[data-testid="stMetricValue"] { color: #e6e6e6; }
</style>
"""


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def load_workbook(file_bytes: bytes):
    xl = pd.ExcelFile(io.BytesIO(file_bytes))
    sheets = {}
    for name in xl.sheet_names:
        df = xl.parse(name)
        if "Timestamp" not in df.columns:
            continue
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], utc=True, errors="coerce")
        df["Timestamp"] = df["Timestamp"].dt.tz_localize(None)
        df = df.dropna(subset=["Timestamp"]).sort_values("Timestamp").reset_index(drop=True)
        sheets[name] = df
    return sheets


def get_basis_df(df: pd.DataFrame, value_cols: list, basis: str,
                  ffill_limit: int) -> pd.DataFrame:
    """Build the series used for correlation. Short gaps (<= ffill_limit rows)
    in the raw price levels are forward-filled BEFORE differencing, so a brief
    missing print doesn't fabricate a large fake move — it's treated as
    "no trade, no change" for that day. Longer gaps are left as NaN."""
    levels = df[value_cols].copy()
    if ffill_limit > 0:
        levels = levels.ffill(limit=int(ffill_limit))
    if basis == "Daily changes":
        out = levels.diff()
    else:
        out = levels
    out.index = df["Timestamp"]
    return out


def rolling_corr(basis_df, a, b, window, min_pct):
    min_periods = max(2, int(np.ceil(window * min_pct / 100)))
    return basis_df[a].rolling(int(window), min_periods=min_periods).corr(basis_df[b])


def valid_pairs(value_cols: list):
    pairs = {}
    for i, base in enumerate(value_cols[:-1]):
        pairs[base] = value_cols[i + 1:]
    return pairs


def parse_window_list(text: str, defaults):
    windows = set(defaults)
    if text.strip():
        for tok in text.replace(",", " ").split():
            try:
                w = int(tok)
                if w > 1:
                    windows.add(w)
            except ValueError:
                pass
    return sorted(windows)


def clip_to_range(s: pd.Series, start, end) -> pd.Series:
    return s[(s.index.date >= start) & (s.index.date <= end)]


def apply_template(fig, dark: bool):
    fig.update_layout(template="plotly_dark" if dark else "plotly_white")
    return fig


# ---------------------------------------------------------------------------
# Sidebar — data + global settings
# ---------------------------------------------------------------------------

st.sidebar.title("Curve Correlation Explorer")

dark_mode = st.sidebar.toggle("Dark mode", value=False, key="dark_mode")
if dark_mode:
    st.markdown(DARK_CSS, unsafe_allow_html=True)

uploaded = st.sidebar.file_uploader(
    "Upload data file(s) (.xlsx)", type=["xlsx"], accept_multiple_files=True
)

if not uploaded:
    st.title("Curve Correlation Explorer")
    st.info(
        "Upload one or more Excel files in the sidebar to get started. "
        "Each sheet should have a `Timestamp` column followed by your curve/spread columns "
        "(e.g. CO1, CO1-2, CO2-3, ...)."
    )
    st.stop()

file_names = [f.name for f in uploaded]
active_file_name = st.sidebar.selectbox("File", file_names)
active_file = next(f for f in uploaded if f.name == active_file_name)

sheets = load_workbook(active_file.getvalue())
if not sheets:
    st.sidebar.error("No sheet with a 'Timestamp' column was found in this file.")
    st.stop()

sheet_name = st.sidebar.selectbox("Sheet", list(sheets.keys()))
df = sheets[sheet_name]
value_cols = [c for c in df.columns if c != "Timestamp"]

if len(value_cols) < 2:
    st.sidebar.error("Need at least two data columns besides Timestamp.")
    st.stop()

basis = st.sidebar.radio("Correlation basis", ["Daily changes", "Price levels"], index=0)
st.sidebar.caption(
    "Daily changes avoids spurious correlation from shared trend in price/curve level. "
    "Price levels shows raw co-movement including trend."
)

with st.sidebar.expander("Missing data handling", expanded=False):
    ffill_limit = st.number_input(
        "Forward-fill gaps up to N days (0 = off)", min_value=0, max_value=30, value=3,
        help="Treats a brief missing print as 'no move' rather than fabricating a jump. "
             "Longer gaps are left as real gaps.",
    )
    min_pct = st.slider(
        "Minimum window completeness required (%)", min_value=50, max_value=100, value=80,
        help="A rolling window doesn't need every single day present to compute a "
             "correlation — this sets how much of the window can be missing before "
             "that point is left blank instead of fabricated.",
    )

min_ts, max_ts = df["Timestamp"].min().date(), df["Timestamp"].max().date()
date_range = st.sidebar.date_input(
    "Display date range", value=(min_ts, max_ts), min_value=min_ts, max_value=max_ts,
    help="Correlation is always computed on the full history (so windows near the start "
         "of your range still have proper lookback) — this only limits what's plotted.",
)
if isinstance(date_range, tuple) and len(date_range) == 2:
    range_start, range_end = date_range
else:
    range_start, range_end = min_ts, max_ts

basis_df = get_basis_df(df, value_cols, basis, ffill_limit)
pairs = valid_pairs(value_cols)
n_rows = len(df)
years_available = sorted(df["Timestamp"].dt.year.unique().tolist())

st.sidebar.markdown(f"**Rows:** {n_rows:,}  \n**Years:** {years_available[0]}–{years_available[-1]}")

# ---------------------------------------------------------------------------
# Base / Target selection (shared across Time Series & Year Overlay tabs)
# ---------------------------------------------------------------------------

st.title("Curve Correlation Explorer")
c1, c2 = st.columns(2)
with c1:
    base_col = st.selectbox("Base column", list(pairs.keys()), key="base_col")
with c2:
    target_col = st.selectbox("Target column", pairs[base_col], key="target_col")

tab_heat, tab_ts, tab_year, tab_summary, tab_about = st.tabs(
    ["Heatmap", "Time Series", "Year Overlay", "Summary Table", "About"]
)

# ---------------------------------------------------------------------------
# Heatmap tab
# ---------------------------------------------------------------------------

with tab_heat:
    # Select exactly which contracts should appear on each heatmap axis.
    # st.multiselect provides a searchable tick-box selector, which is much
    # easier to use when the Excel file contains many contracts.
    hc1, hc2 = st.columns([1, 3])

    with hc1:
        heat_window = st.number_input(
            "Trailing window (periods)", min_value=2, max_value=max(3, n_rows - 1),
            value=min(60, max(2, n_rows - 1)), step=1, key="heat_window",
        )

        asof_idx = st.slider(
            "As-of date", min_value=0, max_value=n_rows - 1, value=n_rows - 1,
            format="", key="asof_idx",
            help="Move to see the correlation matrix as it stood on an earlier date.",
        )

        asof_date = df["Timestamp"].iloc[asof_idx]
        st.caption(
            f"As of: **{asof_date.date()}**  |  window: last {heat_window} periods"
        )

        st.markdown("**Contracts to display**")

        selected_heat_base = st.multiselect(
            "Base columns",
            options=value_cols,
            default=value_cols,
            key="heatmap_base_cols",
            help="Tick the contracts you want on the Base (Y) axis. "
                 "Use the search box when there are many contracts.",
        )

        selected_heat_target = st.multiselect(
            "Target columns",
            options=value_cols,
            default=value_cols,
            key="heatmap_target_cols",
            help="Tick the contracts you want on the Target (X) axis. "
                 "Use the search box when there are many contracts.",
        )

        if not selected_heat_base or not selected_heat_target:
            st.info("Select at least one Base and one Target contract.")

    start = max(0, asof_idx - heat_window + 1)
    window_slice = basis_df.iloc[start: asof_idx + 1]
    min_periods_needed = max(2, int(np.ceil(heat_window * min_pct / 100)))

    if window_slice.notna().sum().min() < min_periods_needed or len(window_slice) < 3:
        with hc2:
            st.warning("Not enough data in this window to compute correlation.")

    elif selected_heat_base and selected_heat_target:
        corr_full = window_slice.corr(min_periods=min_periods_needed)

        # IMPORTANT:
        # Reindex the full correlation matrix using only the contracts selected
        # above. This prevents Plotly from trying to display every Excel column.
        mat = corr_full.reindex(
            index=selected_heat_base,
            columns=selected_heat_target,
        ).copy()

        # A contract correlated with itself is not useful in the heatmap.
        for col in mat.columns:
            if col in mat.index:
                mat.loc[col, col] = np.nan

        # Increase chart size according to the number of selected contracts.
        # This keeps labels/cells readable while avoiding an enormous chart.
        n_heat_rows = max(1, len(selected_heat_base))
        n_heat_cols = max(1, len(selected_heat_target))
        fig_height = max(500, min(1000, 250 + n_heat_rows * 32))
        fig_width = max(700, min(1800, 450 + n_heat_cols * 55))

        fig = go.Figure(
            data=go.Heatmap(
                z=mat.values,
                x=selected_heat_target,
                y=selected_heat_base,
                colorscale="RdYlGn",
                zmin=-1,
                zmax=1,
                colorbar=dict(title="corr"),
                hovertemplate=(
                    "Base: %{y}<br>"
                    "Target: %{x}<br>"
                    "Corr: %{z:.2f}<extra></extra>"
                ),
            )
        )

        fig.update_layout(
            height=fig_height,
            width=fig_width,
            xaxis_title="Target",
            yaxis_title="Base",
            yaxis_autorange="reversed",
            margin=dict(l=120, r=40, t=50, b=130),
        )

        fig.update_xaxes(
            tickangle=-45,
            automargin=True,
            type="category",
        )
        fig.update_yaxes(
            automargin=True,
            type="category",
        )

        apply_template(fig, dark_mode)

        with hc2:
            st.plotly_chart(
                fig,
                use_container_width=True,
                config=PLOTLY_CONFIG,
            )

            st.caption(
                f"Showing {len(selected_heat_base)} Base contract(s) × "
                f"{len(selected_heat_target)} Target contract(s). "
                "Only the ticked contracts are plotted."
            )

    else:
        with hc2:
            st.info(
                "Select at least one Base and one Target contract to display the heatmap."
            )


# ---------------------------------------------------------------------------
# Time Series tab
# ---------------------------------------------------------------------------

with tab_ts:
    tc1, tc2 = st.columns([1, 3])
    with tc1:
        preset_defaults = [20, 60, 120]
        chosen_presets = st.multiselect(
            "Windows to overlay", preset_defaults, default=preset_defaults, key="ts_presets"
        )
        custom_windows_text = st.text_input(
            "Add custom window(s) (comma/space separated)", "", key="ts_custom"
        )
        windows = parse_window_list(custom_windows_text, chosen_presets)
        if not windows:
            windows = [60]
        highlight_flips = st.checkbox("Highlight sign-change points", value=True, key="ts_flip")
        show_avg = st.checkbox("Show average across selected windows", value=False, key="ts_show_avg")
        only_avg = False
        if show_avg:
            only_avg = st.checkbox("Show only average (hide individual lines)", value=False, key="ts_only_avg")

    series_by_window = {}
    for w in windows:
        s = rolling_corr(basis_df, base_col, target_col, w, min_pct)
        series_by_window[w] = clip_to_range(s, range_start, range_end)

    fig = go.Figure()
    if not only_avg:
        for w, s in series_by_window.items():
            fig.add_trace(go.Scatter(x=s.index, y=s.values, mode="lines", name=f"{w}d",
                                      connectgaps=False))
            if highlight_flips:
                valid = s.dropna()
                if len(valid) > 1:
                    sign = np.sign(valid.values)
                    flips = valid.index[1:][sign[1:] != sign[:-1]]
                    if len(flips):
                        fig.add_trace(go.Scatter(
                            x=flips, y=valid.loc[flips].values, mode="markers",
                            marker=dict(color="black", size=6, symbol="x"),
                            name=f"{w}d sign flip", showlegend=(w == windows[0]),
                        ))
    if show_avg and len(series_by_window) > 1:
        avg_series = pd.concat(series_by_window.values(), axis=1).mean(axis=1, skipna=True)
        fig.add_trace(go.Scatter(
            x=avg_series.index, y=avg_series.values, mode="lines", name="Average",
            line=dict(color="black", width=3, dash="dash"), connectgaps=False,
        ))
    fig.update_layout(
        height=550, yaxis_range=[-1, 1], yaxis_title="Trailing correlation",
        xaxis_title="Date", title=f"{base_col} vs {target_col} — trailing correlation ({basis.lower()})",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.add_hline(y=0, line_dash="dot", line_color="grey")
    apply_template(fig, dark_mode)
    with tc2:
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)

    out_df = pd.DataFrame({f"{w}d": s for w, s in series_by_window.items()})
    out_df.index.name = "Timestamp"
    st.download_button(
        "Download this series as CSV", out_df.to_csv().encode(),
        file_name=f"{sheet_name}_{base_col}_vs_{target_col}_timeseries.csv",
        mime="text/csv",
    )

# ---------------------------------------------------------------------------
# Year Overlay tab
# ---------------------------------------------------------------------------

with tab_year:
    yc1, yc2 = st.columns([1, 3])
    with yc1:
        overlay_window = st.number_input(
            "Window for overlay", min_value=2, max_value=max(3, n_rows - 1),
            value=60, step=1, key="year_window",
        )
        chosen_years = st.multiselect(
            "Years to compare", years_available, default=years_available, key="year_pick"
        )
        show_avg_yr = st.checkbox("Show average across selected years", value=False, key="yr_show_avg")
        only_avg_yr = False
        if show_avg_yr:
            only_avg_yr = st.checkbox("Show only average (hide individual years)", value=False, key="yr_only_avg")

    s_full = rolling_corr(basis_df, base_col, target_col, overlay_window, min_pct)
    s = clip_to_range(s_full, range_start, range_end)
    tmp = pd.DataFrame({"ts": s.index, "val": s.values}).dropna()
    tmp["doy"] = tmp["ts"].dt.dayofyear
    tmp["year"] = tmp["ts"].dt.year
    tmp = tmp[tmp["year"].isin(chosen_years)]

    fig = go.Figure()
    if not only_avg_yr:
        for yr, grp in tmp.groupby("year"):
            grp = grp.sort_values("doy")
            fig.add_trace(go.Scatter(x=grp["doy"], y=grp["val"], mode="lines", name=str(yr),
                                      connectgaps=False))
    if show_avg_yr and tmp["year"].nunique() > 1:
        avg_by_doy = tmp.groupby("doy")["val"].mean().sort_index()
        fig.add_trace(go.Scatter(
            x=avg_by_doy.index, y=avg_by_doy.values, mode="lines", name="Average",
            line=dict(color="black", width=3, dash="dash"),
        ))
    fig.update_layout(
        height=550, yaxis_range=[-1, 1], yaxis_title="Trailing correlation",
        xaxis_title="Month",
        title=f"{base_col} vs {target_col} — year-over-year overlay ({overlay_window}d, {basis.lower()})",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_xaxes(tickmode="array", tickvals=MONTH_TICKVALS, ticktext=MONTH_TICKTEXT,
                      range=[1, 366])
    fig.add_hline(y=0, line_dash="dot", line_color="grey")
    apply_template(fig, dark_mode)
    with yc2:
        st.plotly_chart(fig, use_container_width=True, config=PLOTLY_CONFIG)

    pivot = tmp.pivot_table(index="doy", columns="year", values="val")
    st.download_button(
        "Download this overlay as CSV", pivot.to_csv().encode(),
        file_name=f"{sheet_name}_{base_col}_vs_{target_col}_year_overlay.csv",
        mime="text/csv",
    )

# ---------------------------------------------------------------------------
# Summary Table tab
# ---------------------------------------------------------------------------

with tab_summary:
    sc1, sc2 = st.columns([1, 3])
    with sc1:
        summary_window = st.number_input(
            "Window for summary stats", min_value=2, max_value=max(3, n_rows - 1),
            value=60, step=1, key="summary_window",
        )
    rows = []
    for base, targets in pairs.items():
        for target in targets:
            s = rolling_corr(basis_df, base, target, summary_window, min_pct)
            s = clip_to_range(s, range_start, range_end).dropna()
            if len(s):
                rows.append({
                    "Base": base, "Target": target, "Mean": s.mean(), "Std": s.std(),
                    "Min": s.min(), "Max": s.max(), "Last": s.iloc[-1], "N obs": len(s),
                })
    summary_df = pd.DataFrame(rows).round(3)
    st.dataframe(summary_df, use_container_width=True, height=500)
    st.download_button(
        "Download summary as CSV", summary_df.to_csv(index=False).encode(),
        file_name=f"{sheet_name}_correlation_summary_{summary_window}d.csv",
        mime="text/csv",
    )

# ---------------------------------------------------------------------------
# About tab
# ---------------------------------------------------------------------------

with tab_about:
    st.markdown(f"""
### Methodology
- **Pairing**: every column is a "base" correlated against every column to its right
  (e.g. CO1 vs. all spreads; CO1-2 vs. the remaining spreads; etc.).
- **Basis**: toggle in the sidebar between correlation of **daily changes** (recommended)
  and **price levels**.
- **Missing data**: short gaps (configurable, default ≤3 days) in the raw price levels are
  forward-filled before differencing — treating a brief missing print as "no move" rather
  than fabricating a jump. Separately, a rolling window only needs a configurable %% of its
  days present (default 80%%) to compute a correlation, rather than requiring every single
  day — so isolated gaps no longer blank out a whole window's worth of points. Longer gaps
  are still left as real, visible gaps rather than filled.
- **Display date range**: correlation is always computed on the full history first (so early
  points in your chosen range still have proper lookback), then trimmed only for display.
- **Trailing window**: any integer number of periods, set per-chart.
- Currently loaded: **{sheet_name}** from **{active_file_name}**, {n_rows:,} rows,
  {years_available[0]}–{years_available[-1]}.

### Ideas not yet built — say the word if you want any of these added
- **Cross-sheet / cross-file comparison** — overlay the same pair's correlation across two
  different products or datasets.
- **Correlation vs. volatility overlay** — show whether correlation breakdowns coincide with
  vol regime shifts.
- **Persist uploaded data** so you don't need to re-upload each session.
- **Multi-pair small-multiples view** — grid of mini time-series charts for a base column
  against all its near tenors at once, instead of one pair at a time.
""")
