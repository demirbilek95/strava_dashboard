from datetime import timedelta
import streamlit as st
import pandas as pd
import plotly.express as px


def _filter_by_date(df):
    st.sidebar.markdown("### General Options")

    if df.empty:
        st.warning("No data available")
        return df

    min_date = df["activity_date"].min().date()
    max_date = df["activity_date"].max().date()
    default_start = max_date - timedelta(weeks=4)

    start_date = st.sidebar.date_input(
        "Start Date",
        value=default_start,
        min_value=min_date,
        max_value=max_date,
        key="gen_start",
    )
    end_date = st.sidebar.date_input(
        "End Date", value=max_date, min_value=min_date, max_value=max_date, key="gen_end"
    )

    mask = (df["activity_date"].dt.date >= start_date) & (df["activity_date"].dt.date <= end_date)
    filtered_df = df.loc[mask].copy()

    st.caption(f"Showing data from {start_date} to {end_date}")
    return filtered_df


def _display_metrics(filtered_df):
    total_activities = len(filtered_df)
    total_moving_time = (
        filtered_df["moving_time"].sum() if "moving_time" in filtered_df.columns else 0
    )
    total_distance = filtered_df["distance"].sum() if "distance" in filtered_df.columns else 0

    avg_hr = 0
    if "average_heart_rate" in filtered_df.columns:
        avg_hr = filtered_df["average_heart_rate"].mean()

    # Format Duration (Hours and Minutes)
    hours = int(total_moving_time // 3600)
    minutes = int((total_moving_time % 3600) // 60)
    duration_str = f"{hours}h {minutes}m"

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Activities", total_activities)
    col2.metric("Total Distance", f"{total_distance:.1f} km")
    col3.metric("Total Duration", duration_str)
    col4.metric("Avg HR", f"{avg_hr:.0f} bpm" if not pd.isna(avg_hr) else "N/A")


def _plot_weekly_duration(filtered_df):
    st.subheader("Weekly Duration by Sport Type")
    if filtered_df.empty or "activity_type" not in filtered_df.columns:
        return

    # Create a weekly grouper
    plot_df = filtered_df.copy()
    plot_df["Week"] = plot_df["activity_date"].dt.to_period("W-SUN").apply(lambda r: r.start_time)

    plot_df["Duration Minutes"] = plot_df["moving_time"] / 60

    # Group by Week and Type
    weekly_type = plot_df.groupby(["Week", "activity_type"])["Duration Minutes"].sum().reset_index()

    fig_weekly_stack = px.bar(
        weekly_type,
        x="Week",
        y="Duration Minutes",
        color="activity_type",
        title="Weekly Duration by Sport Type (Minutes)",
        labels={
            "Duration Minutes": "Duration (min)",
            "Week": "Week Starting",
            "activity_type": "Activity Type",
        },
    )
    st.plotly_chart(fig_weekly_stack, use_container_width=True)


def _plot_distribution(filtered_df, zones):
    z1_limit, z2_limit, z3_limit, z4_limit = zones
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Activity Distribution")
        if not filtered_df.empty and "activity_type" in filtered_df.columns:
            activity_counts = filtered_df["activity_type"].value_counts().reset_index()
            activity_counts.columns = ["Activity Type", "Count"]

            fig_pie = px.pie(
                activity_counts, values="Count", names="Activity Type", title="Activities by Type"
            )
            st.plotly_chart(fig_pie, use_container_width=True)

    with c2:
        st.subheader("Intensity Distribution")
        if "average_heart_rate" in filtered_df.columns and not filtered_df.empty:
            zone_df = filtered_df.dropna(subset=["average_heart_rate"]).copy()

            def get_zone(hr):
                if hr <= z1_limit:
                    return "Z1"
                if hr <= z2_limit:
                    return "Z2"
                if hr <= z3_limit:
                    return "Z3"
                if hr <= z4_limit:
                    return "Z4"
                return "Z5"

            zone_df["HR Zone"] = zone_df["average_heart_rate"].apply(get_zone)

            zone_colors = {"Z1": "gray", "Z2": "blue", "Z3": "green", "Z4": "orange", "Z5": "red"}

            zone_stats = zone_df.groupby("HR Zone")["moving_time"].sum().reset_index()
            zone_stats["Minutes"] = zone_stats["moving_time"] / 60

            if not zone_stats.empty:
                fig_zone = px.pie(
                    zone_stats,
                    values="Minutes",
                    names="HR Zone",
                    title="Time in Zones (by Avg HR)",
                    color="HR Zone",
                    color_discrete_map=zone_colors,
                    category_orders={"HR Zone": ["Z1", "Z2", "Z3", "Z4", "Z5"]},
                )
                st.plotly_chart(fig_zone, use_container_width=True)
            else:
                st.info("No HR data")
        else:
            st.info("No HR data")


def _display_recent_activities(filtered_df):
    st.subheader("Recent Activities")
    if filtered_df.empty:
        return

    display_df = filtered_df.copy()
    display_df = display_df.sort_values(by="activity_date", ascending=False)
    display_df["Date"] = display_df["activity_date"].dt.date

    if "moving_time" in display_df.columns:

        def fmt_duration(s):
            h = int(s // 3600)
            m = int((s % 3600) // 60)
            return f"{h}h {m}m"

        display_df["Duration"] = display_df["moving_time"].apply(fmt_duration)

    cols_map = {
        "activity_type": "Type",
        "distance": "Distance (km)",
        "average_heart_rate": "Avg HR",
    }

    # logic to robustly pick cols
    available_cols = []
    if "activity_name" in display_df.columns:
        available_cols.append("activity_name")
        cols_map["activity_name"] = "Name"
    if "activity_type" in display_df.columns:
        available_cols.append("activity_type")

    available_cols_derived = ["Date"]
    if "distance" in display_df.columns:
        available_cols.append("distance")
    available_cols_derived.append("Duration")
    if "average_heart_rate" in display_df.columns:
        available_cols.append("average_heart_rate")

    final_df = display_df[available_cols + available_cols_derived].copy()
    final_df = final_df.rename(columns=cols_map)

    desired_order = ["Name", "Type", "Date", "Distance (km)", "Duration", "Avg HR"]
    final_cols = [c for c in desired_order if c in final_df.columns]
    final_df = final_df[final_cols]

    st.dataframe(final_df, width="stretch", hide_index=True)


def page_general(df, zones):
    st.header("General Overview")

    filtered_df = _filter_by_date(df)

    _display_metrics(filtered_df)
    _plot_weekly_duration(filtered_df)
    _plot_distribution(filtered_df, zones)
    _display_recent_activities(filtered_df)
