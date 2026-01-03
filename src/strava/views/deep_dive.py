import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import folium
from streamlit_folium import folium_static
from strava.data import get_activity_stream
from strava.utils.activity_processing import _calculate_metrics, _calculate_splits
from strava.utils.file_parsing import load_and_parse_file


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

    bar_colors = ["#BDBDBD", "#64B5F6", "#81C784", "#FFB74D", "#E57373"]

    for i, row in enumerate(zone_data):
        c = st.columns([1, 2, 2, 1, 1, 3])
        c[0].write(row["Zone"])
        c[1].write(row["Description"])
        c[2].text(row["Range"])  # Use .text to avoid markdown quoting
        c[3].write(format_duration(row["Time"]))
        c[4].write(f"{row['Percentage']:.1f}%")

        # Simple CSS bar
        bar_html = f"""
            <div style="width: 100%; background-color: #f0f2f6; border-radius: 4px; height: 18px; margin-top: 4px;">
                <div style="width: {row['Percentage']}%; background-color: {bar_colors[i]}; height: 100%; border-radius: 4px;"></div>
            </div>
        """
        c[5].markdown(bar_html, unsafe_allow_html=True)


def _render_plots(track_df, zones):
    st.subheader("Performance Analysis")
    st.caption("Pace calculated using elapsed time")

    # Triple-stacked synchronized plots: Pace, Cadence, HR
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.05)

    # 1. Pace (Top) - Standard ordering (Bottom-to-Top) with zone colors
    pace_df = track_df[(track_df["Pace_Decimal"] < 12) & (track_df["Pace_Decimal"] > 3)].copy()

    # Add pace zone colors as background bands
    # Zone shading removed from Pace plot as requested

    # Add HR zone colors as background bands for HR plot
    hr_zones = zones  # (z1, z2, z3, z4)
    # Define 5 zones: Z1 (<z1), Z2 (z1-z2), Z3 (z2-z3), Z4 (z3-z4), Z5 (>z4)
    hr_zone_defs = [
        (0, hr_zones[0]),  # Z1
        (hr_zones[0], hr_zones[1]),  # Z2
        (hr_zones[1], hr_zones[2]),  # Z3
        (hr_zones[2], hr_zones[3]),  # Z4
        (hr_zones[3], 220),  # Z5 (cap at 220 or max HR)
    ]
    hr_zone_colors = ["#BDBDBD", "#64B5F6", "#81C784", "#FFB74D", "#E57373"]
    hr_zone_names = ["Z1", "Z2", "Z3", "Z4", "Z5"]

    for i, (z_min, z_max) in enumerate(hr_zone_defs):
        fig.add_shape(
            type="rect",
            xref="x",
            yref="y",
            x0=track_df["Elapsed Seconds"].min(),
            x1=track_df["Elapsed Seconds"].max(),
            y0=z_min,
            y1=z_max,
            fillcolor=hr_zone_colors[i],
            opacity=0.2,
            layer="below",
            line_width=0,
            row=3,
            col=1,
        )
        # Add zone label
        fig.add_annotation(
            xref="x",
            yref="y",
            x=track_df["Elapsed Seconds"].min(),  # Label on Left
            y=(z_min + z_max) / 2,  # Center of zone
            text=hr_zone_names[i],
            showarrow=False,
            xanchor="left",
            font={"size": 10, "color": "black"},  # Black text for visibility on light/colored bg
            row=3,
            col=1,
        )

    fig.add_trace(
        go.Scatter(
            x=pace_df["Elapsed Seconds"],
            y=pace_df["Pace_Decimal"],
            name="Pace",
            line={"color": "blue"},
        ),
        row=1,
        col=1,
    )
    # Using standard (non-reversed) axis as requested "bottom to top"
    fig.update_yaxes(title_text="Pace (min/km)", autorange="reversed", row=1, col=1, range=[12, 3])

    # 2. Cadence (Middle)
    cadence_col = "cadence" if "cadence" in track_df.columns else None
    if cadence_col:
        fig.add_trace(
            go.Scatter(
                x=track_df["Elapsed Seconds"],
                y=track_df[cadence_col],
                name="Cadence",
                line={"color": "purple"},
            ),
            row=2,
            col=1,
        )
        fig.update_yaxes(title_text="Cadence (spm)", row=2, col=1)

    # 3. HR (Bottom)
    fig.add_trace(
        go.Scatter(
            x=track_df["Elapsed Seconds"],
            y=track_df["HR"],
            name="Heart Rate",
            line={"color": "red"},
        ),
        row=3,
        col=1,
    )
    fig.update_yaxes(title_text="Heart Rate (bpm)", row=3, col=1)

    fig.update_layout(height=700, hovermode="x unified", showlegend=True)
    st.plotly_chart(fig, use_container_width=True)


