"""Import activities from CSV into the database."""

import pandas as pd
from pathlib import Path
from db_manager import DatabaseManager


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
            # Map CSV columns to database schema
            activity_data = {
                "activity_id": (
                    int(row["Activity ID"]) if pd.notna(row.get("Activity ID")) else None
                ),
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
                    str(row["Activity Description"])
                    if pd.notna(row.get("Activity Description"))
                    else None
                ),
            }

            # Time metrics (convert to seconds if needed)
            if pd.notna(row.get("Elapsed Time")):
                activity_data["elapsed_time"] = int(row["Elapsed Time"])
            if pd.notna(row.get("Moving Time")):
                activity_data["moving_time"] = int(row["Moving Time"])

            # Distance (convert to meters if in km)
            if pd.notna(row.get("Distance")):
                # Assuming distance is in km in CSV
                activity_data["distance"] = float(row["Distance"]) * 1000

            # Speed metrics
            if pd.notna(row.get("Max Speed")):
                activity_data["max_speed"] = float(row["Max Speed"])
            if pd.notna(row.get("Average Speed")):
                activity_data["average_speed"] = float(row["Average Speed"])

            # Elevation metrics
            for field in ["Elevation Gain", "Elevation Loss", "Elevation Low", "Elevation High"]:
                db_field = field.lower().replace(" ", "_")
                if pd.notna(row.get(field)):
                    activity_data[db_field] = float(row[field])

            for field in ["Max Grade", "Average Grade"]:
                db_field = field.lower().replace(" ", "_")
                if pd.notna(row.get(field)):
                    activity_data[db_field] = float(row[field])

            # Heart rate metrics
            if pd.notna(row.get("Max Heart Rate")):
                activity_data["max_heart_rate"] = int(row["Max Heart Rate"])
            if pd.notna(row.get("Average Heart Rate")):
                activity_data["average_heart_rate"] = int(row["Average Heart Rate"])

            # Cadence metrics
            if pd.notna(row.get("Max Cadence")):
                activity_data["max_cadence"] = int(row["Max Cadence"])
            if pd.notna(row.get("Average Cadence")):
                activity_data["average_cadence"] = int(row["Average Cadence"])

            # Power metrics
            if pd.notna(row.get("Max Watts")):
                activity_data["max_watts"] = int(row["Max Watts"])
            if pd.notna(row.get("Average Watts")):
                activity_data["average_watts"] = int(row["Average Watts"])
            if pd.notna(row.get("Weighted Average Power")):
                activity_data["weighted_average_power"] = int(row["Weighted Average Power"])

            # Energy metrics
            if pd.notna(row.get("Calories")):
                activity_data["calories"] = int(row["Calories"])
            if pd.notna(row.get("Relative Effort")):
                activity_data["relative_effort"] = int(row["Relative Effort"])
            if pd.notna(row.get("Total Work")):
                activity_data["total_work"] = int(row["Total Work"])

            # Temperature metrics
            if pd.notna(row.get("Max Temperature")):
                activity_data["max_temperature"] = float(row["Max Temperature"])
            if pd.notna(row.get("Average Temperature")):
                activity_data["average_temperature"] = float(row["Average Temperature"])

            # Other fields
            if pd.notna(row.get("Athlete Weight")):
                activity_data["athlete_weight"] = float(row["Athlete Weight"])

            # Commute (convert to boolean)
            if pd.notna(row.get("Commute")):
                commute_val = str(row["Commute"]).lower()
                activity_data["commute"] = 1 if commute_val in ["true", "1", "yes"] else 0

            if pd.notna(row.get("Activity Gear")):
                activity_data["gear"] = str(row["Activity Gear"])

            if pd.notna(row.get("Filename")):
                activity_data["filename"] = str(row["Filename"])

            # Insert into database
            db.insert_activity(activity_data)
            imported_count += 1

            # Progress indicator
            if (idx + 1) % 100 == 0:
                print(f"  Imported {idx + 1}/{len(df)} activities...")

        except Exception as e:
            error_count += 1
            print(f"  ⚠️  Error importing activity {row.get('Activity ID', 'unknown')}: {e}")

    print(f"\n✅ Import complete!")
    print(f"  Successfully imported: {imported_count} activities")
    if error_count > 0:
        print(f"  Errors: {error_count} activities")

    # Print database stats
    stats = db.get_database_stats()
    print(f"\n📈 Database Statistics:")
    print(f"  Total activities: {stats['total_activities']}")
    if "date_range" in stats:
        print(f"  Date range: {stats['date_range']['start']} to {stats['date_range']['end']}")
    if "activity_types" in stats:
        print(f"  Activity types:")
        for activity_type, count in stats["activity_types"].items():
            print(f"    - {activity_type}: {count}")


if __name__ == "__main__":
    import_activities_from_csv()
