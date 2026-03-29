from typing import List

import pandas as pd


def _calculate_metrics(track_df):
    if track_df.empty:
        return None

    # Elapsed Seconds
    track_df["Elapsed Seconds"] = (track_df["Time"] - track_df["Time"].iloc[0]).dt.total_seconds()

    # Smooth Altitude to reduce GPS jitter before grade calculation
    track_df["Altitude_Smooth"] = (
        track_df["Altitude"].rolling(window=15, min_periods=1, center=True).mean()
    )

    # Calculate differences
    track_df["Dist_Diff"] = track_df["Distance"].diff()
    track_df["Time_Diff"] = track_df["Elapsed Seconds"].diff()
    track_df["Alt_Diff"] = track_df["Altitude_Smooth"].diff()

    # Speed and Moving logic
    track_df["Speed_m_s"] = track_df["Dist_Diff"] / track_df["Time_Diff"]
    track_df["Is_Moving"] = track_df["Speed_m_s"] > 0.5
    track_df["Speed_Smooth"] = track_df["Speed_m_s"].rolling(window=10, min_periods=1).mean()

    # Grade calculation (Rise / Run)
    track_df["Grade"] = track_df["Alt_Diff"] / track_df["Dist_Diff"]
    track_df.loc[track_df["Dist_Diff"] < 1, "Grade"] = 0  # Avoid noise on small distances
    track_df["Grade"] = track_df["Grade"].clip(-0.4, 0.4).fillna(0)

    # GAP calculation (Refined factor)
    def get_gap_factor(grade):
        # Strava-like approximation:
        # Uphill (Grade > 0): Factor > 1
        # Downhill (Grade < 0): Factor < 1 (initially) then > 1 (very steep)
        if grade > 0:
            return 1 + (9.0 * grade)  # More aggressive factor (9.0)
        # Downhill is more complex, but a simple drop works for moderate slopes
        return 1 + (4.0 * grade)

    track_df["GAP_Factor"] = track_df["Grade"].apply(get_gap_factor)
    track_df["Speed_GAP"] = track_df["Speed_Smooth"] * track_df["GAP_Factor"]

    def get_pace(speed_ms):
        if pd.isna(speed_ms) or speed_ms < 0.1:
            return None
        return (1000 / speed_ms) / 60

    track_df["Pace_Decimal"] = track_df["Speed_Smooth"].apply(get_pace)
    track_df["GAP_Pace_Decimal"] = track_df["Speed_GAP"].apply(get_pace)

    # Elevation Gain (using smoothed altitude for consistency)
    track_df["Elev_Gain_Step"] = track_df["Alt_Diff"].apply(lambda x: x if x > 0 else 0)

    return track_df


def _calculate_splits(track_df):
    """Calculate exactly 1km splits with consistent data."""
    if track_df.empty:
        return pd.DataFrame()

    # Calculate splits at exact 1km intervals
    max_dist = track_df["Distance"].max()
    splits = []

    current_km = 0
    while current_km * 1000 < max_dist:
        start_dist = current_km * 1000
        end_dist = (current_km + 1) * 1000

        split_data = track_df[
            (track_df["Distance"] >= start_dist) & (track_df["Distance"] < end_dist)
        ].copy()

        if not split_data.empty:
            actual_dist_m = split_data["Distance"].iloc[-1] - split_data["Distance"].iloc[0]
            actual_dist_km = actual_dist_m / 1000

            # Use moving time to match Strava's pace calculation
            moving_time_s = split_data[split_data["Is_Moving"]]["Time_Diff"].sum()
            pace = (moving_time_s / actual_dist_km) / 60 if actual_dist_km > 0 else 0

            avg_hr = split_data["HR"].mean()
            avg_cadence = split_data["cadence"].mean() if "cadence" in split_data.columns else None

            valid_paces = (
                split_data["Pace_Decimal"][
                    (split_data["Pace_Decimal"] > 3) & (split_data["Pace_Decimal"] < 12)
                ]
                if "Pace_Decimal" in split_data.columns
                else pd.Series(dtype=float)
            )
            min_pace = float(valid_paces.min()) if not valid_paces.empty else None
            max_pace = float(valid_paces.max()) if not valid_paces.empty else None

            splits.append(
                {
                    "KM": current_km + 1,
                    "Distance": actual_dist_km,
                    "Pace": pace,
                    "Min_Pace": min_pace,
                    "Max_Pace": max_pace,
                    "Avg HR": avg_hr,
                    "Cadence": avg_cadence,
                }
            )

        current_km += 1

    return pd.DataFrame(splits)


