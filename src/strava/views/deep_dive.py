# pylint: disable=too-many-lines
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import folium
from streamlit_folium import folium_static
from strava.data import get_activity_stream, get_activity_laps, get_activities_with_streams
from strava.utils.activity_processing import (
    _calculate_metrics,
    _calculate_splits,
    fmt_pace,
    fmt_duration,
)
from strava.constants import ZONE_COLORS_LIST


def _render_hr_analysis(track_df, zones):
    z1, z2, z3, z4 = zones
    st.markdown("### Heart Rate Analysis")

    labels = ["Recovery", "Endurance", "Tempo", "Threshold", "Anaerobic"]
    # Non-overlapping ranges: Z4 ends at z4-1, Z5 starts at z4
    ranges = [f"< {z1}", f"{z1} - {z2-1}", f"{z2} - {z3-1}", f"{z3} - {z4-1}", f"{z4}+"]

    def get_zone_idx(h):
        if pd.isna(h):
            return None
        if h < z1:
            return 0
        if h < z2:
            return 1
        if h < z3:
            return 2
        if h < z4:
            return 3
        return 4

    track_df["Zone_Idx"] = track_df["HR"].apply(get_zone_idx)
    total_time = track_df["Time_Diff"].sum()

    zone_data = []
    for i in range(5):
        z_time = track_df[track_df["Zone_Idx"] == i]["Time_Diff"].sum()
        pct = (z_time / total_time * 100) if total_time > 0 else 0
        zone_data.append(
            {
                "Zone": f"Z{i+1}",
                "Description": labels[i],
                "Range": ranges[i],
                "Time": z_time,
                "Percentage": pct,
            }
        )

    # Display as table with bars
    cols = st.columns([1, 2, 2, 1, 1, 3])
    headers = ["Zone", "Description", "Range", "Time", "%", ""]
    for col, head in zip(cols, headers):
        col.markdown(f"**{head}**")

    for i, row in enumerate(zone_data):
        c = st.columns([1, 2, 2, 1, 1, 3])
        c[0].write(row["Zone"])
        c[1].write(row["Description"])
        c[2].text(row["Range"])  # Use .text to avoid markdown quoting
        c[3].write(fmt_duration(row["Time"]))
        c[4].write(f"{row['Percentage']:.1f}%")

        # Simple CSS bar
        bar_html = f"""
            <div style="width: 100%; background-color: #f0f2f6; border-radius: 4px; height: 18px; margin-top: 4px;">
                <div style="width: {row['Percentage']}%; background-color: {ZONE_COLORS_LIST[i]}; height: 100%; border-radius: 4px;"></div>
            </div>
        """
        c[5].markdown(bar_html, unsafe_allow_html=True)


