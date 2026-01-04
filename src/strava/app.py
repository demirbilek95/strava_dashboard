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
    To get started, follow these steps:
    
    1. **Authorize the App**: Click the button below to go to Strava and grant permissions.
    2. **Copy the Code**: After authorizing, you will be redirected to `localhost`. Copy the `code` parameter from the address bar.
    3. **Connect**: Paste the code below and click 'Complete Connection'.
    """
    )

    try:
        api = StravaAPI()
        auth_url = api.get_authorization_url()
        st.link_button("🔑 Authorize Strava", auth_url, type="primary")
    except Exception as e:
        st.error(f"Failed to generate authorization URL: {e}")
        st.info("Make sure `STRAVA_CLIENT_ID` is set in your `.env` file.")

    st.divider()
    
    auth_code = st.text_input("Step 3: Paste Authorization Code here", placeholder="e.g. a1b2c3d4...")
    
    if st.button("Complete Connection & Import Data"):
        if not auth_code:
            st.error("Please paste the authorization code from the Strava redirect URL.")
            return

        try:
            # Initialize API
            api = StravaAPI()
            
            with st.spinner("Exchanging code for tokens..."):
                api.exchange_code_for_tokens(auth_code)
            
            st.success("Successfully connected to Strava!")

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
            if "401" in str(e):
                st.error("The authorization code might be expired or invalid. Please try the 'Authorize' step again.")


def main():
    # Check if database exists and has data
    db = DatabaseManager()

    # Check for forced re-authorization
    if st.session_state.get("force_reauth"):
        show_welcome_page()
        return

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
            if "401" in str(e) or "missing" in str(e).lower():
                st.sidebar.warning("Permissions might be missing or expired.")
                if st.sidebar.button("🔑 Re-authorize Strava"):
                    # Clear data or just show welcome? Let's show welcome.
                    # We can use a session state to force welcome page
                    st.session_state["force_reauth"] = True
                    st.rerun()

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
