import streamlit as st
import pandas as pd
import plotly.express as px


def page_races(df, zones):
    st.header("Race Analysis")
    st.caption("Top performances for standard distances identified from your activities.")

    # Unpack Zones
    z1, z2, z3, z4 = zones

    # Filter for Runs
    # Rely on 'activity_type'
    if "activity_type" in df.columns:
        df_runs = df[df["activity_type"] == "Run"].copy()
    else:
        df_runs = df.copy()

    if df_runs.empty:
        st.warning("No running activities found.")
        return

    # Define Race Categories (Distance in km)
    # Allows for some GPS buffer
    race_cats = {
        "5k": (4.9, 5.15),
        "10k": (9.9, 10.3),
        "Half Marathon": (21.0, 21.5),
        "Marathon": (42.0, 43.0),
    }

    # Identify Races
    # We will look for runs matching these distances.
    # If a 'Workout Type' or 'Competition' flag existed we would use it, but absent that we use distance matching.

    # Container for results
    best_efforts = {}

    for cat_name, (min_d, max_d) in race_cats.items():
        # Filter by distance
        # Use 'distance' column (assumed km based on previous checks)
        cat_matches = df_runs[
            (df_runs["distance"] >= min_d) & (df_runs["distance"] <= max_d)
        ].copy()

        if not cat_matches.empty:
            # Sort by Elapsed Time (Races are judged on Elapsed Time)
            # If Elapsed Time is available, use it, otherwise Moving Time
            time_col = "elapsed_time" if "elapsed_time" in cat_matches.columns else "moving_time"

            # Sort ascending (fastest first)
            cat_matches = cat_matches.sort_values(by=time_col, ascending=True)

            # Take top 3
            top_3 = cat_matches.head(3)
            best_efforts[cat_name] = top_3

    # Display Results
    if not best_efforts:
        st.info("No activities found matching standard race distances (5k, 10k, HM, Marathon).")

    for cat, matches in best_efforts.items():
        st.subheader(f"🏆 {cat} Top Performances")

        # Display as a table with custom formatting or metrics
        # Let's iterate and show key stats

        for i, (idx, row) in enumerate(matches.iterrows()):
            rank = i + 1

            # Extract metrics
            date_str = row["activity_date"].strftime("%Y-%m-%d")
            name = row["activity_name"] if "activity_name" in row else "Run"

            # Time
            time_col = "elapsed_time" if "elapsed_time" in row else "moving_time"
            seconds = row[time_col]
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            time_str = f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"

            # Pace
            dist = row["distance"]
            if dist > 0:
                pace_dec = (seconds / 60) / dist  # min/km
                pm = int(pace_dec)
                ps = int((pace_dec - pm) * 60)
                pace_str = f"{pm}:{ps:02d} /km"
            else:
                pace_str = "N/A"

            # HR
            hr_val = (
                row["average_heart_rate"]
                if "average_heart_rate" in row and not pd.isna(row["average_heart_rate"])
                else None
            )
            avg_hr_str = "N/A"
            zone_str = "N/A"

            if hr_val:
                avg_hr_str = f"{int(hr_val)} bpm"
                # Calculate Zone
                if hr_val <= z1:
                    zone_str = "Z1"
                elif hr_val <= z2:
                    zone_str = "Z2"
                elif hr_val <= z3:
                    zone_str = "Z3"
                elif hr_val <= z4:
                    zone_str = "Z4"
                else:
                    zone_str = "Z5"

            max_hr = (
                row["max_heart_rate"]
                if "max_heart_rate" in row and not pd.isna(row["max_heart_rate"])
                else "N/A"
            )
            if max_hr != "N/A":
                max_hr = f"{int(max_hr)} bpm"

            # Display Row
            with st.expander(f"#{rank}: {time_str} - {name} ({date_str})", expanded=(i == 0)):
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Time", time_str)
                c2.metric("Pace", pace_str)
                c3.metric("Avg HR", avg_hr_str)
                c4.metric("Max HR", max_hr)
                c5.metric("Zone", zone_str)

                # Optional: Show distance exactly
                st.caption(f"Exact Distance: {dist:.2f} km")
