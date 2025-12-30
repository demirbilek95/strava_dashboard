"""Import detailed activity streams from TCX and FIT files."""

import os
import gzip
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional
import pandas as pd

import tcxparser
import garmin_fit_sdk

from db_manager import DatabaseManager


def _parse_timestamp(ts_str: str) -> Optional[Any]:
    if not isinstance(ts_str, str):
        return None
    from datetime import datetime

    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _extract_tcx_record(  # pylint: disable=too-many-positional-arguments
    i,
    timestamps,
    start_dt,
    hr_values,
    altitude_values,
    distance_values,
    cadence_values,
    power_values,
    position_values,
):
    raw_ts = timestamps[i]
    timestamp = _parse_timestamp(raw_ts) if isinstance(raw_ts, str) else raw_ts

    if not timestamp:
        return None

    record = {
        "timestamp": timestamp.isoformat() if timestamp else None,
    }

    if start_dt and timestamp:
        try:
            record["elapsed_seconds"] = (timestamp - start_dt).total_seconds()
        except (ValueError, TypeError):
            pass

    def add_val(key, vals, cast_func):
        if i < len(vals) and vals[i] is not None:
            record[key] = cast_func(vals[i])

    add_val("heart_rate", hr_values, int)
    add_val("altitude", altitude_values, float)
    add_val("distance", distance_values, float)
    add_val("cadence", cadence_values, int)
    add_val("power", power_values, int)

    if i < len(position_values) and position_values[i] is not None:
        lat, lon = position_values[i]
        if lat is not None:
            record["latitude"] = float(lat)
        if lon is not None:
            record["longitude"] = float(lon)

    record["source_type"] = "TCX"
    return record


def parse_tcx_file(file_path: Path) -> Optional[List[Dict[str, Any]]]:
    """Parse a TCX file and extract stream data."""
    try:
        # Handle gzipped files
        if str(file_path).endswith(".gz"):
            with gzip.open(file_path, "rb") as f:
                content = f.read()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".tcx") as tmp:
                tmp.write(content)
                tmp_path = tmp.name
        else:
            tmp_path = str(file_path)

        tcx = tcxparser.TCXParser(tmp_path)
        timestamps = tcx.time_values()

        if not timestamps:
            return None

        # Get all available data arrays
        hr_values = tcx.hr_values() or []
        altitude_values = tcx.altitude_points() or []
        distance_values = tcx.distance_values() or []
        cadence_values = tcx.cadence_values() or []
        power_values = tcx.power_values() or []
        position_values = tcx.position_values() or []

        stream_records = []
        num_points = len(timestamps)
        start_time = timestamps[0]

        start_dt = _parse_timestamp(start_time) if isinstance(start_time, str) else start_time

        for i in range(num_points):
            record = _extract_tcx_record(
                i,
                timestamps,
                start_dt,
                hr_values,
                altitude_values,
                distance_values,
                cadence_values,
                power_values,
                position_values,
            )
            if record:
                stream_records.append(record)

        if str(file_path).endswith(".gz") and os.path.exists(tmp_path):
            os.remove(tmp_path)

        return stream_records

    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"  ⚠️  Error parsing TCX file {file_path.name}: {e}")
        return None


def _extract_fit_record(record, start_time):  # pylint: disable=too-many-branches
    stream_record = {}
    timestamp = record.get("timestamp")

    if timestamp:
        stream_record["timestamp"] = timestamp.isoformat()
        if start_time:
            stream_record["elapsed_seconds"] = (timestamp - start_time).total_seconds()

    if "heart_rate" in record and record["heart_rate"] is not None:
        stream_record["heart_rate"] = int(record["heart_rate"])

    # GPS coordinates
    semicircle_const = 180 / 2**31
    if "position_lat" in record and record["position_lat"] is not None:
        stream_record["latitude"] = record["position_lat"] * semicircle_const
    if "position_long" in record and record["position_long"] is not None:
        stream_record["longitude"] = record["position_long"] * semicircle_const

    # Altitude
    altitude = record.get("enhanced_altitude") or record.get("altitude")
    if altitude is not None:
        stream_record["altitude"] = float(altitude)
        if "enhanced_altitude" in record:
            stream_record["enhanced_altitude"] = float(record["enhanced_altitude"])

    # Distance
    if "distance" in record and record["distance"] is not None:
        stream_record["distance"] = float(record["distance"])

    # Speed
    speed = record.get("enhanced_speed") or record.get("speed")
    if speed is not None:
        stream_record["speed"] = float(speed)
        if "enhanced_speed" in record:
            stream_record["enhanced_speed"] = float(record["enhanced_speed"])

    # Other metrics
    for field, key, typ_func in [
        ("cadence", "cadence", int),
        ("power", "power", int),
        ("accumulated_power", "accumulated_power", int),
        ("temperature", "temperature", int),
    ]:
        if field in record and record[field] is not None:
            stream_record[key] = typ_func(record[field])

    if "step_length" in record and record["step_length"] is not None:
        stream_record["step_length"] = float(record["step_length"]) / 1000

    stream_record["source_type"] = "FIT"
    return stream_record


