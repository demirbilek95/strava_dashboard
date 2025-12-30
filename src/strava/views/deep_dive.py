import gzip
import os
import tempfile
import streamlit as st
import pandas as pd
import plotly.express as px
import tcxparser
import garmin_fit_sdk


def _get_project_root():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))


def _parse_fit(file_content):
    timestamps = []
    hrs = []
    alts = []
    dists = []
    parsing_error = None

    try:
        stream = garmin_fit_sdk.Stream.from_byte_array(file_content)
        decoder = garmin_fit_sdk.Decoder(stream)
        messages, errors = decoder.read()

        if errors:
            parsing_error = str(errors)

        if "record_mesgs" in messages:
            for record in messages["record_mesgs"]:
                timestamps.append(record.get("timestamp"))
                hrs.append(record.get("heart_rate"))
                alt = (
                    record.get("enhanced_altitude")
                    if record.get("enhanced_altitude") is not None
                    else record.get("altitude")
                )
                alts.append(alt)
                dists.append(record.get("distance"))
    except Exception as e:
        parsing_error = str(e)

    return timestamps, hrs, alts, dists, parsing_error


def _parse_tcx(tmp_path):
    tcx = tcxparser.TCXParser(tmp_path)
    return (tcx.time_values(), tcx.hr_values(), tcx.altitude_points(), tcx.distance_values(), None)


def _create_track_df(timestamps, hrs, alts, dists):
    if not timestamps:
        return pd.DataFrame()

    min_len = len(timestamps)

    # helper to pad/trunc list
    def adjust(lst):
        if len(lst) < min_len:
            return lst + [None] * (min_len - len(lst))
        elif len(lst) > min_len:
            return lst[:min_len]
        return lst

    hrs = adjust(hrs)
    alts = adjust(alts)
    dists = adjust(dists)

    track_df = pd.DataFrame(
        {
            "Time": pd.to_datetime(timestamps, errors="coerce"),
            "HR": hrs,
            "Altitude": alts,
            "Distance": dists,
        }
    )

    track_df["HR"] = pd.to_numeric(track_df["HR"], errors="coerce")
    track_df["Altitude"] = pd.to_numeric(track_df["Altitude"], errors="coerce")
    track_df["Distance"] = pd.to_numeric(track_df["Distance"], errors="coerce")

    # Fill gaps
    track_df["Distance"] = track_df["Distance"].ffill()
    track_df["Altitude"] = track_df["Altitude"].ffill()
    track_df["HR"] = track_df["HR"].ffill()

    track_df = track_df.dropna(subset=["Time"])
    return track_df


def _calculate_metrics(track_df):
    if track_df.empty:
        return None

    # Elapsed Seconds
    track_df["Elapsed Seconds"] = (track_df["Time"] - track_df["Time"].iloc[0]).dt.total_seconds()

    # Smooth Speed/Pace
    track_df["Dist_Diff"] = track_df["Distance"].diff()
    track_df["Time_Diff"] = track_df["Elapsed Seconds"].diff()
    track_df["Speed_m_s"] = track_df["Dist_Diff"] / track_df["Time_Diff"]

    track_df["Speed_Smooth"] = track_df["Speed_m_s"].rolling(window=10, min_periods=1).mean()

    def get_pace(speed_ms):
        if pd.isna(speed_ms):
            return None
        if speed_ms > 0.1:
            return (1000 / speed_ms) / 60
        return None

    track_df["Pace_Decimal"] = track_df["Speed_Smooth"].apply(get_pace)
    return track_df


def _render_plots(track_df, zones):
    z1, z2, z3, z4 = zones

    # 1. HR Profile
    st.subheader("Heart Rate Profile")
    fig_hr = px.line(track_df, x="Elapsed Seconds", y="HR", title="Heart Rate Profile")

    # Add zones
    colors = ["gray", "blue", "green", "orange", "red"]
    limits = [0, z1, z2, z3, z4, 240]
    labels = ["Z1", "Z2", "Z3", "Z4", "Z5"]

    for i in range(5):
        fig_hr.add_hrect(
            y0=limits[i],
            y1=limits[i + 1],
            line_width=0,
            fillcolor=colors[i],
            opacity=0.1,
            annotation_text=labels[i],
            annotation_position="top left",
        )
    st.plotly_chart(fig_hr, use_container_width=True)

    # 2. Pace Profile
    st.subheader("Pace Profile (Smoothed)")
    pace_filtered = track_df[
        (track_df["Pace_Decimal"] < 15) & (track_df["Pace_Decimal"] > 2)
    ].copy()

    if not pace_filtered.empty:
        fig_pace = px.line(
            pace_filtered, x="Elapsed Seconds", y="Pace_Decimal", title="Pace Profile"
        )
        fig_pace.update_yaxes(autorange="reversed")
        st.plotly_chart(fig_pace, use_container_width=True)

    # 3. Zone Distribution
    st.subheader("Zone Distribution (This Activity)")

    def get_zone_local(h):
        if pd.isna(h):
            return None
        for z_limit, label in zip([z1, z2, z3, z4], ["Z1", "Z2", "Z3", "Z4"]):
            if h <= z_limit:
                return label
        return "Z5"

    track_df["Zone"] = track_df["HR"].apply(get_zone_local)
    zone_dist = track_df.groupby("Zone")["Time_Diff"].sum().reset_index()
    zone_dist["Minutes"] = zone_dist["Time_Diff"] / 60

    if not zone_dist.empty:
        fig_pie = px.pie(
            zone_dist,
            values="Minutes",
            names="Zone",
            title="Time in Zones",
            color="Zone",
            color_discrete_map={
                "Z1": "gray",
                "Z2": "blue",
                "Z3": "green",
                "Z4": "orange",
                "Z5": "red",
            },
            category_orders={"Zone": ["Z1", "Z2", "Z3", "Z4", "Z5"]},
        )
        st.plotly_chart(fig_pie, use_container_width=True)


