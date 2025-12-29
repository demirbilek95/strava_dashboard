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


def parse_tcx_file(file_path: Path) -> Optional[List[Dict[str, Any]]]:
    """
    Parse a TCX file and extract stream data.

    Args:
        file_path: Path to TCX file (may be gzipped)

    Returns:
        List of stream records or None if parsing fails
    """
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

        # Parse TCX
        tcx = tcxparser.TCXParser(tmp_path)

        # Get time-series data
        timestamps = tcx.time_values()
        if not timestamps:
            return None

        # Get all available data arrays
        hr_values = tcx.hr_values() or []
        altitude_values = tcx.altitude_points() or []
        distance_values = tcx.distance_values() or []
        cadence_values = tcx.cadence_values() or []
        power_values = tcx.power_values() or []
        position_values = tcx.position_values() or []  # Returns list of (lat, lon) tuples

        # Build stream records
        stream_records = []
        num_points = len(timestamps)

        # Get start time for elapsed calculation
        start_time = timestamps[0]

        for i in range(num_points):
            timestamp = timestamps[i]

            # Handle both datetime objects and string timestamps
            if isinstance(timestamp, str):
                from datetime import datetime

                try:
                    timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                except:
                    continue  # Skip invalid timestamps

            if not timestamp:
                continue

            record = {
                "timestamp": timestamp.isoformat() if timestamp else None,
            }

            # Calculate elapsed seconds
            if start_time:
                if isinstance(start_time, str):
                    from datetime import datetime

                    try:
                        start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                    except:
                        pass

                if timestamp and start_time:
                    try:
                        record["elapsed_seconds"] = (timestamp - start_time).total_seconds()
                    except:
                        pass

            # Heart rate
            if i < len(hr_values) and hr_values[i] is not None:
                record["heart_rate"] = int(hr_values[i])

            # Altitude
            if i < len(altitude_values) and altitude_values[i] is not None:
                record["altitude"] = float(altitude_values[i])

            # Distance
            if i < len(distance_values) and distance_values[i] is not None:
                record["distance"] = float(distance_values[i])

            # Cadence
            if i < len(cadence_values) and cadence_values[i] is not None:
                record["cadence"] = int(cadence_values[i])

            # Power
            if i < len(power_values) and power_values[i] is not None:
                record["power"] = int(power_values[i])

            # GPS position
            if i < len(position_values) and position_values[i] is not None:
                lat, lon = position_values[i]
                if lat is not None:
                    record["latitude"] = float(lat)
                if lon is not None:
                    record["longitude"] = float(lon)

            record["source_type"] = "TCX"
            stream_records.append(record)

        # Clean up temp file
        if str(file_path).endswith(".gz") and os.path.exists(tmp_path):
            os.remove(tmp_path)

        return stream_records

    except Exception as e:
        print(f"  ⚠️  Error parsing TCX file {file_path.name}: {e}")
        return None


def parse_fit_file(file_path: Path) -> Optional[List[Dict[str, Any]]]:
    """
    Parse a FIT file and extract stream data.

    Args:
        file_path: Path to FIT file (may be gzipped)

    Returns:
        List of stream records or None if parsing fails
    """
    try:
        # Read file content
        if str(file_path).endswith(".gz"):
            with gzip.open(file_path, "rb") as f:
                content = f.read()
        else:
            with open(file_path, "rb") as f:
                content = f.read()

        # Parse FIT using Garmin SDK
        stream = garmin_fit_sdk.Stream.from_byte_array(content)
        decoder = garmin_fit_sdk.Decoder(stream)
        messages, errors = decoder.read()

        if not messages or "record_mesgs" not in messages:
            return None

        records = messages["record_mesgs"]
        if not records:
            return None

        # Get start time for elapsed seconds calculation
        start_time = records[0].get("timestamp")

        # Convert FIT records to stream format
        stream_records = []

        for record in records:
            stream_record = {}

            # Timestamp
            timestamp = record.get("timestamp")
            if timestamp:
                stream_record["timestamp"] = timestamp.isoformat()
                if start_time:
                    stream_record["elapsed_seconds"] = (timestamp - start_time).total_seconds()

            # Heart rate
            if "heart_rate" in record and record["heart_rate"] is not None:
                stream_record["heart_rate"] = int(record["heart_rate"])

            # GPS coordinates (stored as semicircles in FIT, need conversion)
            if "position_lat" in record and record["position_lat"] is not None:
                # Convert semicircles to degrees: degrees = semicircles * (180 / 2^31)
                stream_record["latitude"] = record["position_lat"] * (180 / 2**31)

            if "position_long" in record and record["position_long"] is not None:
                stream_record["longitude"] = record["position_long"] * (180 / 2**31)

            # Altitude (prefer enhanced_altitude if available)
            altitude = record.get("enhanced_altitude") or record.get("altitude")
            if altitude is not None:
                stream_record["altitude"] = float(altitude)
                if "enhanced_altitude" in record:
                    stream_record["enhanced_altitude"] = float(record["enhanced_altitude"])

            # Distance
            if "distance" in record and record["distance"] is not None:
                stream_record["distance"] = float(record["distance"])

            # Speed (prefer enhanced_speed if available)
            speed = record.get("enhanced_speed") or record.get("speed")
            if speed is not None:
                stream_record["speed"] = float(speed)
                if "enhanced_speed" in record:
                    stream_record["enhanced_speed"] = float(record["enhanced_speed"])

            # Cadence
            if "cadence" in record and record["cadence"] is not None:
                stream_record["cadence"] = int(record["cadence"])

            # Power
            if "power" in record and record["power"] is not None:
                stream_record["power"] = int(record["power"])

            if "accumulated_power" in record and record["accumulated_power"] is not None:
                stream_record["accumulated_power"] = int(record["accumulated_power"])

            # Temperature
            if "temperature" in record and record["temperature"] is not None:
                stream_record["temperature"] = int(record["temperature"])

            # Step length
            if "step_length" in record and record["step_length"] is not None:
                stream_record["step_length"] = (
                    float(record["step_length"]) / 1000
                )  # Convert mm to m

            stream_record["source_type"] = "FIT"
            stream_records.append(stream_record)

        return stream_records

    except Exception as e:
        print(f"  ⚠️  Error parsing FIT file {file_path.name}: {e}")
        return None