def _render_plots(track_df, zones):
    z1, z2, z3, z4 = zones
    st.subheader("Performance Analysis")
    st.caption("Pace calculated using elapsed time")

    # Quadruple-stacked synchronized plots: Pace, Elevation, Cadence, HR
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.04)

    # 1. Pace (Top) - Standard ordering (Bottom-to-Top) with zone colors
    pace_df = track_df[(track_df["Pace_Decimal"] < 12) & (track_df["Pace_Decimal"] > 3)].copy()

    fig.add_trace(
        go.Scatter(
            x=pace_df["Elapsed Seconds"],
            y=pace_df["Pace_Decimal"],
            name="Pace",
            line={"color": "#88B4E7"},
        ),
        row=1,
        col=1,
    )
    # Using standard (non-reversed) axis as requested "bottom to top"
    fig.update_yaxes(title_text="Pace (min/km)", autorange="reversed", row=1, col=1, range=[12, 3])

    # 2. Elevation (Second from Top)
    if "Altitude" in track_df.columns:
        fig.add_trace(
            go.Scatter(
                x=track_df["Elapsed Seconds"],
                y=track_df["Altitude"],
                name="Elevation",
                line={"color": "#7DAF74"},
                fill="tozeroy",
                fillcolor="rgba(184,224,184,0.3)",
            ),
            row=2,
            col=1,
        )
        fig.update_yaxes(title_text="Elevation (m)", row=2, col=1)

    # 3. Cadence (Third from Top)
    cadence_col = "cadence" if "cadence" in track_df.columns else None
    if cadence_col:
        fig.add_trace(
            go.Scatter(
                x=track_df["Elapsed Seconds"],
                y=track_df[cadence_col],
                name="Cadence",
                line={"color": "#D4B8E8"},
            ),
            row=3,
            col=1,
        )
        fig.update_yaxes(title_text="Cadence (spm)", row=3, col=1)

    # 4. HR (Bottom) — line colored by zone
    hr_valid = track_df[["Elapsed Seconds", "HR"]].dropna().reset_index(drop=True)
    if not hr_valid.empty:
        hr_valid["zone_idx"] = hr_valid["HR"].apply(
            lambda h: 0 if h < z1 else 1 if h < z2 else 2 if h < z3 else 3 if h < z4 else 4
        )
        hr_valid["group"] = (hr_valid["zone_idx"] != hr_valid["zone_idx"].shift()).cumsum()

        zone_labels = ["Z1 Recovery", "Z2 Endurance", "Z3 Tempo", "Z4 Threshold", "Z5 Anaerobic"]
        shown_zones: set = set()

        for grp_id in hr_valid["group"].unique():
            seg = hr_valid[hr_valid["group"] == grp_id]
            zone_idx = int(seg["zone_idx"].iloc[0])
            # Extend one point on each side so adjacent segments share a boundary point
            start = max(0, seg.index[0] - 1)
            end = min(len(hr_valid) - 1, seg.index[-1] + 1)
            fig.add_trace(
                go.Scatter(
                    x=hr_valid.loc[start:end, "Elapsed Seconds"],
                    y=hr_valid.loc[start:end, "HR"],
                    mode="lines",
                    name=zone_labels[zone_idx],
                    legendgroup=f"hr_zone_{zone_idx}",
                    showlegend=zone_idx not in shown_zones,
                    line={"color": ZONE_COLORS_LIST[zone_idx], "width": 2},
                ),
                row=4,
                col=1,
            )
            shown_zones.add(zone_idx)
    fig.update_yaxes(title_text="Heart Rate (bpm)", row=4, col=1)

    # Format x-axis ticks as M:SS / H:MM:SS instead of raw seconds
    max_s = int(track_df["Elapsed Seconds"].max())
    step = 300 if max_s <= 1800 else 600 if max_s <= 5400 else 900
    tick_vals = list(range(0, max_s + step, step))

    def _fmt_s(s):
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"

    fig.update_xaxes(tickvals=tick_vals, ticktext=[_fmt_s(s) for s in tick_vals])
    fig.update_layout(height=850, hovermode="x unified", showlegend=True)
    st.plotly_chart(fig)


