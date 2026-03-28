import time
from typing import Optional

import pandas as pd
import streamlit as st

from strava.db.db_manager import DatabaseManager


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


def _display_performance_card(m, category, rank=None, is_latest=False):
    title = (
        f"#{rank}: {m['time_str']} - {m['name']} ({m['date_str']})"
        if rank
        else f"{m['name']} ({m['date_str']})"
    )
    if is_latest:
        title = f"Latest Race: {m['time_str']} - {m['name']} ({m['date_str']})"

    with st.expander(title, expanded=(rank == 1 or is_latest)):
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Time", m["time_str"])
        c2.metric("Pace", m["pace_str"])
        c3.metric("Avg HR", m["avg_hr_str"])
        c4.metric("Max HR", m["max_hr_str"])
        c5.metric("Zone", m["zone_str"])

        col_dist, col_btn = st.columns([4, 1])
        col_dist.caption(f"Exact Distance: {m['dist']:.2f} km")

        # Unique key using category and activity_id
        btn_key = f"btn_{category.lower().replace(' ', '_')}_{m['activity_id']}"
        if col_btn.button("🔍 Deep Dive", key=btn_key):
            st.session_state["selected_activity_id"] = m["activity_id"]
            st.session_state["requested_page"] = "Deep Dive"
            st.rerun()


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
        "activity_id": row["activity_id"],
        "time_str": time_str,
        "pace_str": pace_str,
        "avg_hr_str": avg_hr_str,
        "max_hr_str": max_hr_str,
        "zone_str": zone_str,
        "date_str": row["activity_date"].strftime("%Y-%m-%d"),
        "name": row.get("activity_name", "Run"),
        "dist": dist,
    }


_RACES_IMPORTED_KEY = "races_imported_at"


def _auto_fetch_races(database: DatabaseManager) -> None:
    """Fetch all-time race history once (persisted in DB), not every session."""
    from strava.db.api_importer import StravaImporter  # pylint: disable=import-outside-toplevel
    from strava.utils.strava_api import StravaAPI  # pylint: disable=import-outside-toplevel

    try:
        api = StravaAPI()
        importer = StravaImporter(database, api)
        progress_bar = st.progress(0)
        status_text = st.empty()

        def _cb(msg, pct):
            status_text.text(msg)
            progress_bar.progress(pct)

        count = importer.import_races(progress_callback=_cb)
        # Persist the flag regardless of count — even "no races" means we ran.
        database.set_setting(_RACES_IMPORTED_KEY, str(int(time.time())))
        if count:
            st.cache_data.clear()
            st.rerun()
        else:
            status_text.empty()
            progress_bar.empty()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        st.warning(f"Could not load race history: {exc}")


def page_races(
    df, zones, database: Optional[DatabaseManager] = None
):  # pylint: disable=too-many-branches
    st.header("Race Analysis")
    st.caption("Detailed view of your races and top performances.")

    if database is not None and database.get_setting(_RACES_IMPORTED_KEY) is None:
        _auto_fetch_races(database)

    if "activity_type" in df.columns:
        df_runs = df[df["activity_type"] == "Run"].copy()
    else:
        df_runs = df.copy()

    if df_runs.empty:
        st.warning("No running activities found.")
        return

    race_cats = _get_race_categories()

    # Check if workout_type is available
    has_workout_type = "workout_type" in df_runs.columns

    for cat_name, (min_d, max_d) in race_cats.items():
        st.subheader(f"📍 {cat_name} Analysis")

        cat_matches = df_runs[
            (df_runs["distance"] >= min_d) & (df_runs["distance"] <= max_d)
        ].copy()

        if cat_matches.empty:
            st.info(f"No activities found for {cat_name}.")
            continue

        time_col = "elapsed_time" if "elapsed_time" in cat_matches.columns else "moving_time"
        cat_matches = cat_matches.sort_values(by=time_col, ascending=True)

        # 1. Actual Races (workout_type = 1)
        actual_races = pd.DataFrame()
        if has_workout_type:
            actual_races = cat_matches[cat_matches["workout_type"] == 1].copy()

        if not actual_races.empty:
            st.markdown("#### 🏁 Actual Races")
            # Latest race
            latest_race = actual_races.sort_values(by="activity_date", ascending=False).iloc[0]
            m_latest = _calculate_metrics(latest_race, zones)
            _display_performance_card(m_latest, cat_name, is_latest=True)

            # Other races if any
            if len(actual_races) > 1:
                with st.expander("Other Races"):
                    other_races = actual_races.sort_values(
                        by="activity_date", ascending=False
                    ).iloc[1:]
                    for _, row in other_races.iterrows():
                        m = _calculate_metrics(row, zones)
                        st.write(f"**{m['date_str']}**: {m['time_str']} - {m['name']}")
                        btn_key = (
                            f"btn_other_{cat_name.lower().replace(' ', '_')}_{m['activity_id']}"
                        )
                        if st.button("Deep Dive", key=btn_key):
                            st.session_state["selected_activity_id"] = m["activity_id"]
                            st.session_state["requested_page"] = "Deep Dive"
                            st.rerun()
        else:
            # Fallback to Top Performances ONLY if no actual races exist
            st.markdown("#### 🏆 Top All-Time Performances")
            top_3 = cat_matches.head(3)
            for i, (_, row) in enumerate(top_3.iterrows()):
                m = _calculate_metrics(row, zones)
                # Use rank in the display card
                _display_performance_card(m, cat_name, rank=i + 1)

        st.divider()