def page_recent_activities(df, zones):
    st.header("Deep Dive Analysis")
    st.caption("Detailed analysis of individual activities using raw track data (TCX files).")

    if "filename" not in df.columns:
        st.error("Filename column missing in data.")
        return

    mask = df["filename"].str.contains(r"\.(?:tcx|fit)", case=False, na=False) & (
        df["activity_type"] == "Run"
    )
    available_activities = df[mask].copy().sort_values(by="activity_date", ascending=False)

    if available_activities.empty:
        st.warning("No activities with TCX/FIT data found.")
        return

    options = available_activities.apply(
        lambda x: f"{x['activity_date'].date()} - {x.get('activity_name', 'Unknown')} ({x['activity_type']})",
        axis=1,
    ).tolist()

    selected_option = st.selectbox("Select Activity", options)
    if not selected_option:
        return

    idx = options.index(selected_option)
    selected_row = available_activities.iloc[idx]

    st.subheader(
        f"{selected_row.get('activity_name', 'Unknown')} - {selected_row['activity_date'].date()}"
    )
    if pd.notna(selected_row.get("activity_description")):
        st.markdown(f"*{selected_row['activity_description']}*")

    # Load File
    file_rel_path = selected_row["filename"]
    project_root = _get_project_root()
    file_path = os.path.join(project_root, "data", file_rel_path)

    if not os.path.exists(file_path):
        st.error(f"File not found: {file_path}")
        return

    with st.spinner("Parsing activity data..."):
        try:
            # Prepare temp file
            extension = ".fit" if ".fit" in file_rel_path.lower() else ".tcx"
            with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp:
                if file_path.endswith(".gz"):
                    with gzip.open(file_path, "rb") as f:
                        content = f.read()
                        tmp.write(content)
                else:
                    with open(file_path, "rb") as f:
                        content = f.read()
                        tmp.write(content)
                tmp_path = tmp.name

            # Parse
            timestamps, hrs, alts, dists, parsing_error = [], [], [], [], None

            if ".fit" in extension:
                timestamps, hrs, alts, dists, parsing_error = _parse_fit(content)
            else:
                timestamps, hrs, alts, dists, parsing_error = _parse_tcx(tmp_path)

            if os.path.exists(tmp_path):
                os.remove(tmp_path)

            if parsing_error:
                st.warning(f"Sort parsing errors occurred: {parsing_error}")

            track_df = _create_track_df(timestamps, hrs, alts, dists)

            if track_df.empty:
                st.warning("No valid data points after parsing.")
                return

            track_df = _calculate_metrics(track_df)

            # Display Top Stats
            c1, c2, c3 = st.columns(3)
            avg_hr = track_df["HR"].mean()
            max_hr = track_df["HR"].max()

            total_dist = track_df["Distance"].max()
            total_time = track_df["Elapsed Seconds"].max()
            avg_pace_dec = ((total_time / 60) / (total_dist / 1000)) if total_dist > 0 else 0

            c1.metric("Avg HR (Track)", f"{avg_hr:.0f} bpm" if pd.notna(avg_hr) else "N/A")
            c2.metric("Max HR (Track)", f"{max_hr:.0f} bpm" if pd.notna(max_hr) else "N/A")

            if avg_pace_dec > 0:
                pm = int(avg_pace_dec)
                ps = int((avg_pace_dec - pm) * 60)
                c3.metric("Avg Pace", f"{pm}:{ps:02d} /km")
            else:
                c3.metric("Avg Pace", "N/A")

            _render_plots(track_df, zones)

        except Exception as e:
            st.error(f"Error parsing file: {e}")
