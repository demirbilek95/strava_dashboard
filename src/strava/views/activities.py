import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import timedelta


def page_activity_run_details(df, zones):
    st.header("Activity Run Details")

    # Unpack Zones
    z1_limit, z2_limit, z3_limit, z4_limit = zones

    # -- Filter Logic --
    # Filter for Non-Commute AND Run activities
    # Use robust check for 'activity_type'
    if "activity_type" in df.columns:
        df_run = df[(df["commute"] == False) & (df["activity_type"] == "Run")].copy()
    else:
        df_run = df[df["commute"] == False].copy()  # Fallback

    if df_run.empty:
        st.warning("No running activities found.")
        return

    # -- Sidebar Controls --
    st.sidebar.markdown("### Analysis Options")

    # Date Range Filter
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

    # -- Metrics (Pace, HR, Distance) --
    # Calculate key metrics
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

    # Pace Stats (Calculate from Distance and Time sums for Average, Median from rows)
    # Average Pace = Total Time / Total Distance
    total_moving_time = filtered_df["moving_time"].sum()
    if total_distance > 0:
        avg_pace_decimal = (total_moving_time / 60) / total_distance
        # Convert to min:sec
        avg_pace_min = int(avg_pace_decimal)
        avg_pace_sec = int((avg_pace_decimal - avg_pace_min) * 60)
        avg_pace_str = f"{avg_pace_min}:{avg_pace_sec:02d} /km"
    else:
        avg_pace_str = "N/A"

    # Median and Fastest Pace from individual activities
    if "pace_decimal" in filtered_df.columns:
        valid_paces = filtered_df[filtered_df["distance"] > 0]["pace_decimal"].dropna()
        if not valid_paces.empty:
            median_pace_dec = valid_paces.median()
            min_pace_dec = valid_paces.min()

            # Helper to format
            def fmt_pace(dec):
                m = int(dec)
                s = int((dec - m) * 60)
                return f"{m}:{s:02d} /km"

            median_pace_str = fmt_pace(median_pace_dec)
            fastest_pace_str = fmt_pace(min_pace_dec)
        else:
            median_pace_str = "N/A"
            fastest_pace_str = "N/A"
    else:
        median_pace_str = "N/A"
        fastest_pace_str = "N/A"

    # Display Metrics
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

    # -- Plots --

    # 1. Total Kilometer per Week Bar Plot
    st.subheader("Weekly Distance")
    if not filtered_df.empty:
        plot_df = filtered_df.copy()
        # Group by week (W-SUN ensures week ends on Sunday, so it starts on Monday)
        plot_df["Week"] = (
            plot_df["activity_date"].dt.to_period("W-SUN").apply(lambda r: r.start_time)
        )
        weekly_dist = plot_df.groupby("Week")["distance"].sum().reset_index()

        fig_dist = px.bar(
            weekly_dist,
            x="Week",
            y="distance",
            title="Total Kilometers per Week",
            labels={"distance": "Distance (km)", "Week": "Week Starting"},
        )
        st.plotly_chart(fig_dist, use_container_width=True)

    # 2. Scatter Plot (Pace vs HR)
    st.subheader("Pace vs Heart Rate")
    st.info("Scatter plot of individual activities.")

    if "pace_decimal" in filtered_df.columns and "average_heart_rate" in filtered_df.columns:
        scatter_plot_df = filtered_df.dropna(subset=["pace_decimal", "average_heart_rate"])

        if not scatter_plot_df.empty:

            # Prepare hover data
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
                range_y=[90, 210],  # Expanded range to show zones better
            )

            # Add Zone Rectangles
            # Zone 1: < z1_limit (Grey)
            fig_scatter.add_hrect(
                y0=0,
                y1=z1_limit,
                line_width=0,
                fillcolor="gray",
                opacity=0.1,
                annotation_text="Z1",
                annotation_position="top left",
            )

            # Zone 2: z1_limit - z2_limit (Blue)
            fig_scatter.add_hrect(
                y0=z1_limit,
                y1=z2_limit,
                line_width=0,
                fillcolor="blue",
                opacity=0.1,
                annotation_text="Z2",
                annotation_position="top left",
            )

            # Zone 3: z2_limit - z3_limit (Green)
            fig_scatter.add_hrect(
                y0=z2_limit,
                y1=z3_limit,
                line_width=0,
                fillcolor="green",
                opacity=0.1,
                annotation_text="Z3",
                annotation_position="top left",
            )

            # Zone 4: z3_limit - z4_limit (Orange)
            fig_scatter.add_hrect(
                y0=z3_limit,
                y1=z4_limit,
                line_width=0,
                fillcolor="orange",
                opacity=0.1,
                annotation_text="Z4",
                annotation_position="top left",
            )

            # Zone 5: > z4_limit (Red) - go up to reasonable max, e.g. 220
            fig_scatter.add_hrect(
                y0=z4_limit,
                y1=220,
                line_width=0,
                fillcolor="red",
                opacity=0.1,
                annotation_text="Z5",
                annotation_position="top left",
            )

            st.plotly_chart(fig_scatter, use_container_width=True)

    # 3. Zone Distribution Pie Chart
    st.subheader("Training Intensity Distribution")

    if "average_heart_rate" in filtered_df.columns and not filtered_df.empty:
        # Create a copy for manipulation
        zone_df = filtered_df.dropna(subset=["average_heart_rate"]).copy()

        # Define Zones
        def get_zone(hr):
            if hr <= z1_limit:
                return "Zone 1"
            elif hr <= z2_limit:
                return "Zone 2"
            elif hr <= z3_limit:
                return "Zone 3"
            elif hr <= z4_limit:
                return "Zone 4"
            else:
                return "Zone 5"

        zone_df["HR Zone"] = zone_df["average_heart_rate"].apply(get_zone)

        # Color map for consistency
        zone_colors = {
            "Zone 1": "gray",
            "Zone 2": "blue",
            "Zone 3": "green",
            "Zone 4": "orange",
            "Zone 5": "red",
        }

        # Toggle for Metric
        metric_choice = st.radio("Distribution Metric", ["Time", "Distance"], horizontal=True)

        if metric_choice == "Time":
            # Sum Moving Time (in minutes for display)
            zone_stats = zone_df.groupby("HR Zone")["moving_time"].sum().reset_index()
            zone_stats["Value"] = zone_stats["moving_time"] / 60  # Minutes
            title_text = "Time Spent in Zones (based on Activity Avg HR)"
        else:
            # Sum Distance
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
            st.info("No heart rate data available for the selected period.")
