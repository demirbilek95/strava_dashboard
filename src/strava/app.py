import streamlit as st
from views.general import page_general  # pylint: disable=import-error
from views.activities import page_activity_run_details  # pylint: disable=import-error
from views.races import page_races  # pylint: disable=import-error
from views.deep_dive import page_recent_activities  # pylint: disable=import-error
from data import load_data  # pylint: disable=import-error
from db.db_manager import DatabaseManager  # pylint: disable=import-error
from db.api_importer import StravaImporter  # pylint: disable=import-error
from utils.strava_api import StravaAPI  # pylint: disable=import-error

# Set page config
st.set_page_config(page_title="Strava Analytics", layout="wide")


def show_welcome_page():
    """Show the welcome page for initial setup."""
    st.title("🏃 Welcome to Strava Analytics")

    st.markdown(
        """
    This application allows you to analyze your Strava activities in depth.
    To get started, please enter your Strava Athlete ID to fetch your data.
    """
    )

    athlete_id = st.text_input("Strava Athlete ID", placeholder="e.g. 12345678")

    if st.button("Connect & Import Data"):
        if not athlete_id:
            st.error("Please enter an Athlete ID.")
            return

        try:
            # Initialize API and DB
            api = StravaAPI()

            # Verify Athlete
            try:
                athlete = api.get_athlete()
                if str(athlete.get("id")) != str(athlete_id):
                    st.warning(
                        f"Authenticated as {athlete.get('firstname')} {athlete.get('lastname')} (ID: {athlete.get('id')}), but you entered {athlete_id}. Proceeding with authenticated user..."
                    )
                else:
                    st.success(
                        f"Verified athlete: {athlete.get('firstname')} {athlete.get('lastname')}"
                    )
            except Exception as e:
                st.error(f"Failed to authenticate with Strava: {e}")
                return

            # Setup Database
            db = DatabaseManager()
            db.create_tables()

            # Run Import
            importer = StravaImporter(db, api)

            progress_bar = st.progress(0)
            status_text = st.empty()

            def update_progress(msg, percent):
                status_text.text(msg)
                progress_bar.progress(percent)

            with st.spinner(
                "Importing data from Strava... This may take a while depending on your activity count."
            ):
                importer.import_all_data(progress_callback=update_progress)

            st.success("Import complete! Loading dashboard...")
            st.rerun()

        except Exception as e:
            st.error(f"An error occurred during setup: {e}")


def main():
    # Check if database exists and has data
    db = DatabaseManager()

    # Check if tables exist first
    try:
        activity_count = db.get_activity_count()
    except Exception:
        # Tables might not exist
        activity_count = 0

    if activity_count == 0:
        show_welcome_page()
        return

    st.title("🏃 Strava Activity Analytics")

    df = load_data()

    if df.empty:
        st.warning("Database exists but returned no data. Try resetting.")
        if st.button("Reset Database"):
            # Logic to reset/delete DB could go here, for now just show welcome
            show_welcome_page()
        return

    # Navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Go to", ["General Overview", "Activity Run Details", "Deep Dive", "Races"]
    )

    # Reload Data Option
    if st.sidebar.button("🔄 Refresh Data from Strava"):
        try:
            api = StravaAPI()
            importer = StravaImporter(db, api)
            with st.spinner("Refreshing data..."):
                importer.import_all_data()
            st.success("Data refreshed!")
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"Update failed: {e}")

    # Global Zone Settings
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Heart Rate Zones")
    # Default values based on previous code
    z1 = st.sidebar.number_input("Zone 1 Limit (Recovery)", value=145, step=1, key="global_z1")
    z2 = st.sidebar.number_input("Zone 2 Limit (Aerobic)", value=164, step=1, key="global_z2")
    z3 = st.sidebar.number_input("Zone 3 Limit (Tempo)", value=174, step=1, key="global_z3")
    z4 = st.sidebar.number_input("Zone 4 Limit (Threshold)", value=188, step=1, key="global_z4")

    zones = [z1, z2, z3, z4]

    if page == "General Overview":
        page_general(df, zones)
    elif page == "Activity Run Details":
        page_activity_run_details(df, zones)
    elif page == "Deep Dive":
        page_recent_activities(df, zones)
    elif page == "Races":
        page_races(df, zones)


if __name__ == "__main__":
    main()
