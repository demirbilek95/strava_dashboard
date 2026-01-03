import pandas as pd


def _create_track_df(timestamps, hrs, alts, dists, lats=None, lons=None):
    if not timestamps:
        return pd.DataFrame()

    min_len = len(timestamps)

    # helper to pad/trunc list
    def adjust(lst):
        if len(lst) < min_len:
            return lst + [None] * (min_len - len(lst))
        if len(lst) > min_len:
            return lst[:min_len]
        return lst

    hrs = adjust(hrs)
    alts = adjust(alts)
    dists = adjust(dists)

    track_df = pd.DataFrame(
        {
            "Time": pd.to_datetime(timestamps, errors="coerce"),
            "HR": hrs,
            "Altitude": alts,
            "Distance": dists,
            "latitude": lats if lats else [None] * min_len,
            "longitude": lons if lons else [None] * min_len,
        }
    )

    track_df["HR"] = pd.to_numeric(track_df["HR"], errors="coerce")
    track_df["Altitude"] = pd.to_numeric(track_df["Altitude"], errors="coerce")
    track_df["Distance"] = pd.to_numeric(track_df["Distance"], errors="coerce")

    # Fill gaps
    track_df["Distance"] = track_df["Distance"].ffill()
    track_df["Altitude"] = track_df["Altitude"].ffill()
    track_df["HR"] = track_df["HR"].ffill()

    track_df["HR"] = track_df["HR"].ffill()

    # Convert semicircles to degrees if needed for simple lat/lon columns
    def to_degrees(val):
        if pd.isna(val):
            return None
        # Heuristic: if value > 180, it's likely semicircles
        if abs(val) > 180:
            return val * (180.0 / 2**31)
        return val

    if "latitude" in track_df.columns:
        track_df["latitude"] = track_df["latitude"].apply(to_degrees)
    if "longitude" in track_df.columns:
        track_df["longitude"] = track_df["longitude"].apply(to_degrees)

    track_df = track_df.dropna(subset=["Time"])
    return track_df


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

        # Get data for this exact 1km segment
        if end_dist <= max_dist:
            # Full 1km split
            split_data = track_df[
                (track_df["Distance"] >= start_dist) & (track_df["Distance"] < end_dist)
            ].copy()

            if not split_data.empty:
                # Calculate actual distance covered
                actual_dist_m = split_data["Distance"].iloc[-1] - split_data["Distance"].iloc[0]
                actual_dist_km = actual_dist_m / 1000

                # Use elapsed time (to match device laps behavior)
                # Device laps use total_timer_time or total_elapsed_time, not moving time
                elapsed_time_s = (
                    split_data["Time"].iloc[-1] - split_data["Time"].iloc[0]
                ).total_seconds()

                # Pace calculation (same as laps: (time_seconds / distance_km) / 60 = min/km)
                pace = (elapsed_time_s / actual_dist_km) / 60 if actual_dist_km > 0 else 0
                avg_hr = split_data["HR"].mean()
                avg_cadence = (
                    split_data["cadence"].mean() if "cadence" in split_data.columns else None
                )

                splits.append(
                    {
                        "KM": current_km + 1,
                        "Distance": actual_dist_km,
                        "Pace": pace,
                        "Avg HR": avg_hr,
                        "Cadence": avg_cadence,
                    }
                )

        current_km += 1

    return pd.DataFrame(splits)