def _render_pace_bar_chart(df, label_col, title, time_basis="Elapsed Time"):
    """Render Strava-style pace bar chart (fast at top, slow at bottom)."""
    if df.empty:
        return

    df = df.copy()
    df = df[df["Pace"] > 0]

    if df.empty:
        st.write("No valid pace data available.")
        return

    df["Pace_Str"] = df["Pace"].apply(fmt_pace)

    # ---- stats ----
    min_pace = df["Pace"].min()  # fastest
    max_pace = df["Pace"].max()  # slowest

    y_min = max(3.0, min_pace - 0.5)
    y_max = min(10.0, max_pace + 0.5)

    # ---- bar logic (IMPORTANT PART) ----
    baseline = y_max

    fig = go.Figure()

    fig.add_trace(
        go.Bar(
            x=df[label_col],
            y=baseline - df["Pace"],  # bar height
            base=df["Pace"],  # bar starts at pace
            text=df["Pace_Str"],
            textposition="auto",
            showlegend=False,
            marker_color="#88B4E7",
        )
    )

    if "Min_Pace" in df.columns and "Max_Pace" in df.columns:
        has_range = df["Min_Pace"].notna() & df["Max_Pace"].notna()
        range_df = df[has_range]
        if not range_df.empty:
            # Vertical range lines (min to max) per bar
            xs, ys = [], []
            for _, row in range_df.iterrows():
                xs += [row[label_col], row[label_col], None]
                ys += [row["Min_Pace"], row["Max_Pace"], None]
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="lines",
                    name="Pace range",
                    line={"color": "#E07B39", "width": 2},
                    hoverinfo="skip",
                )
            )
            # Tick marks at fastest (min) and slowest (max)
            fig.add_trace(
                go.Scatter(
                    x=range_df[label_col],
                    y=range_df["Min_Pace"],
                    mode="markers",
                    name="Fastest",
                    marker={
                        "symbol": "line-ew",
                        "size": 10,
                        "color": "#E07B39",
                        "line": {"width": 2, "color": "#E07B39"},
                    },
                    text=range_df["Min_Pace"].apply(fmt_pace),
                    hovertemplate="%{text}/km<extra>Fastest</extra>",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=range_df[label_col],
                    y=range_df["Max_Pace"],
                    mode="markers",
                    name="Slowest",
                    marker={
                        "symbol": "line-ew",
                        "size": 10,
                        "color": "#E07B39",
                        "line": {"width": 2, "color": "#E07B39"},
                    },
                    text=range_df["Max_Pace"].apply(fmt_pace),
                    hovertemplate="%{text}/km<extra>Slowest</extra>",
                )
            )

    # ---- y-axis ticks ----
    tick_vals = list(range(int(y_min), int(y_max) + 1))
    tick_texts = [f"{t}:00/km" for t in tick_vals]

    fig.update_layout(
        title=f"{title} (based on {time_basis})",
        xaxis_title=label_col,
        yaxis={
            "autorange": "reversed",
            "tickmode": "array",
            "tickvals": tick_vals,
            "ticktext": tick_texts,
        },
        height=400,
    )

    st.plotly_chart(fig)


def _render_splits_table(track_df):
    """Render splits table with consistent data."""
    st.subheader("Splits")
    st.caption("Pace calculated using elapsed time")
    splits = _calculate_splits(track_df)

    if splits.empty:
        st.write("No split data available.")
        return

    display_splits = splits.copy()
    display_splits["Pace"] = display_splits["Pace"].apply(fmt_pace)
    display_splits["Avg HR"] = display_splits["Avg HR"].apply(
        lambda x: f"{x:.0f} bpm" if pd.notna(x) else "N/A"
    )
    if "Cadence" in display_splits.columns:
        display_splits["Cadence"] = display_splits["Cadence"].apply(
            lambda x: f"{x:.0f} spm" if pd.notna(x) else "N/A"
        )
    display_splits["Distance"] = display_splits["Distance"].apply(lambda x: f"{x:.2f} km")

    st.dataframe(display_splits, width="stretch")


def _get_available_activities():
    """Get activities that have stream data available."""
    # Use database helper to find activities with streams
    activities = get_activities_with_streams()

    if activities.empty:
        return pd.DataFrame()

    # Ensure date column is datetime
    if "activity_date" in activities.columns:
        activities["activity_date"] = pd.to_datetime(activities["activity_date"])

    # Filter for Runs
    mask = activities["activity_type"] == "Run"
    return activities[mask].copy().sort_values(by="activity_date", ascending=False)


