import streamlit as st
import pandas as pd


def _get_race_categories():
    return {
        "5k": (4.9, 5.15),
        "10k": (9.9, 10.3),
        "Half Marathon": (21.0, 21.5),
        "Marathon": (42.0, 43.0),
    }


def _find_best_efforts(df_runs):
    race_cats = _get_race_categories()
    best_efforts = {}

    for cat_name, (min_d, max_d) in race_cats.items():
        cat_matches = df_runs[
            (df_runs["distance"] >= min_d) & (df_runs["distance"] <= max_d)
        ].copy()

        if not cat_matches.empty:
            time_col = "elapsed_time" if "elapsed_time" in cat_matches.columns else "moving_time"
            cat_matches = cat_matches.sort_values(by=time_col, ascending=True)
            best_efforts[cat_name] = cat_matches.head(3)

    return best_efforts


def _calculate_metrics(row, zones):
    z1, z2, z3, z4 = zones

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
        pace_dec = (seconds / 60) / dist
        pm = int(pace_dec)
        ps = int((pace_dec - pm) * 60)
        pace_str = f"{pm}:{ps:02d} /km"
    else:
        pace_str = "N/A"

    # HR
    hr_val = row.get("average_heart_rate")
    if pd.isna(hr_val):
        hr_val = None

    avg_hr_str = f"{int(hr_val)} bpm" if hr_val else "N/A"

    zone_str = "N/A"
    if hr_val:
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

    max_hr = row.get("max_heart_rate")
    max_hr_str = f"{int(max_hr)} bpm" if not pd.isna(max_hr) else "N/A"

    return {
        "time_str": time_str,
        "pace_str": pace_str,
        "avg_hr_str": avg_hr_str,
        "max_hr_str": max_hr_str,
        "zone_str": zone_str,
        "date_str": row["activity_date"].strftime("%Y-%m-%d"),
        "name": row.get("activity_name", "Run"),
        "dist": dist,
    }


def _display_race_category(cat, matches, zones):
    st.subheader(f"🏆 {cat} Top Performances")

    for i, (_, row) in enumerate(matches.iterrows()):
        m = _calculate_metrics(row, zones)
        rank = i + 1

        with st.expander(
            f"#{rank}: {m['time_str']} - {m['name']} ({m['date_str']})", expanded=(i == 0)
        ):
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Time", m["time_str"])
            c2.metric("Pace", m["pace_str"])
            c3.metric("Avg HR", m["avg_hr_str"])
            c4.metric("Max HR", m["max_hr_str"])
            c5.metric("Zone", m["zone_str"])
            st.caption(f"Exact Distance: {m['dist']:.2f} km")


def page_races(df, zones):
    st.header("Race Analysis")
    st.caption("Top performances for standard distances identified from your activities.")

    if "activity_type" in df.columns:
        df_runs = df[df["activity_type"] == "Run"].copy()
    else:
        df_runs = df.copy()

    if df_runs.empty:
        st.warning("No running activities found.")
        return

    best_efforts = _find_best_efforts(df_runs)

    if not best_efforts:
        st.info("No activities found matching standard race distances (5k, 10k, HM, Marathon).")
        return

    for cat, matches in best_efforts.items():
        _display_race_category(cat, matches, zones)