def calculate_per_km_hr_data(activity_ids: List[int], filtered_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate average heart rate per kilometer for multiple activities.

    Args:
        activity_ids: List of activity IDs to process
        filtered_df: DataFrame with activity summary data

    Returns:
        DataFrame with columns: activity_id, activity_name, activity_date, km_segment,
                               avg_hr, avg_pace, distance_m, elapsed_time_s
    """
    # Import here to avoid circular imports
    from strava.data import get_activity_stream  # pylint: disable=import-outside-toplevel

    all_km_data = []

    for activity_id in activity_ids:
        # Get activity metadata
        activity_row = filtered_df[filtered_df["activity_id"] == int(activity_id)]
        if activity_row.empty:
            continue

        activity_name = activity_row.iloc[0].get("activity_name", f"Activity {activity_id}")
        activity_date = activity_row.iloc[0].get("activity_date")

        # Try to get stream data
        stream_df = get_activity_stream(activity_id)

        if stream_df.empty or "heart_rate" not in stream_df.columns:
            # Fallback: use overall activity average
            avg_hr = activity_row.iloc[0].get("average_heart_rate")
            pace = activity_row.iloc[0].get("pace_decimal")

            if pd.notna(avg_hr) and pd.notna(pace):
                all_km_data.append(
                    {
                        "activity_id": activity_id,
                        "activity_name": activity_name,
                        "activity_date": activity_date,
                        "km_segment": 1,
                        "avg_hr": avg_hr,
                        "avg_pace": pace,
                        "distance_m": activity_row.iloc[0].get("distance", 0) * 1000,
                        "elapsed_time_s": activity_row.iloc[0].get("moving_time", 0),
                    }
                )
            continue

        # Calculate per-kilometer segments
        max_dist = stream_df["distance"].max() if "distance" in stream_df.columns else 0

        if max_dist == 0:
            continue

        current_km = 0
        while current_km * 1000 < max_dist:
            start_dist = current_km * 1000
            end_dist = (current_km + 1) * 1000

            # Get data for this 1km segment
            if end_dist <= max_dist:
                segment_data = stream_df[
                    (stream_df["distance"] >= start_dist) & (stream_df["distance"] < end_dist)
                ].copy()

                if not segment_data.empty and "heart_rate" in segment_data.columns:
                    # Calculate metrics for this kilometer
                    avg_hr = segment_data["heart_rate"].dropna().mean()

                    # Calculate actual distance and time
                    actual_dist_m = (
                        segment_data["distance"].iloc[-1] - segment_data["distance"].iloc[0]
                    )

                    # Calculate elapsed time for this segment
                    if "timestamp" in segment_data.columns:
                        elapsed_time_s = (
                            segment_data["timestamp"].iloc[-1] - segment_data["timestamp"].iloc[0]
                        ).total_seconds()
                    elif "elapsed_seconds" in segment_data.columns:
                        elapsed_time_s = (
                            segment_data["elapsed_seconds"].iloc[-1]
                            - segment_data["elapsed_seconds"].iloc[0]
                        )
                    else:
                        elapsed_time_s = 0

                    # Calculate pace (min/km)
                    actual_dist_km = actual_dist_m / 1000
                    avg_pace = (
                        (elapsed_time_s / actual_dist_km) / 60 if actual_dist_km > 0 else None
                    )

                    if pd.notna(avg_hr) and pd.notna(avg_pace):
                        all_km_data.append(
                            {
                                "activity_id": activity_id,
                                "activity_name": activity_name,
                                "activity_date": activity_date,
                                "km_segment": current_km + 1,
                                "avg_hr": avg_hr,
                                "avg_pace": avg_pace,
                                "distance_m": actual_dist_m,
                                "elapsed_time_s": elapsed_time_s,
                            }
                        )

            current_km += 1

    return pd.DataFrame(all_km_data)


def fmt_pace(dec: float, suffix: str = "") -> str:
    """Format a decimal pace value to MM:SS string. Returns 'N/A' for invalid values."""
    if pd.isna(dec) or dec <= 0:
        return "N/A"
    m = int(dec)
    s = int((dec - m) * 60)
    return f"{m}:{s:02d}{suffix}"


def fmt_duration(seconds) -> str:
    """Format seconds to H:MM:SS or M:SS string. Returns 'N/A' for missing values."""
    if pd.isna(seconds) or seconds is None:
        return "N/A"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