def _display_stats(track_df, selected_row):
    # Summary data from Strava OR fallback to calculated from tracks
    dist_km = selected_row.get("distance", track_df["Distance"].max() / 1000)

    # Try using summary moving time, else sum
    if "moving_time" in selected_row and pd.notna(selected_row["moving_time"]):
        moving_s = selected_row["moving_time"]
    else:
        moving_s = track_df[track_df["Is_Moving"]]["Time_Diff"].sum()

    elapsed_s = selected_row.get("elapsed_time", track_df["Elapsed Seconds"].max())
    elev_gain = selected_row.get("elevation_gain", track_df["Elev_Gain_Step"].sum())

    effort = selected_row.get("suffer_score", "N/A")
    calories = selected_row.get("calories", "N/A")

    avg_pace_dec = ((moving_s / 60) / dist_km) if dist_km > 0 else 0

    # Top Metrics
    st.markdown(f"## {dist_km:.2f} km | {fmt_duration(moving_s)} | {fmt_pace(avg_pace_dec)}/km")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Relative Effort", effort)
    col2.metric("Elevation Gain", f"{elev_gain:.0f} m")
    col3.metric("Calories", f"{calories:.0f}" if pd.notna(calories) else "N/A")
    col4.metric("Elapsed Time", fmt_duration(elapsed_s))

    st.markdown("---")

    col1, col2, col3 = st.columns(3)
    avg_hr = selected_row.get("average_heart_rate", track_df["HR"].mean())
    max_hr = selected_row.get("max_heart_rate", track_df["HR"].max())
    col1.metric("Avg HR", f"{avg_hr:.0f} bpm")
    col2.metric("Max HR", f"{max_hr:.0f} bpm")

    # Cadence if available
    if "cadence" in track_df.columns:
        # Avoid mean of 0 cadence?
        avg_cadence = track_df[track_df["Is_Moving"]]["cadence"].mean()
        col3.metric(
            "Avg Cadence",
            f"{avg_cadence:.0f} spm" if pd.notna(avg_cadence) else "N/A",
        )
    else:
        col3.metric("Avg Cadence", "N/A")


def _has_meaningful_laps(laps_df):
    """Return True if laps exist and are not just ~1km auto-splits.

    The last lap of any run is always a partial km, so it's excluded from
    the check — only the preceding laps need to be ~1km for the set to be
    considered redundant with splits.
    """
    if laps_df is None or laps_df.empty:
        return False
    # Exclude the last (partial) lap before checking
    check = laps_df.iloc[:-1] if len(laps_df) > 1 else laps_df
    return not check["Distance"].between(0.9, 1.1).all()


_REST_PACE_THRESHOLD = 12  # min/km — laps slower than this are excluded from the chart


def _enrich_laps(laps_df, track_df):
    """Add Pace, Min_Pace, Max_Pace to laps_df using track_df stream data."""
    df = laps_df.copy()
    df["Pace"] = (df["Time"] / df["Distance"]) / 60

    # Reconstruct approximate lap start/end from cumulative elapsed time
    df["_end_s"] = df["Time"].cumsum()
    df["_start_s"] = df["_end_s"] - df["Time"]

    min_paces, max_paces = [], []
    for _, row in df.iterrows():
        lap_track = track_df[
            (track_df["Elapsed Seconds"] >= row["_start_s"])
            & (track_df["Elapsed Seconds"] < row["_end_s"])
        ]
        valid = lap_track["Pace_Decimal"].dropna()
        valid = valid[(valid > 3) & (valid < 12)]
        min_paces.append(float(valid.quantile(0.1)) if not valid.empty else None)
        max_paces.append(float(valid.quantile(0.9)) if not valid.empty else None)

    df["Min_Pace"] = min_paces
    df["Max_Pace"] = max_paces
    return df.drop(columns=["_start_s", "_end_s"])


def _render_laps_tab(laps_df, track_df):
    st.info("Device Recorded Laps")
    st.caption("Pace calculated using elapsed time")

    l_chart = _enrich_laps(laps_df, track_df)

    # Exclude rest laps from the chart — they distort the y-axis and aren't useful
    active_laps = l_chart[l_chart["Pace"] < _REST_PACE_THRESHOLD]
    rest_count = len(l_chart) - len(active_laps)
    if rest_count:
        st.caption(
            f"{rest_count} rest lap(s) hidden from chart" f" (pace > {_REST_PACE_THRESHOLD} min/km)"
        )

    _render_pace_bar_chart(active_laps, "Lap", "Pace per Lap", "Elapsed Time")

    # Format all laps for the table (rest laps included)
    l_display = l_chart.copy()
    l_display["Pace"] = l_display["Pace"].apply(fmt_pace)
    l_display["Time"] = l_display["Time"].apply(fmt_duration)
    l_display["Distance"] = l_display["Distance"].apply(lambda x: f"{x:.2f} km")
    l_display["Avg HR"] = l_display["Avg HR"].apply(lambda x: f"{x:.0f}" if pd.notna(x) else "N/A")
    l_display["Cadence"] = l_display["Cadence"].apply(
        lambda x: f"{x:.0f}" if pd.notna(x) else "N/A"
    )
    l_display = l_display.drop(columns=["Min_Pace", "Max_Pace"])

    st.dataframe(l_display, width="stretch")


