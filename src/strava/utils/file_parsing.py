import gzip
import os
import tempfile
import pandas as pd
import tcxparser
import garmin_fit_sdk
import streamlit as st
from strava.utils.activity_processing import _create_track_df, _calculate_metrics


def _get_project_root():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))


def _read_file_content(abs_path):
    if abs_path.endswith(".gz"):
        with gzip.open(abs_path, "rb") as f:
            return f.read()
    with open(abs_path, "rb") as f:
        return f.read()


def _parse_fit(file_content):
    timestamps = []
    hrs = []
    alts = []
    dists = []
    lats = []
    lons = []
    parsing_error = None

    try:
        stream = garmin_fit_sdk.Stream.from_byte_array(file_content)
        decoder = garmin_fit_sdk.Decoder(stream)
        messages, errors = decoder.read()

        if errors:
            parsing_error = str(errors)

        if "record_mesgs" in messages:
            for record in messages["record_mesgs"]:
                timestamps.append(record.get("timestamp"))
                hrs.append(record.get("heart_rate"))
                alt = (
                    record.get("enhanced_altitude")
                    if record.get("enhanced_altitude") is not None
                    else record.get("altitude")
                )
                alts.append(alt)
                dists.append(record.get("distance"))

                # GPS extraction (FIT uses semicircles)
                lat = record.get("position_lat")
                lon = record.get("position_long")
                lats.append(lat)
                lons.append(lon)
    except Exception as e:  # pylint: disable=broad-exception-caught
        parsing_error = str(e)

    return timestamps, hrs, alts, dists, lats, lons, parsing_error


def _parse_tcx(tmp_path):
    tcx = tcxparser.TCXParser(tmp_path)
    return (tcx.time_values(), tcx.hr_values(), tcx.altitude_points(), tcx.distance_values(), None)


def _parse_fit_messages(content):
    """Worker to parse fit messages to reduce complexity."""
    timestamps, hrs, alts, dists, cads = [], [], [], [], []
    lats, lons = [], []
    laps = []

    try:
        stream = garmin_fit_sdk.Stream.from_byte_array(content)
        decoder = garmin_fit_sdk.Decoder(stream)
        messages, _ = decoder.read()

        if "record_mesgs" in messages:
            for record in messages["record_mesgs"]:
                timestamps.append(record.get("timestamp"))
                hrs.append(record.get("heart_rate"))
                alt = record.get("enhanced_altitude") or record.get("altitude")
                alts.append(alt)
                dists.append(record.get("distance"))
                # FIT files store cadence for ONE leg only, double it to match Strava
                raw_cad = record.get("cadence")
                cads.append(raw_cad * 2 if raw_cad is not None else None)

                # GPS extraction
                lats.append(record.get("position_lat"))
                lons.append(record.get("position_long"))

        if "lap_mesgs" in messages:
            for i, lap in enumerate(messages["lap_mesgs"]):
                # Use elapsed time consistently (total_elapsed_time) to match splits
                raw_cadence = lap.get("avg_combined_cadence") or lap.get("avg_cadence")
                # Double cadence to match Strava (FIT stores one leg only)
                display_cadence = raw_cadence * 2 if raw_cadence is not None else None

                laps.append(
                    {
                        "Lap": i + 1,
                        "Distance": (lap.get("total_distance", 0) / 1000),
                        "Time": (
                            lap.get("total_elapsed_time")
                            or lap.get("total_timer_time")
                            or lap.get("total_moving_time")
                        ),
                        "Pace": 0,
                        "Avg HR": lap.get("avg_heart_rate"),
                        "Cadence": display_cadence,
                    }
                )
    except Exception as e:  # pylint: disable=broad-exception-caught
        st.error(f"FIT parsing error: {e}")

    return timestamps, hrs, alts, dists, cads, lats, lons, laps


def load_and_parse_file(file_path):
    project_root = _get_project_root()
    abs_path = os.path.join(project_root, "data", file_path)

    if not os.path.exists(abs_path):
        st.error(f"File not found: {abs_path}")
        return None, None

    try:
        extension = ".fit" if ".fit" in file_path.lower() else ".tcx"
        content = _read_file_content(abs_path)

        if ".fit" in extension:
            timestamps, hrs, alts, dists, cads, lats, lons, laps = _parse_fit_messages(content)
            if timestamps:
                track_df = _create_track_df(timestamps, hrs, alts, dists, lats, lons)
                if not track_df.empty and len(cads) == len(track_df):
                    track_df["cadence"] = cads
                    track_df["cadence"] = track_df["cadence"].ffill()
                return _calculate_metrics(track_df), pd.DataFrame(laps)

        # Fallback/TCX
        with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        if ".fit" in extension:
            timestamps, hrs, alts, dists, lats, lons, _ = _parse_fit(content)
        else:
            timestamps, hrs, alts, dists, _ = _parse_tcx(tmp_path)
            lats, lons = [], []  # TODO: Implement TCX GPS extraction if needed
            # Try to extract cadence from TCX if available
            cads = []

        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        track_df = _create_track_df(timestamps, hrs, alts, dists, lats, lons)
        if track_df is not None and not track_df.empty:
            if cads and len(cads) == len(track_df):
                track_df["cadence"] = cads
                track_df["cadence"] = track_df["cadence"].ffill()
        return (
            (_calculate_metrics(track_df), pd.DataFrame()) if track_df is not None else (None, None)
        )

    except Exception as e:  # pylint: disable=broad-exception-caught
        st.error(f"Error parsing file: {e}")
        return None, None
