import streamlit as st
import pandas as pd
import plotly.express as px
import os
import gzip
import tempfile
import tcxparser
import garmin_fit_sdk


def page_recent_activities(df, zones):
    st.header("Deep Dive Analysis")
    st.caption("Detailed analysis of individual activities using raw track data (TCX files).")

    # Unpack Zones
    z1, z2, z3, z4 = zones  # Unpack into variables expected by local logic

    # Filter for activities with TCX files
    if "filename" not in df.columns:
        st.error("Filename column missing in data.")
        return

    # Check for valid TCX or FIT files
    # We look for .tcx or .tcx.gz
    mask = df["filename"].str.contains(r"\.(?:tcx|fit)", case=False, na=False) & (
        df["activity_type"] == "Run"
    )
    available_activities = df[mask].copy()

    if available_activities.empty:
        st.warning("No activities with TCX/FIT data found.")
        return

    # Sort by date
    available_activities = available_activities.sort_values(by="activity_date", ascending=False)

    # Selection
    # Format: "YYYY-MM-DD - Name (Type)"
    options = available_activities.apply(
        lambda x: f"{x['activity_date'].date()} - {x['activity_name'] if 'activity_name' in x else 'Unknown'} ({x['activity_type']})",
        axis=1,
    ).tolist()

    # Store ID map
    # Create a mapping from "Option String" -> "Row Index" or "Activity ID"
    # But since options might not be unique (rare), we better zip them.
    # Simple approach: Index match

    selected_option = st.selectbox("Select Activity", options)

    if selected_option:
        # Find the row
        idx = options.index(selected_option)
        selected_row = available_activities.iloc[idx]

        # Details
        st.subheader(
            f"{selected_row['activity_name'] if 'activity_name' in selected_row else 'Unknown'} - {selected_row['activity_date'].date()}"
        )
        if "activity_description" in selected_row and pd.notna(
            selected_row["activity_description"]
        ):
            st.markdown(f"*{selected_row['activity_description']}*")

        # Load File
        file_rel_path = selected_row["filename"]
        # Construct absolute path
        # This file is in src/strava/pages/deep_dive.py
        current_dir = os.path.dirname(os.path.abspath(__file__))  # src/strava/pages
        # Go up 3 levels: pages -> strava -> src -> root
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
        file_path = os.path.join(project_root, "data", file_rel_path)

        if not os.path.exists(file_path):
            st.error(f"File not found: {file_path}")
            return

        # Parse
        with st.spinner("Parsing activity data..."):
            try:
                # Decompress/Copy to temporary file
                # We normalize to a temp file so both parsers can just read a path
                extension = ".fit" if ".fit" in file_rel_path.lower() else ".tcx"

                with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp:
                    if file_path.endswith(".gz"):
                        with gzip.open(file_path, "rb") as f:
                            file_content = f.read()
                            tmp.write(file_content)
                    else:
                        with open(file_path, "rb") as f:
                            file_content = f.read()
                            tmp.write(file_content)
                    tmp_path = tmp.name

                timestamps = []
                hrs = []
                alts = []
                dists = []
                parsing_error = None

                if ".fit" in file_rel_path.lower():
                    # Parse FIT using the robust Garmin SDK
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
                                # Garmin SDK often has enhanced_altitude or altitude
                                alt = (
                                    record.get("enhanced_altitude")
                                    if record.get("enhanced_altitude") is not None
                                    else record.get("altitude")
                                )
                                alts.append(alt)
                                dists.append(record.get("distance"))
                    except Exception as e:
                        st.error(f"Failed to parse FIT file: {e}")
                        parsing_error = str(e)

                else:
                    # Parse TCX
                    tcx = tcxparser.TCXParser(tmp_path)
                    timestamps = tcx.time_values()
                    hrs = tcx.hr_values()
                    alts = tcx.altitude_points()
                    dists = tcx.distance_values()

                # Clean up temp
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

                if parsing_error:
                    st.warning(
                        f"Note: Some records in this FIT file couldn't be parsed due to format errors ({parsing_error}). Showing partial data."
                    )

                if not timestamps:
                    st.warning("No track points found in this file.")
                    return

                # Create DataFrame
                # Handle length mismatches and padding
                min_len = len(timestamps)
                # If HR is missing/empty, fill with None
                if len(hrs) < min_len:
                    hrs = hrs + [None] * (min_len - len(hrs))
                elif len(hrs) > min_len:
                    hrs = hrs[:min_len]

                if len(alts) < min_len:
                    alts = alts + [None] * (min_len - len(alts))
                elif len(alts) > min_len:
                    alts = alts[:min_len]

                if len(dists) < min_len:
                    dists = dists + [None] * (min_len - len(dists))
                elif len(dists) > min_len:
                    dists = dists[:min_len]

                # Build DF
                track_df = pd.DataFrame(
                    {
                        "Time": pd.to_datetime(timestamps, errors="coerce"),
                        "HR": hrs,
                        "Altitude": alts,
                        "Distance": dists,
                    }
                )

                # Coerce numeric
                track_df["HR"] = pd.to_numeric(track_df["HR"], errors="coerce")
                track_df["Altitude"] = pd.to_numeric(track_df["Altitude"], errors="coerce")
                track_df["Distance"] = pd.to_numeric(track_df["Distance"], errors="coerce")

                # DATA QUALITY: Forward fill distance and altitude
                # Often FIT records only contain HR, but we need the last known distance/altitude for pace
                track_df["Distance"] = track_df["Distance"].ffill()
                track_df["Altitude"] = track_df["Altitude"].ffill()
                track_df["HR"] = track_df["HR"].ffill()  # Also fill HR if there are tiny gaps

                # Drop rows where Time is NaT
                track_df = track_df.dropna(subset=["Time"])

                if track_df.empty:
                    st.warning("No valid data points after parsing.")
                    return

                # Calculate elapsed time in seconds
                track_df["Elapsed Seconds"] = (
                    track_df["Time"] - track_df["Time"].iloc[0]
                ).dt.total_seconds()

                # Calculate Pace (Instantaneous)
                # Speed = dDistance / dTime
                # We use a rolling window to smooth it, otherwise gps noise makes it jumpy
                track_df["Dist_Diff"] = track_df["Distance"].diff()
                track_df["Time_Diff"] = track_df["Elapsed Seconds"].diff()

                # Avoid div by zero
                track_df["Speed_m_s"] = track_df["Dist_Diff"] / track_df["Time_Diff"]

                # Smooth Speed (e.g. 10s rolling average)
                # Assuming ~1s sampling, 10 samples
                track_df["Speed_Smooth"] = (
                    track_df["Speed_m_s"].rolling(window=10, min_periods=1).mean()
                )

                # Convert to Pace (min/km)
                def get_pace(speed_ms):
                    if pd.isna(speed_ms):
                        return None
                    if speed_ms > 0.1:  # Threshold for moving
                        pace_min_km = (1000 / speed_ms) / 60
                        return pace_min_km
                    return None

                track_df["Pace_Decimal"] = track_df["Speed_Smooth"].apply(get_pace)

                # Metrics for this activity
                avg_hr_track = track_df["HR"].mean()
                max_hr_track = track_df["HR"].max()

                # Avg Pace (Harmonic mean of speed is better, or just Total Time / Total Dist)
                total_dist = track_df["Distance"].max()
                total_time = track_df["Elapsed Seconds"].max()
                if not pd.isna(total_dist) and total_dist > 0:
                    avg_pace_track_dec = (total_time / 60) / (total_dist / 1000)
                else:
                    avg_pace_track_dec = 0

                # Display Metrics
                c1, c2, c3 = st.columns(3)
                c1.metric(
                    "Avg HR (Track)",
                    f"{avg_hr_track:.0f} bpm" if not pd.isna(avg_hr_track) else "N/A",
                )
                c2.metric(
                    "Max HR (Track)",
                    f"{max_hr_track:.0f} bpm" if not pd.isna(max_hr_track) else "N/A",
                )

                # Format Avg Pace
                if avg_pace_track_dec > 0:
                    pm = int(avg_pace_track_dec)
                    ps = int((avg_pace_track_dec - pm) * 60)
                    c3.metric("Avg Pace", f"{pm}:{ps:02d} /km")
                else:
                    c3.metric("Avg Pace", "N/A")

                # Viz 1: Heart Rate over Time
                st.subheader("Heart Rate & Pace Analysis")

                fig_hr = px.line(track_df, x="Elapsed Seconds", y="HR", title="Heart Rate Profile")

                # Add Zone Backgrounds
                # Zone 1 (Gray)
                fig_hr.add_hrect(
                    y0=0,
                    y1=z1,
                    line_width=0,
                    fillcolor="gray",
                    opacity=0.1,
                    annotation_text="Z1",
                    annotation_position="top left",
                )
                # Zone 2 (Blue)
                fig_hr.add_hrect(
                    y0=z1,
                    y1=z2,
                    line_width=0,
                    fillcolor="blue",
                    opacity=0.1,
                    annotation_text="Z2",
                    annotation_position="top left",
                )
                # Zone 3 (Green)
                fig_hr.add_hrect(
                    y0=z2,
                    y1=z3,
                    line_width=0,
                    fillcolor="green",
                    opacity=0.1,
                    annotation_text="Z3",
                    annotation_position="top left",
                )
                # Zone 4 (Orange)
                fig_hr.add_hrect(
                    y0=z3,
                    y1=z4,
                    line_width=0,
                    fillcolor="orange",
                    opacity=0.1,
                    annotation_text="Z4",
                    annotation_position="top left",
                )
                # Zone 5 (Red)
                fig_hr.add_hrect(
                    y0=z4,
                    y1=240,
                    line_width=0,
                    fillcolor="red",
                    opacity=0.1,
                    annotation_text="Z5",
                    annotation_position="top left",
                )

                st.plotly_chart(fig_hr, use_container_width=True)

                # Viz 2: Pace over Time
                # Filter out crazy outliers for pace plot (e.g. > 20 min/km or < 2 min/km)
                pace_filtered = track_df[
                    (track_df["Pace_Decimal"] < 15) & (track_df["Pace_Decimal"] > 2)
                ].copy()
                if not pace_filtered.empty:
                    fig_pace = px.line(
                        pace_filtered,
                        x="Elapsed Seconds",
                        y="Pace_Decimal",
                        title="Pace Profile (Smoothed)",
                    )
                    fig_pace.update_yaxes(autorange="reversed")  # Standard pace chart convention
                    st.plotly_chart(fig_pace, use_container_width=True)

                # Viz 3: Zone Distribution for this activity
                st.subheader("Zone Distribution (This Activity)")
                if not pd.isna(avg_hr_track):
                    # Uses global zones passed into function

                    def get_zone_local(h):
                        if pd.isna(h):
                            return None
                        if h <= z1:
                            return "Z1"
                        elif h <= z2:
                            return "Z2"
                        elif h <= z3:
                            return "Z3"
                        elif h <= z4:
                            return "Z4"
                        else:
                            return "Z5"

                    track_df["Zone"] = track_df["HR"].apply(get_zone_local)

                    # Sum Time_Diff grouped by Zone
                    zone_dist = track_df.groupby("Zone")["Time_Diff"].sum().reset_index()
                    zone_dist["Minutes"] = zone_dist["Time_Diff"] / 60

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

            except Exception as e:
                st.error(f"Error parsing TCX file: {e}")