def _render_deep_dive_tabs(track_df, laps_df, zones):
    show_laps = _has_meaningful_laps(laps_df)

    tab_labels = ["Analysis", "Splits"]
    if show_laps:
        tab_labels.append("Laps")
    tab_labels.append("Route Map")

    tabs = st.tabs(tab_labels)
    tab_idx = 0

    with tabs[tab_idx]:  # Analysis
        _render_plots(track_df, zones)
        _render_hr_analysis(track_df, zones)
    tab_idx += 1

    with tabs[tab_idx]:  # Splits
        st.info("Kilometer splits (Auto-calculated)")
        splits = _calculate_splits(track_df)
        if not splits.empty:
            _render_pace_bar_chart(splits, "KM", "Pace per Kilometer", "Moving Time")
            _render_splits_table(track_df)
    tab_idx += 1

    if show_laps:
        with tabs[tab_idx]:  # Laps
            _render_laps_tab(laps_df, track_df)
        tab_idx += 1

    with tabs[tab_idx]:  # Route Map
        _render_route_map(track_df, zones)


def _hex_gradient(t: float, low: str, high: str) -> str:
    """Linearly interpolate between two hex colours, t in [0, 1]."""
    t = max(0.0, min(1.0, t))
    lr, lg, lb = int(low[1:3], 16), int(low[3:5], 16), int(low[5:7], 16)
    hr, hg, hb = int(high[1:3], 16), int(high[3:5], 16), int(high[5:7], 16)
    return (
        f"#{int(lr + (hr - lr) * t):02x}{int(lg + (hg - lg) * t):02x}{int(lb + (hb - lb) * t):02x}"
    )


def _draw_colored_route(m, gps_df, metric_col, color_fn):
    """Draw route as consecutive same-colour PolyLine segments."""
    current_color = None
    current_coords = []

    for _, row in gps_df.iterrows():
        color = color_fn(row.get(metric_col))
        coord = (row["latitude"], row["longitude"])
        if color != current_color:
            if current_coords:
                current_coords.append(coord)  # bridge point to avoid gaps
                folium.PolyLine(current_coords, color=current_color, weight=4, opacity=0.9).add_to(
                    m
                )
            current_color = color
            current_coords = [coord]
        else:
            current_coords.append(coord)

    if current_coords and current_color:
        folium.PolyLine(current_coords, color=current_color, weight=4, opacity=0.9).add_to(m)


