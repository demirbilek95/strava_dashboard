"""Import activities from CSV into the database."""

import pandas as pd
from pathlib import Path
from db_manager import DatabaseManager


def _extract_core_data(row):
    return {
        "activity_id": (int(row["Activity ID"]) if pd.notna(row.get("Activity ID")) else None),
        "activity_date": (
            row["Activity Date"].isoformat() if pd.notna(row.get("Activity Date")) else None
        ),
        "activity_name": (
            str(row["Activity Name"]) if pd.notna(row.get("Activity Name")) else None
        ),
        "activity_type": (
            str(row["Activity Type"]) if pd.notna(row.get("Activity Type")) else None
        ),
        "activity_description": (
            str(row["Activity Description"]) if pd.notna(row.get("Activity Description")) else None
        ),
    }


def _add_metrics(row, activity_data):
    # Time metrics
    if pd.notna(row.get("Elapsed Time")):
        activity_data["elapsed_time"] = int(row["Elapsed Time"])
    if pd.notna(row.get("Moving Time")):
        activity_data["moving_time"] = int(row["Moving Time"])

    # Distance
    if pd.notna(row.get("Distance")):
        activity_data["distance"] = float(row["Distance"]) * 1000

    # Speed
    if pd.notna(row.get("Max Speed")):
        activity_data["max_speed"] = float(row["Max Speed"])
    if pd.notna(row.get("Average Speed")):
        activity_data["average_speed"] = float(row["Average Speed"])

    # Elevation
    for field in ["Elevation Gain", "Elevation Loss", "Elevation Low", "Elevation High"]:
        db_field = field.lower().replace(" ", "_")
        if pd.notna(row.get(field)):
            activity_data[db_field] = float(row[field])

    for field in ["Max Grade", "Average Grade"]:
        db_field = field.lower().replace(" ", "_")
        if pd.notna(row.get(field)):
            activity_data[db_field] = float(row[field])

    # HR, Cadence, Power, Energy, Temp
    mappings = [
        ("Max Heart Rate", "max_heart_rate", int),
        ("Average Heart Rate", "average_heart_rate", int),
        ("Max Cadence", "max_cadence", int),
        ("Average Cadence", "average_cadence", int),
        ("Max Watts", "max_watts", int),
        ("Average Watts", "average_watts", int),
        ("Weighted Average Power", "weighted_average_power", int),
        ("Calories", "calories", int),
        ("Relative Effort", "relative_effort", int),
        ("Total Work", "total_work", int),
        ("Max Temperature", "max_temperature", float),
        ("Average Temperature", "average_temperature", float),
        ("Athlete Weight", "athlete_weight", float),
    ]

    for csv_field, db_field, cast_type in mappings:
        if pd.notna(row.get(csv_field)):
            activity_data[db_field] = cast_type(row[csv_field])


def _add_metadata(row, activity_data):
    if pd.notna(row.get("Commute")):
        commute_val = str(row["Commute"]).lower()
        activity_data["commute"] = 1 if commute_val in ["true", "1", "yes"] else 0

    if pd.notna(row.get("Activity Gear")):
        activity_data["gear"] = str(row["Activity Gear"])

    if pd.notna(row.get("Filename")):
        activity_data["filename"] = str(row["Filename"])


def _extract_activity_data(row):
    activity_data = _extract_core_data(row)
    _add_metrics(row, activity_data)
    _add_metadata(row, activity_data)
    return activity_data


def import_activities_from_csv(csv_path: str = None, db_path: str = None):
    """
    Import activities from activities.csv into the database.

    Args:
        csv_path: Path to activities.csv. If None, uses default location.
        db_path: Path to database file. If None, uses default location.
    """
    # Setup paths
    if csv_path is None:
        current_dir = Path(__file__).parent
        project_root = current_dir.parent.parent.parent
        csv_path = project_root / "data" / "activities.csv"

    csv_path = Path(csv_path)

    if not csv_path.exists():
        print(f"❌ CSV file not found: {csv_path}")
        return

    # Initialize database
    db = DatabaseManager(db_path)

    print(f"📊 Reading activities from {csv_path}...")
    df = pd.read_csv(csv_path)

    print(f"Found {len(df)} activities in CSV")

    # Convert date column to datetime
    df["Activity Date"] = pd.to_datetime(df["Activity Date"], format="mixed", errors="coerce")

    # Process each activity
    imported_count = 0
    error_count = 0

    for idx, row in df.iterrows():
        try:
            activity_data = _extract_activity_data(row)
            db.insert_activity(activity_data)
            imported_count += 1

            # Progress indicator
            if (idx + 1) % 100 == 0:
                print(f"  Imported {idx + 1}/{len(df)} activities...")

        except Exception as e:
            error_count += 1
            print(f"  ⚠️  Error importing activity {row.get('Activity ID', 'unknown')}: {e}")

    print("\n✅ Import complete!")
    print(f"  Successfully imported: {imported_count} activities")
    if error_count > 0:
        print(f"  Errors: {error_count} activities")

    # Print database stats
    stats = db.get_database_stats()
    print("\n📈 Database Statistics:")
    print(f"  Total activities: {stats['total_activities']}")
    if "date_range" in stats:
        print(f"  Date range: {stats['date_range']['start']} to {stats['date_range']['end']}")
    if "activity_types" in stats:
        print("  Activity types:")
        for activity_type, count in stats["activity_types"].items():
            print(f"    - {activity_type}: {count}")


if __name__ == "__main__":
    import_activities_from_csv()