def _render_pace_bar_chart(df, label_col, title, time_basis="Elapsed Time"):
    """Render Strava-style pace bar chart (fast at top, slow at bottom)."""
    if df.empty:
        return

    # ---- helpers ----
    def fmt(p):
        if pd.isna(p) or p <= 0:
            return "N/A"
        m = int(p)
        s = int((p - m) * 60)
        return f"{m}:{s:02d}"

    df = df.copy()
    df = df[df["Pace"] > 0]

    if df.empty:
        st.write("No valid pace data available.")
        return

    df["Pace_Str"] = df["Pace"].apply(fmt)

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
        margin={"r": 140, "b": 150},
        height=400,
    )

    st.plotly_chart(fig, use_container_width=True)


def _render_splits_table(track_df):
    """Render splits table with consistent data."""
    st.subheader("Splits")
    st.caption("Pace calculated using elapsed time")
    splits = _calculate_splits(track_df)

    if splits.empty:
        st.write("No split data available.")
        return

    def fmt_pace(p):
        if pd.isna(p) or p == 0:
            return "N/A"
        return f"{int(p)}:{int((p%1)*60):02d}"

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

    st.dataframe(display_splits, use_container_width=True)


def _get_available_activities(df):
    if "filename" not in df.columns:
        st.error("Filename column missing in data.")
        return pd.DataFrame()

    mask = df["filename"].str.contains(r"\.(?:tcx|fit)", case=False, na=False) & (
        df["activity_type"] == "Run"
    )
    return df[mask].copy().sort_values(by="activity_date", ascending=False)


def format_duration(seconds):
    if pd.isna(seconds) or seconds is None:
        return "N/A"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _display_stats(track_df, selected_row):
    # Summary data from Strava
    dist_km = selected_row.get("distance", track_df["Distance"].max() / 1000)
    moving_s = selected_row.get("moving_time", track_df[track_df["Is_Moving"]]["Time_Diff"].sum())
    elapsed_s = selected_row.get("elapsed_time", track_df["Elapsed Seconds"].max())
    elev_gain = selected_row.get("elevation_gain", track_df["Elev_Gain_Step"].sum())

    effort = selected_row.get("relative_effort", "N/A")
    calories = selected_row.get("calories", "N/A")
    gear = selected_row.get("gear", "N/A")

    avg_pace_dec = ((moving_s / 60) / dist_km) if dist_km > 0 else 0

    # Top Metrics
    pace_str = f"{int(avg_pace_dec)}:{int((avg_pace_dec % 1) * 60):02d}"
    st.markdown(f"## {dist_km:.2f} km | {format_duration(moving_s)} | {pace_str}/km")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Relative Effort", effort)
    col2.metric("Elevation Gain", f"{elev_gain:.0f} m")
    col3.metric("Calories", f"{calories:.0f}" if pd.notna(calories) else "N/A")
    col4.metric("Elapsed Time", format_duration(elapsed_s))

    st.markdown("---")

    col1, col2, col3, col4 = st.columns(4)
    avg_hr = selected_row.get("average_heart_rate", track_df["HR"].mean())
    max_hr = selected_row.get("max_heart_rate", track_df["HR"].max())
    col1.metric("Avg HR", f"{avg_hr:.0f} bpm")
    col2.metric("Max HR", f"{max_hr:.0f} bpm")
    col3.metric("Gear", gear)

    # Cadence if available
    if "cadence" in track_df.columns:
        avg_cadence = track_df[track_df["Is_Moving"]]["cadence"].mean()
        col4.metric(
            "Avg Cadence",
            f"{avg_cadence:.0f} spm" if pd.notna(avg_cadence) else "N/A",
        )
    else:
        col4.metric("Avg Cadence", "N/A")