def _build_color_setup(color_by, gps_df, zones):
    """Return (metric_col, color_fn) and render the legend for the chosen mode."""
    z1, z2, z3, z4 = zones
    if color_by == "Heart Rate":
        zone_defs = [
            (ZONE_COLORS_LIST[0], f"Z1 &lt;{z1}"),
            (ZONE_COLORS_LIST[1], f"Z2 {z1}–{z2}"),
            (ZONE_COLORS_LIST[2], f"Z3 {z2}–{z3}"),
            (ZONE_COLORS_LIST[3], f"Z4 {z3}–{z4}"),
            (ZONE_COLORS_LIST[4], f"Z5 &gt;{z4}"),
        ]
        badges = " ".join(
            f'<span style="background:{c};padding:3px 10px;border-radius:4px;'
            f'font-size:0.82em;color:#222;">{l}</span>'
            for c, l in zone_defs
        )
        st.markdown(badges, unsafe_allow_html=True)

        def _hr_color(val):
            if pd.isna(val):
                return "#808080"
            if val < z1:
                return ZONE_COLORS_LIST[0]
            if val < z2:
                return ZONE_COLORS_LIST[1]
            if val < z3:
                return ZONE_COLORS_LIST[2]
            if val < z4:
                return ZONE_COLORS_LIST[3]
            return ZONE_COLORS_LIST[4]

        return "HR", _hr_color

    if color_by == "Pace":
        valid_pace = gps_df["Pace_Decimal"].replace(0, pd.NA).dropna()
        valid_pace = valid_pace[(valid_pace > 2) & (valid_pace < 15)]
        p_min = float(valid_pace.quantile(0.05)) if not valid_pace.empty else 3.0
        p_max = float(valid_pace.quantile(0.95)) if not valid_pace.empty else 8.0
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:8px;margin:4px 0 8px 0;">'
            f'<span style="font-size:0.82em;white-space:nowrap;">Fast ({fmt_pace(p_min)}/km)</span>'
            f'<div style="flex:1;height:12px;border-radius:6px;'
            f'background:linear-gradient(to right,#B8E0B8,#F4A0A0);"></div>'
            f'<span style="font-size:0.82em;white-space:nowrap;">Slow ({fmt_pace(p_max)}/km)</span>'
            f"</div>",
            unsafe_allow_html=True,
        )

        def _pace_color(val):
            if pd.isna(val) or val <= 0:
                return "#808080"
            t = (val - p_min) / (p_max - p_min) if p_max > p_min else 0.5
            return _hex_gradient(t, "#B8E0B8", "#F4A0A0")

        return "Pace_Decimal", _pace_color

    if color_by == "Elevation":
        e_min = float(gps_df["Altitude"].min())
        e_max = float(gps_df["Altitude"].max())
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:8px;margin:4px 0 8px 0;">'
            f'<span style="font-size:0.82em;white-space:nowrap;">Low ({e_min:.0f} m)</span>'
            f'<div style="flex:1;height:12px;border-radius:6px;'
            f'background:linear-gradient(to right,#88B4E7,#F4A0A0);"></div>'
            f'<span style="font-size:0.82em;white-space:nowrap;">High ({e_max:.0f} m)</span>'
            f"</div>",
            unsafe_allow_html=True,
        )

        def _elev_color(val):
            if pd.isna(val):
                return "#808080"
            t = (val - e_min) / (e_max - e_min) if e_max > e_min else 0.5
            return _hex_gradient(t, "#88B4E7", "#F4A0A0")

        return "Altitude", _elev_color

    return None, None


