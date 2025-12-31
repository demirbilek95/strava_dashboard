from datetime import timedelta
import streamlit as st
import plotly.express as px


def _filter_and_setup(df):
    st.sidebar.markdown("### Analysis Options")

    if "activity_type" in df.columns:
        df_run = df[(~df["commute"]) & (df["activity_type"] == "Run")].copy()
    else:
        df_run = df[~df["commute"]].copy()

    if df_run.empty:
        st.warning("No running activities found.")
        return None

    min_date = df_run["activity_date"].min().date()
    max_date = df_run["activity_date"].max().date()
    default_start = max_date - timedelta(weeks=4)

    start_date = st.sidebar.date_input(
        "Start Date", value=default_start, min_value=min_date, max_value=max_date, key="det_start"
    )
    end_date = st.sidebar.date_input(
        "End Date", value=max_date, min_value=min_date, max_value=max_date, key="det_end"
    )

    mask = (df_run["activity_date"].dt.date >= start_date) & (
        df_run["activity_date"].dt.date <= end_date
    )
    filtered_df = df_run.loc[mask].copy()

    st.caption(f"Showing Run data from {start_date} to {end_date}")
    return filtered_df


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
    plot_df["Week"] = plot_df["activity_date"].dt.to_period("W-SUN").apply(lambda r: r.start_time)
    weekly_dist = plot_df.groupby("Week")["distance"].sum().reset_index()

    fig_dist = px.bar(
        weekly_dist,
        x="Week",
        y="distance",
        title="Total Kilometers per Week",
        labels={"distance": "Distance (km)", "Week": "Week Starting"},
    )
    st.plotly_chart(fig_dist, use_container_width=True)


def _plot_scatter(filtered_df, zones):
    z1, z2, z3, z4 = zones
    st.subheader("Pace vs Heart Rate")
    st.info("Scatter plot of individual activities.")

    if "pace_decimal" not in filtered_df.columns or "average_heart_rate" not in filtered_df.columns:
        return

    scatter_plot_df = filtered_df.dropna(subset=["pace_decimal", "average_heart_rate"])
    if scatter_plot_df.empty:
        return

    hover_cols = ["activity_date", "distance", "moving_time"]
    if "activity_name" in scatter_plot_df.columns:
        hover_cols.insert(0, "activity_name")

    fig_scatter = px.scatter(
        scatter_plot_df,
        x="pace_decimal",
        y="average_heart_rate",
        hover_data=hover_cols,
        title="Heart Rate vs Pace with Zones",
        labels={"pace_decimal": "Pace (min/km)", "average_heart_rate": "Avg HR (bpm)"},
        range_y=[90, 210],
    )

    colors = ["gray", "blue", "green", "orange", "red"]
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

    st.plotly_chart(fig_scatter, use_container_width=True)


def _plot_zone_distribution(filtered_df, zones):
    z1, z2, z3, z4 = zones
    st.subheader("Training Intensity Distribution")

    if "average_heart_rate" not in filtered_df.columns or filtered_df.empty:
        st.info("No heart rate data available for the selected period.")
        return

    zone_df = filtered_df.dropna(subset=["average_heart_rate"]).copy()

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

    zone_df["HR Zone"] = zone_df["average_heart_rate"].apply(get_zone)

    zone_colors = {
        "Zone 1": "gray",
        "Zone 2": "blue",
        "Zone 3": "green",
        "Zone 4": "orange",
        "Zone 5": "red",
    }

    metric_choice = st.radio("Distribution Metric", ["Time", "Distance"], horizontal=True)

    if metric_choice == "Time":
        zone_stats = zone_df.groupby("HR Zone")["moving_time"].sum().reset_index()
        zone_stats["Value"] = zone_stats["moving_time"] / 60
        title_text = "Time Spent in Zones (based on Activity Avg HR)"
    else:
        zone_stats = zone_df.groupby("HR Zone")["distance"].sum().reset_index()
        zone_stats["Value"] = zone_stats["distance"]
        title_text = "Distance Covered in Zones (based on Activity Avg HR)"

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
        st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.info("No data in zones")


def page_activity_run_details(df, zones):
    st.header("Activity Run Details")

    filtered_df = _filter_and_setup(df)
    if filtered_df is None:
        return

    metrics = _calculate_metrics(filtered_df)
    _display_metrics(metrics)

    _plot_distance(filtered_df)
    _plot_scatter(filtered_df, zones)
    _plot_zone_distribution(filtered_df, zones)
