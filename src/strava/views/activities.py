from typing import Optional

import streamlit as st
import pandas as pd
import plotly.express as px
from strava.utils.activity_processing import calculate_per_km_hr_data
from strava.constants import ZONE_COLORS


def _filter_and_setup(df, start_date=None) -> Optional[pd.DataFrame]:
    if "activity_type" in df.columns:
        df_run = df[(~df["commute"]) & (df["activity_type"] == "Run")].copy()
    else:
        df_run = df[~df["commute"]].copy()

    if df_run.empty:
        st.warning("No running activities found.")
        return None

    max_date = df_run["activity_date"].max().date()
    effective_start = start_date if start_date is not None else df_run["activity_date"].min().date()
    mask = (df_run["activity_date"].dt.date >= effective_start) & (
        df_run["activity_date"].dt.date <= max_date
    )
    return df_run.loc[mask].copy()


def _calculate_metrics(filtered_df):
    total_distance = filtered_df["distance"].sum()

    # Heart Rate Stats
    if "average_heart_rate" in filtered_df.columns:
        avg_hr = filtered_df["average_heart_rate"].mean()
        valid_hr = filtered_df["average_heart_rate"].dropna()
        median_hr = valid_hr.median() if not valid_hr.empty else 0
        max_hr = (
            filtered_df["max_heart_rate"].max() if "max_heart_rate" in filtered_df.columns else 0
        )
    else:
        avg_hr, median_hr, max_hr = 0, 0, 0

    # Pace Stats
    total_moving_time = filtered_df["moving_time"].sum()
    if total_distance > 0:
        avg_pace_decimal = (total_moving_time / 60) / total_distance
        avg_pace_min = int(avg_pace_decimal)
        avg_pace_sec = int((avg_pace_decimal - avg_pace_min) * 60)
        avg_pace_str = f"{avg_pace_min}:{avg_pace_sec:02d} /km"
    else:
        avg_pace_str = "N/A"

    if "pace_decimal" in filtered_df.columns:
        valid_paces = filtered_df[filtered_df["distance"] > 0]["pace_decimal"].dropna()
        if not valid_paces.empty:

            def fmt_pace(dec):
                m = int(dec)
                s = int((dec - m) * 60)
                return f"{m}:{s:02d} /km"

            median_pace_str = fmt_pace(valid_paces.median())
            fastest_pace_str = fmt_pace(valid_paces.min())
        else:
            median_pace_str = "N/A"
            fastest_pace_str = "N/A"
    else:
        median_pace_str = "N/A"
        fastest_pace_str = "N/A"

    return (
        total_distance,
        avg_hr,
        median_hr,
        max_hr,
        avg_pace_str,
        median_pace_str,
        fastest_pace_str,
    )