@st.fragment
def _render_route_map(track_df, zones):
    """Render GPS route map using folium."""
    st.subheader("Route Map")

    if "latitude" not in track_df.columns or "longitude" not in track_df.columns:
        st.warning("No GPS data available for this activity.")
        return

    gps_df = track_df.dropna(subset=["latitude", "longitude"]).copy()

    if gps_df.empty:
        st.warning("No valid GPS coordinates found.")
        return

    # Build list of available colour modes
    color_options = []
    if "HR" in gps_df.columns and gps_df["HR"].notna().any():
        color_options.append("Heart Rate")
    if "Pace_Decimal" in gps_df.columns and gps_df["Pace_Decimal"].notna().any():
        color_options.append("Pace")
    if "Altitude" in gps_df.columns and gps_df["Altitude"].notna().any():
        color_options.append("Elevation")

    col_color, col_tile = st.columns(2)
    color_by = col_color.radio(
        "Color route by", color_options if color_options else ["None"], horizontal=True
    )
    tile_style = col_tile.radio(
        "Map style",
        ["Light", "Dark", "Street"],
        horizontal=True,
    )

    _TILE_PROVIDERS = {
        "Street": "OpenStreetMap",
        "Light": "CartoDB Positron",
        "Dark": "CartoDB DarkMatter",
    }

    metric_col, color_fn = _build_color_setup(color_by, gps_df, zones)

    center_lat = gps_df["latitude"].mean()
    center_lon = gps_df["longitude"].mean()
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=13,
        tiles=_TILE_PROVIDERS[tile_style],
    )

    if color_fn and metric_col:
        _draw_colored_route(m, gps_df, metric_col, color_fn)
    else:
        route_color = (
            "#555555" if tile_style == "Light" else "#aaaaaa" if tile_style == "Dark" else "#3388ff"
        )
        coordinates = list(zip(gps_df["latitude"], gps_df["longitude"]))
        folium.PolyLine(coordinates, color=route_color, weight=3, opacity=0.8).add_to(m)

    # Kilometre markers
    if "Distance" in gps_df.columns and gps_df["Distance"].notna().any():
        max_dist_m = gps_df["Distance"].max()
        for km in range(1, int(max_dist_m / 1000) + 1):
            target = km * 1000
            closest = gps_df.iloc[(gps_df["Distance"] - target).abs().argsort().iloc[0]]
            folium.Marker(
                location=[closest["latitude"], closest["longitude"]],
                icon=folium.DivIcon(
                    html=(
                        f'<div style="font-size:10px;font-weight:bold;color:#fff;'
                        f"background:#333;border-radius:50%;width:20px;height:20px;"
                        f'text-align:center;line-height:20px;border:1px solid #fff;">'
                        f"{km}</div>"
                    ),
                    icon_size=(20, 20),
                    icon_anchor=(10, 10),
                ),
            ).add_to(m)

    coordinates = list(zip(gps_df["latitude"], gps_df["longitude"]))
    folium.Marker(
        coordinates[0], popup="Start", icon=folium.Icon(color="green", icon="play")
    ).add_to(m)
    folium.Marker(
        coordinates[-1], popup="Finish", icon=folium.Icon(color="red", icon="stop")
    ).add_to(m)

    folium_static(m, width=1600, height=500)


def page_recent_activities(_, zones):
    st.header("Deep Dive Analysis")

    available_activities = _get_available_activities()
    if available_activities.empty:
        st.warning("No activities with stream data found. Try importing detailed data.")
        return

    options = available_activities.apply(
        lambda x: f"{x['activity_date'].date()} - {x.get('activity_name', 'Unknown')}",
        axis=1,
    ).tolist()

    # Handle pre-selected activity from other pages
    default_index = 0
    if "selected_activity_id" in st.session_state:
        requested_id = st.session_state.pop("selected_activity_id")
        matches = available_activities[available_activities["activity_id"] == requested_id]
        if not matches.empty:
            default_index = available_activities.index.get_loc(matches.index[0])

    selected_option = st.selectbox("Select Activity", options, index=default_index)
    if not selected_option:
        return

    idx = options.index(selected_option)
    selected_row = available_activities.iloc[idx]

    with st.spinner("Loading activity data..."):
        try:
            track_df = get_activity_stream(selected_row["activity_id"])
            laps_df = get_activity_laps(selected_row["activity_id"])

            if not track_df.empty:
                # Rename columns to match existing logic
                rename_map = {
                    "heart_rate": "HR",
                    "altitude": "Altitude",
                    "distance": "Distance",
                    "timestamp": "Time",
                    "latitude": "latitude",  # Keep as is for GPS mapping
                    "longitude": "longitude",  # Keep as is for GPS mapping
                }
                track_df = track_df.rename(columns=rename_map)
                # Ensure proper types
                if "Time" in track_df.columns:
                    track_df["Time"] = pd.to_datetime(track_df["Time"])

                track_df = _calculate_metrics(track_df)

                if track_df is None or track_df.empty:
                    st.error("Processing failed: `_calculate_metrics` returned empty data.")
                    return

                _display_stats(track_df, selected_row)
                _render_deep_dive_tabs(track_df, laps_df, zones)
            else:
                st.error(f"No stream records found for activity {selected_row['activity_id']}.")
                st.info("Try refreshing data from Strava if this is a new activity.")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            st.error(f"Error loading stream data: {exc}")
            st.exception(exc)
