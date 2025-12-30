#!/usr/bin/env python3
"""Master import script to initialize and populate the database."""

import sys

from db_manager import DatabaseManager  # pylint: disable=import-error
from import_activities import import_activities_from_csv  # pylint: disable=import-error
from import_streams import import_activity_streams  # pylint: disable=import-error


def import_all(db_path: str = None, skip_existing_streams: bool = True):
    """
    Run complete database import process.

    Args:
        db_path: Path to database file
        skip_existing_streams: If True, skip stream import for activities already imported
    """
    print("=" * 60)
    print("🏃 Strava Database Import")
    print("=" * 60)

    # Step 1: Create database tables
    print("\n📋 Step 1: Creating database schema...")
    db = DatabaseManager(db_path)
    db.create_tables()

    # Step 2: Import activities from CSV
    print("\n📋 Step 2: Importing activities from CSV...")
    import_activities_from_csv(db_path=db_path)

    # Step 3: Import activity streams from TCX/FIT files
    print("\n📋 Step 3: Importing activity streams from TCX/FIT files...")
    import_activity_streams(db_path=db_path, skip_existing=skip_existing_streams)

    # Final statistics
    print("\n" + "=" * 60)
    print("✅ Database import complete!")
    print("=" * 60)

    stats = db.get_database_stats()
    print("\n📊 Final Database Summary:")
    print(f"  Database location: {db.db_path}")
    print(f"  Database size: {stats['database_size_mb']:.2f} MB")
    print(f"  Total activities: {stats['total_activities']}")
    print(f"  Activities with detailed streams: {stats['activities_with_streams']}")
    print(f"  Total stream data points: {stats['total_stream_records']}")

    if "date_range" in stats:
        print("\n📅 Date Range:")
        print(f"  From: {stats['date_range']['start']}")
        print(f"  To: {stats['date_range']['end']}")

    if "activity_types" in stats:
        print("\n🏃 Activity Types:")
        for activity_type, count in stats["activity_types"].items():
            print(f"  {activity_type}: {count} activities")

    print("\n💡 Next Steps:")
    print("  1. Update your Streamlit app to use the database")
    print("  2. Run: poetry run streamlit run src/strava/app.py")
    print("  3. Enjoy faster data loading and new analytics!")


if __name__ == "__main__":
    # Allow custom database path from command line
    cli_db_path = sys.argv[1] if len(sys.argv) > 1 else None
    import_all(db_path=cli_db_path)