def _render_deep_dive_tabs(track_df, laps_df, zones):
    # Layout like Strava with Route Map tab
    tab1, tab2, tab3, tab4 = st.tabs(["Analysis", "Splits", "Laps", "Route Map"])

    with tab1:
        _render_plots(track_df, zones)
        _render_hr_analysis(track_df, zones)

    with tab2:
        st.info("Kilometer splits (Auto-calculated)")
        splits = _calculate_splits(track_df)
        if not splits.empty:
            _render_pace_bar_chart(splits, "KM", "Pace per Kilometer", "Elapsed Time")
            _render_splits_table(track_df)

    with tab3:
        if laps_df is not None and not laps_df.empty:
            st.info("Device Recorded Laps")
            st.caption("Pace calculated using elapsed time")

            l_display = laps_df.copy()
            l_display["Pace"] = (l_display["Time"] / l_display["Distance"]) / 60

            # Render bar chart before formatting columns to strings
            _render_pace_bar_chart(l_display, "Lap", "Pace per Lap", "Elapsed Time")

            # Format for display
            l_display["Pace"] = l_display["Pace"].apply(
                lambda x: f"{int(x)}:{int((x % 1) * 60):02d}"
            )
            l_display["Time"] = l_display["Time"].apply(format_duration)
            l_display["Distance"] = l_display["Distance"].apply(lambda x: f"{x:.2f} km")
            l_display["Avg HR"] = l_display["Avg HR"].apply(
                lambda x: f"{x:.0f}" if pd.notna(x) else "N/A"
            )
            l_display["Cadence"] = l_display["Cadence"].apply(
                lambda x: f"{x:.0f}" if pd.notna(x) else "N/A"
            )

            st.dataframe(l_display, use_container_width=True)
        else:
            st.info("No device laps found. Showing 1km splits.")
            _render_splits_table(track_df)

    with tab4:
        _render_route_map(track_df)


def _render_route_map(track_df):
    """Render GPS route map using folium."""
    st.subheader("Route Map")

    # Get GPS coordinates from database stream
    if "latitude" not in track_df.columns or "longitude" not in track_df.columns:
        st.warning("No GPS data available for this activity.")
        return

    # Filter out null coordinates
    gps_df = track_df.dropna(subset=["latitude", "longitude"])

    if gps_df.empty:
        st.warning("No valid GPS coordinates found.")
        return

    # Create map centered on the route
    center_lat = gps_df["latitude"].mean()
    center_lon = gps_df["longitude"].mean()

    m = folium.Map(location=[center_lat, center_lon], zoom_start=13)

    # Create route coordinates
    coordinates = list(zip(gps_df["latitude"], gps_df["longitude"]))

    # Add route line
    folium.PolyLine(coordinates, color="blue", weight=3, opacity=0.8).add_to(m)

    # Add start marker (green)
    folium.Marker(
        coordinates[0], popup="Start", icon=folium.Icon(color="green", icon="play")
    ).add_to(m)

    # Add finish marker (red)
    folium.Marker(
        coordinates[-1], popup="Finish", icon=folium.Icon(color="red", icon="stop")
    ).add_to(m)

    # Render the map
    # Use a large width to fill the container (standard Streamlit wide mode is ~1200px)
    folium_static(m, width=1600, height=500)


def page_recent_activities(df, zones):
    st.header("Deep Dive Analysis")

    available_activities = _get_available_activities(df)
    if available_activities.empty:
        st.warning("No activities with TCX/FIT data found.")
        return

    options = available_activities.apply(
        lambda x: f"{x['activity_date'].date()} - {x.get('activity_name', 'Unknown')}",
        axis=1,
    ).tolist()

    selected_option = st.selectbox("Select Activity", options)
    if not selected_option:
        return

    idx = options.index(selected_option)
    selected_row = available_activities.iloc[idx]

    with st.spinner("Loading activity data..."):
        track_df = get_activity_stream(selected_row["activity_id"])
        laps_df = pd.DataFrame()

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
            track_df["Time"] = pd.to_datetime(track_df["Time"])
            track_df = _calculate_metrics(track_df)
            # Try to load laps from file anyway if needed, or stick to auto-splits
            # For now, let's also try to load laps if it's a FIT file
            if ".fit" in selected_row["filename"].lower():
                _, laps_df = load_and_parse_file(selected_row["filename"])
        else:
            # Fallback to file parsing
            track_df, laps_df = load_and_parse_file(selected_row["filename"])

        if track_df is not None:
            _display_stats(track_df, selected_row)
            _render_deep_dive_tabs(track_df, laps_df, zones)
