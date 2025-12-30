import streamlit as st
import pandas as pd
from pathlib import Path


@st.cache_data
def load_data():
    """Load activity data from the database."""
    try:
        from db.db_manager import DatabaseManager

        # Get database path
        current_dir = Path(__file__).parent
        project_root = current_dir.parent.parent
        db_path = project_root / "data" / "strava.db"

        if not db_path.exists():
            st.error(
                f"Database not found at {db_path}. Please run: poetry run python src/strava/db/import_all.py"
            )
            return pd.DataFrame()

        db = DatabaseManager(str(db_path))

        # Load query from file
        query = db.load_query("get_all_activities")

        rows = db.execute_query(query)
        df = pd.DataFrame([dict(row) for row in rows])

        if df.empty:
            st.warning("No activities found in database.")
            return df

        # Convert date column to datetime
        df["activity_date"] = pd.to_datetime(df["activity_date"])

        # Ensure commute column is boolean
        df["commute"] = df["commute"].astype(bool)

        # Pre-calculate pace_decimal for the entire dataset
        if "moving_time" in df.columns and "distance" in df.columns:
            df["pace_decimal"] = df.apply(
                lambda x: (x["moving_time"] / 60) / x["distance"] if x["distance"] > 0 else None,
                axis=1,
            )

        return df

    except Exception as e:
        st.error(f"Error loading data from database: {e}")
        return pd.DataFrame()


@st.cache_data
def get_activity_stream(activity_id: int) -> pd.DataFrame:
    """
    Get detailed stream data for a specific activity from the database.

    Args:
        activity_id: The activity ID

    Returns:
        DataFrame with stream data (timestamp, HR, GPS, pace, etc.)
    """
    try:
        from db.db_manager import DatabaseManager

        current_dir = Path(__file__).parent
        project_root = current_dir.parent.parent
        db_path = project_root / "data" / "strava.db"

        if not db_path.exists():
            return pd.DataFrame()

        db = DatabaseManager(str(db_path))
        stream_records = db.get_activity_stream(activity_id)

        if not stream_records:
            return pd.DataFrame()

        df = pd.DataFrame(stream_records)

        # Convert timestamp to datetime
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"])

        return df

    except Exception as e:
        st.error(f"Error loading stream data: {e}")
        return pd.DataFrame()


@st.cache_data
def get_activities_with_streams() -> pd.DataFrame:
    """
    Get list of activities that have detailed stream data available.

    Returns:
        DataFrame with activity IDs that have stream data
    """
    try:
        from db.db_manager import DatabaseManager

        current_dir = Path(__file__).parent
        project_root = current_dir.parent.parent
        db_path = project_root / "data" / "strava.db"

        if not db_path.exists():
            return pd.DataFrame()

        db = DatabaseManager(str(db_path))
        query = db.load_query("get_activities_with_streams")
        rows = db.execute_query(query)

        return pd.DataFrame([dict(row) for row in rows])

    except Exception:
        return pd.DataFrame()
