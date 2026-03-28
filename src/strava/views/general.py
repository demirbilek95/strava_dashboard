import streamlit as st
import pandas as pd
import plotly.express as px

from strava.constants import ACTIVITY_TYPE_COLORS, ZONE_COLORS, ZONE_ORDER, classify_zone


def _filter_by_date(df, start_date):
    if df.empty:
        st.warning("No data available")
        return df

    max_date = df["activity_date"].max().date()
    effective_start = start_date if start_date is not None else df["activity_date"].min().date()
    mask = (df["activity_date"].dt.date >= effective_start) & (
        df["activity_date"].dt.date <= max_date
    )
    return df.loc[mask].copy()


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
    plot_df["Week"] = (
        plot_df["activity_date"]
        .dt.tz_localize(None)
        .dt.to_period("W-SUN")
        .apply(lambda r: r.start_time)
    )

    plot_df["Duration Minutes"] = plot_df["moving_time"] / 60

    # Group by Week and Type
    weekly_type = plot_df.groupby(["Week", "activity_type"])["Duration Minutes"].sum().reset_index()

    # Convert Week to string for consistent x-axis labeling
    weekly_type["Week"] = weekly_type["Week"].dt.strftime("%Y-%m-%d")

    fig_weekly_stack = px.bar(
        weekly_type,
        x="Week",
        y="Duration Minutes",
        color="activity_type",
        color_discrete_map=ACTIVITY_TYPE_COLORS,
        title="Weekly Duration by Sport Type (Minutes)",
        labels={
            "Duration Minutes": "Duration (min)",
            "Week": "Week Starting",
            "activity_type": "Activity Type",
        },
    )
    fig_weekly_stack.update_layout(xaxis={"type": "date"})
    st.plotly_chart(fig_weekly_stack)


def _plot_distribution(filtered_df, zones):
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Activity Distribution")
        if not filtered_df.empty and "activity_type" in filtered_df.columns:
            activity_counts = filtered_df["activity_type"].value_counts().reset_index()
            activity_counts.columns = ["Activity Type", "Count"]

            fig_pie = px.pie(
                activity_counts,
                values="Count",
                names="Activity Type",
                title="Activities by Type",
                color="Activity Type",
                color_discrete_map=ACTIVITY_TYPE_COLORS,
            )
            st.plotly_chart(fig_pie)

    with c2:
        st.subheader("Intensity Distribution")
        if "average_heart_rate" in filtered_df.columns and not filtered_df.empty:
            zone_df = filtered_df.dropna(subset=["average_heart_rate"]).copy()
            zone_df["HR Zone"] = zone_df["average_heart_rate"].apply(
                lambda hr: classify_zone(hr, zones)
            )

            zone_stats = zone_df.groupby("HR Zone")["moving_time"].sum().reset_index()
            zone_stats["Minutes"] = zone_stats["moving_time"] / 60

            if not zone_stats.empty:
                fig_zone = px.pie(
                    zone_stats,
                    values="Minutes",
                    names="HR Zone",
                    title="Time in Zones (by Avg HR)",
                    color="HR Zone",
                    color_discrete_map=ZONE_COLORS,
                    category_orders={"HR Zone": ZONE_ORDER},
                )
                st.plotly_chart(fig_zone)
            else:
                st.info("No HR data")
        else:
            st.info("No HR data")


def _plot_relative_score(filtered_df):
    st.subheader("Relative Score Trend")
    if filtered_df.empty or "suffer_score" not in filtered_df.columns:
        return

    plot_df = filtered_df.dropna(subset=["suffer_score"]).copy()
    if plot_df.empty:
        st.info("No relative score data available.")
        return

    # Aggregate by week
    plot_df["Week"] = (
        plot_df["activity_date"]
        .dt.tz_localize(None)
        .dt.to_period("W-SUN")
        .apply(lambda r: r.start_time)
    )

    weekly_score = plot_df.groupby("Week")["suffer_score"].sum().reset_index()

    # Fill missing weeks with 0
    if not weekly_score.empty:
        min_week = weekly_score["Week"].min()
        max_week = weekly_score["Week"].max()
        all_weeks = pd.date_range(start=min_week, end=max_week, freq="W-MON")
        complete_weeks_df = pd.DataFrame({"Week": all_weeks})
        weekly_score = complete_weeks_df.merge(weekly_score, on="Week", how="left")
        weekly_score["suffer_score"] = weekly_score["suffer_score"].fillna(0)

    # Convert Week to string for consistent x-axis labeling
    weekly_score["Week"] = weekly_score["Week"].dt.strftime("%Y-%m-%d")

    fig = px.bar(
        weekly_score,
        x="Week",
        y="suffer_score",
        title="Weekly Total Relative Score (Training Load)",
        labels={"Week": "Week Starting", "suffer_score": "Total Relative Score"},
        text="suffer_score",
    )
    fig.update_layout(xaxis={"type": "category"})
    st.plotly_chart(fig)


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
        "suffer_score": "Score",
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
    if "suffer_score" in display_df.columns:
        available_cols.append("suffer_score")

    final_df = display_df[available_cols + available_cols_derived].copy()
    final_df = final_df.rename(columns=cols_map)

    desired_order = ["Name", "Type", "Date", "Distance (km)", "Duration", "Avg HR", "Score"]
    final_cols = [c for c in desired_order if c in final_df.columns]
    final_df = final_df[final_cols]

    st.dataframe(final_df, width="stretch", hide_index=True)


def page_general(df, zones, start_date=None):
    st.header("General Overview")

    filtered_df = _filter_by_date(df, start_date)

    _display_metrics(filtered_df)
    _plot_weekly_duration(filtered_df)
    _plot_distribution(filtered_df, zones)
    _plot_relative_score(filtered_df)
    _display_recent_activities(filtered_df)