def parse_fit_file(file_path: Path) -> Optional[List[Dict[str, Any]]]:
    """Parse a FIT file and extract stream data."""
    try:
        if str(file_path).endswith(".gz"):
            with gzip.open(file_path, "rb") as f:
                content = f.read()
        else:
            with open(file_path, "rb") as f:
                content = f.read()

        stream = garmin_fit_sdk.Stream.from_byte_array(content)
        decoder = garmin_fit_sdk.Decoder(stream)
        messages, _ = decoder.read()

        if not messages or "record_mesgs" not in messages:
            return None

        records = messages["record_mesgs"]
        if not records:
            return None

        start_time = records[0].get("timestamp")
        stream_records = []

        for record in records:
            stream_record = _extract_fit_record(record, start_time)
            stream_records.append(stream_record)

        return stream_records

    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"  ⚠️  Error parsing FIT file {file_path.name}: {e}")
        return None


def calculate_pace(stream_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Calculate pace from speed or distance/time for stream records."""
    if not stream_records:
        return stream_records

    df = pd.DataFrame(stream_records)

    if "speed" in df.columns:
        df["pace"] = df["speed"].apply(
            lambda s: (1000 / s) / 60 if pd.notna(s) and s > 0.1 else None
        )
    elif "distance" in df.columns and "elapsed_seconds" in df.columns:
        df["dist_diff"] = df["distance"].diff()
        df["time_diff"] = df["elapsed_seconds"].diff()
        df["instant_speed"] = df["dist_diff"] / df["time_diff"]
        df["smooth_speed"] = df["instant_speed"].rolling(window=10, min_periods=1).mean()
        df["pace"] = df["smooth_speed"].apply(
            lambda s: (1000 / s) / 60 if pd.notna(s) and s > 0.1 else None
        )
        df = df.drop(columns=["dist_diff", "time_diff", "instant_speed", "smooth_speed"])

    return df.to_dict("records")


def _process_file(file_path, db, skip_existing):
    try:
        activity_id = int(file_path.stem.split(".")[0])

        if skip_existing and db.activity_has_streams(activity_id):
            return "skipped", 0

        if file_path.suffix in [".tcx", ".gz"] and "tcx" in file_path.name:
            stream_records = parse_tcx_file(file_path)
        else:
            stream_records = parse_fit_file(file_path)

        if not stream_records:
            return "error", 0

        stream_records = calculate_pace(stream_records)

        for record in stream_records:
            record["activity_id"] = activity_id

        batch_size = 1000
        for i in range(0, len(stream_records), batch_size):
            batch = stream_records[i : i + batch_size]
            db.insert_stream_batch(batch)

        return "imported", len(stream_records)

    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"  ⚠️  Error processing {file_path.name}: {e}")
        return "error", 0


def import_activity_streams(
    activities_dir: str = None, db_path: str = None, skip_existing: bool = True
):
    """Import activity stream data from TCX and FIT files."""
    if activities_dir is None:
        current_dir = Path(__file__).parent
        project_root = current_dir.parent.parent.parent
        activities_dir = project_root / "data" / "activities"

    activities_dir = Path(activities_dir)

    if not activities_dir.exists():
        print(f"❌ Activities directory not found: {activities_dir}")
        return

    db = DatabaseManager(db_path)

    tcx_files = list(activities_dir.glob("*.tcx")) + list(activities_dir.glob("*.tcx.gz"))
    fit_files = list(activities_dir.glob("*.fit")) + list(activities_dir.glob("*.fit.gz"))
    all_files = tcx_files + fit_files

    print(f"📁 Found {len(tcx_files)} TCX files and {len(fit_files)} FIT files")
    print(f"📊 Total files to process: {len(all_files)}")

    imported_count = 0
    skipped_count = 0
    error_count = 0
    total_records = 0

    for idx, file_path in enumerate(all_files):
        status, records_count = _process_file(file_path, db, skip_existing)

        if status == "imported":
            imported_count += 1
            total_records += records_count
        elif status == "skipped":
            skipped_count += 1
        elif status == "error":
            error_count += 1

        if (idx + 1) % 10 == 0:
            print(
                f"  Processed {idx + 1}/{len(all_files)} files... "
                f"(imported: {imported_count}, skipped: {skipped_count}, errors: {error_count})"
            )

    print("\n✅ Import complete!")
    print(f"  Successfully imported: {imported_count} activities ({total_records} records)")
    print(f"  Skipped (already imported): {skipped_count} activities")
    if error_count > 0:
        print(f"  Errors: {error_count} files")

    stats = db.get_database_stats()
    print("\n📈 Database Statistics:")
    print(f"  Total activities: {stats['total_activities']}")
    print(f"  Activities with streams: {stats['activities_with_streams']}")
    print(f"  Total stream records: {stats['total_stream_records']}")
    print(f"  Database size: {stats['database_size_mb']:.2f} MB")


if __name__ == "__main__":
    import_activity_streams()