def _display_metrics(metrics):
    total_distance, avg_hr, median_hr, max_hr, avg_pace_str, median_pace_str, fastest_pace_str = (
        metrics
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.subheader("Distance")
        st.metric("Total Distance", f"{total_distance:.1f} km")

    with col2:
        st.subheader("Pace")
        st.metric("Avg Pace", avg_pace_str)
        st.metric("Median Pace", median_pace_str)
        st.metric("Fastest Pace", fastest_pace_str)

    with col3:
        st.subheader("Heart Rate")
        st.metric("Avg HR", f"{avg_hr:.0f} bpm")
        st.metric("Median HR", f"{median_hr:.0f} bpm")
        st.metric("Max HR", f"{max_hr:.0f} bpm")


def _plot_distance(filtered_df):
    st.subheader("Weekly Distance")
    if filtered_df.empty:
        return

    plot_df = filtered_df.copy()
    plot_df["Week"] = (
        plot_df["activity_date"]
        .dt.tz_localize(None)
        .dt.to_period("W-SUN")
        .apply(lambda r: r.start_time)
    )
    weekly_dist = plot_df.groupby("Week")["distance"].sum().reset_index()

    # Generate complete date range to fill gaps
    if not weekly_dist.empty:
        min_week = weekly_dist["Week"].min()
        max_week = weekly_dist["Week"].max()

        # Create complete weekly range
        all_weeks = pd.date_range(start=min_week, end=max_week, freq="W-MON")
        complete_weeks_df = pd.DataFrame({"Week": all_weeks})

        # Merge with actual data and fill missing weeks with 0
        weekly_dist = complete_weeks_df.merge(weekly_dist, on="Week", how="left")
        weekly_dist["distance"] = weekly_dist["distance"].fillna(0)

    # Convert Week to string for consistent x-axis labeling
    weekly_dist["Week"] = weekly_dist["Week"].dt.strftime("%Y-%m-%d")

    fig_dist = px.bar(
        weekly_dist,
        x="Week",
        y="distance",
        title="Total Kilometers per Week",
        labels={"distance": "Distance (km)", "Week": "Week Starting"},
        text="distance",
        text_auto=".3s",
    )
    fig_dist.update_layout(xaxis={"type": "category"})
    st.plotly_chart(fig_dist)


def _plot_scatter(filtered_df, zones):
    z1, z2, z3, z4 = zones
    st.subheader("Pace vs Heart Rate")
    st.info("Scatter plot showing per-kilometer data points, colored by activity.")

    if "pace_decimal" not in filtered_df.columns or "average_heart_rate" not in filtered_df.columns:
        return

    activities_with_hr = filtered_df.dropna(subset=["average_heart_rate"])
    if activities_with_hr.empty:
        return

    # Get per-kilometer HR data

    activity_ids = activities_with_hr["activity_id"].tolist()
    km_data = calculate_per_km_hr_data(activity_ids, filtered_df)

    if km_data.empty:
        st.warning("No per-kilometer data available for the selected activities.")
        return

    # Format activity_date for display
    km_data["activity_date_str"] = km_data["activity_date"].dt.strftime("%Y-%m-%d")
    short_date = km_data["activity_date"].dt.strftime("%b %d")
    km_data["display_name"] = km_data["activity_name"] + " (" + short_date + ")"

    # Create hover template
    hover_cols = ["activity_name", "activity_date_str", "km_segment"]

    fig_scatter = px.scatter(
        km_data,
        x="avg_pace",
        y="avg_hr",
        color="display_name",
        hover_data=hover_cols,
        title="Heart Rate vs Pace (Per Kilometer) with Zones",
        labels={
            "avg_pace": "Pace (min/km)",
            "avg_hr": "HR (bpm)",
            "display_name": "Activity",
            "activity_name": "Activity Name",
            "activity_date_str": "Date",
            "km_segment": "Kilometer",
        },
        range_y=[90, 210],
    )

    # Add HR zone backgrounds
    colors = [
        ZONE_COLORS.get("Z1", "lightblue"),
        ZONE_COLORS.get("Z2", "green"),
        ZONE_COLORS.get("Z3", "yellow"),
        ZONE_COLORS.get("Z4", "orange"),
        ZONE_COLORS.get("Z5", "red"),
    ]
    limits = [0, z1, z2, z3, z4, 220]
    labels = ["Z1", "Z2", "Z3", "Z4", "Z5"]

    for i in range(5):
        fig_scatter.add_hrect(
            y0=limits[i],
            y1=limits[i + 1],
            line_width=0,
            fillcolor=colors[i],
            opacity=0.1,
            annotation_text=labels[i],
            annotation_position="top left",
        )

    st.plotly_chart(fig_scatter)


def _plot_zone_distribution(filtered_df, zones):
    z1, z2, z3, z4 = zones
    st.subheader("Training Intensity Distribution")

    if "average_heart_rate" not in filtered_df.columns or filtered_df.empty:
        st.info("No heart rate data available for the selected period.")
        return

    activities_with_hr = filtered_df.dropna(subset=["average_heart_rate"])
    if activities_with_hr.empty:
        st.info("No heart rate data available for the selected period.")
        return

    # Get per-kilometer HR data

    activity_ids = activities_with_hr["activity_id"].tolist()
    km_data = calculate_per_km_hr_data(activity_ids, filtered_df)

    if km_data.empty:
        st.warning("No per-kilometer data available for zone distribution.")
        return

    def get_zone(hr):
        if hr <= z1:
            return "Zone 1"
        if hr <= z2:
            return "Zone 2"
        if hr <= z3:
            return "Zone 3"
        if hr <= z4:
            return "Zone 4"
        return "Zone 5"

    km_data["HR Zone"] = km_data["avg_hr"].apply(get_zone)

    zone_colors = {
        "Zone 1": ZONE_COLORS.get("Z1", "lightblue"),
        "Zone 2": ZONE_COLORS.get("Z2", "green"),
        "Zone 3": ZONE_COLORS.get("Z3", "yellow"),
        "Zone 4": ZONE_COLORS.get("Z4", "orange"),
        "Zone 5": ZONE_COLORS.get("Z5", "red"),
    }

    metric_choice = st.radio("Distribution Metric", ["Time", "Distance"], horizontal=True)

    if metric_choice == "Time":
        zone_stats = km_data.groupby("HR Zone")["elapsed_time_s"].sum().reset_index()
        zone_stats["Value"] = zone_stats["elapsed_time_s"] / 60
        title_text = "Time Spent in Zones (Per-Kilometer HR Data)"
    else:
        zone_stats = km_data.groupby("HR Zone")["distance_m"].sum().reset_index()
        zone_stats["Value"] = zone_stats["distance_m"] / 1000  # Convert to km
        title_text = "Distance Covered in Zones (Per-Kilometer HR Data)"

    if not zone_stats.empty:
        fig_pie = px.pie(
            zone_stats,
            values="Value",
            names="HR Zone",
            title=title_text,
            color="HR Zone",
            color_discrete_map=zone_colors,
            category_orders={"HR Zone": ["Zone 1", "Zone 2", "Zone 3", "Zone 4", "Zone 5"]},
        )
        st.plotly_chart(fig_pie)
    else:
        st.info("No data in zones")


def page_activity_run_details(df, zones, start_date=None):
    st.header("Activity Run Details")

    filtered_df = _filter_and_setup(df, start_date)
    if filtered_df is None:
        return

    metrics = _calculate_metrics(filtered_df)
    _display_metrics(metrics)

    _plot_distance(filtered_df)
    _plot_scatter(filtered_df, zones)
    _plot_zone_distribution(filtered_df, zones)