def calculate_pace(stream_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Calculate pace from speed or distance/time for stream records.

    Args:
        stream_records: List of stream records

    Returns:
        Stream records with pace calculated
    """
    if not stream_records:
        return stream_records

    # Convert to DataFrame for easier calculation
    df = pd.DataFrame(stream_records)

    # Method 1: Calculate from speed if available
    if "speed" in df.columns:
        # Pace (min/km) = (1000 / speed_m/s) / 60
        df["pace"] = df["speed"].apply(
            lambda s: (1000 / s) / 60 if pd.notna(s) and s > 0.1 else None
        )

    # Method 2: Calculate from distance and time diff if speed not available
    elif "distance" in df.columns and "elapsed_seconds" in df.columns:
        df["dist_diff"] = df["distance"].diff()
        df["time_diff"] = df["elapsed_seconds"].diff()
        df["instant_speed"] = df["dist_diff"] / df["time_diff"]
        # Smooth speed with rolling average
        df["smooth_speed"] = df["instant_speed"].rolling(window=10, min_periods=1).mean()
        df["pace"] = df["smooth_speed"].apply(
            lambda s: (1000 / s) / 60 if pd.notna(s) and s > 0.1 else None
        )
        # Drop temporary columns
        df = df.drop(columns=["dist_diff", "time_diff", "instant_speed", "smooth_speed"])

    # Convert back to list of dicts
    return df.to_dict("records")


def import_activity_streams(
    activities_dir: str = None, db_path: str = None, skip_existing: bool = True
):
    """
    Import activity stream data from TCX and FIT files.

    Args:
        activities_dir: Directory containing activity files
        db_path: Path to database file
        skip_existing: If True, skip activities that already have stream data
    """
    # Setup paths
    if activities_dir is None:
        current_dir = Path(__file__).parent
        project_root = current_dir.parent.parent.parent
        activities_dir = project_root / "data" / "activities"

    activities_dir = Path(activities_dir)

    if not activities_dir.exists():
        print(f"❌ Activities directory not found: {activities_dir}")
        return

    # Initialize database
    db = DatabaseManager(db_path)

    # Get all TCX and FIT files
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
        try:
            # Extract activity ID from filename
            activity_id = int(file_path.stem.split(".")[0])

            # Skip if already imported
            if skip_existing and db.activity_has_streams(activity_id):
                skipped_count += 1
                continue

            # Parse file
            if file_path.suffix in [".tcx", ".gz"] and "tcx" in file_path.name:
                stream_records = parse_tcx_file(file_path)
            else:
                stream_records = parse_fit_file(file_path)

            if not stream_records:
                error_count += 1
                continue

            # Calculate pace
            stream_records = calculate_pace(stream_records)

            # Add activity_id to each record
            for record in stream_records:
                record["activity_id"] = activity_id

            # Insert in batches of 1000
            batch_size = 1000
            for i in range(0, len(stream_records), batch_size):
                batch = stream_records[i : i + batch_size]
                db.insert_stream_batch(batch)

            imported_count += 1
            total_records += len(stream_records)

            # Progress indicator
            if (idx + 1) % 10 == 0:
                print(
                    f"  Processed {idx + 1}/{len(all_files)} files... (imported: {imported_count}, skipped: {skipped_count}, errors: {error_count})"
                )

        except Exception as e:
            error_count += 1
            print(f"  ⚠️  Error processing {file_path.name}: {e}")

    print(f"\n✅ Import complete!")
    print(f"  Successfully imported: {imported_count} activities ({total_records} records)")
    print(f"  Skipped (already imported): {skipped_count} activities")
    if error_count > 0:
        print(f"  Errors: {error_count} files")

    # Print database stats
    stats = db.get_database_stats()
    print(f"\n📈 Database Statistics:")
    print(f"  Total activities: {stats['total_activities']}")
    print(f"  Activities with streams: {stats['activities_with_streams']}")
    print(f"  Total stream records: {stats['total_stream_records']}")
    print(f"  Database size: {stats['database_size_mb']:.2f} MB")


if __name__ == "__main__":
    import_activity_streams()
