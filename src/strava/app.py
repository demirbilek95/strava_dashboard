import streamlit as st
from strava.data import load_data
from strava.db.db_manager import DatabaseManager
from strava.db.api_importer import StravaImporter
from strava.utils.strava_api import StravaAPI
from strava.views.general import page_general
from strava.views.activities import page_activity_run_details
from strava.views.races import page_races
from strava.views.deep_dive import page_recent_activities
from strava.views.training_plan import page_ai_training_plan

# Set page config
st.set_page_config(page_title="Strava Analytics", layout="wide")


def handle_authorization(api: StravaAPI, auth_code: str):
    """Handle the OAuth code exchange and initial data import."""
    try:
        with st.spinner("Exchanging code for tokens..."):
            api.exchange_code_for_tokens(auth_code)

        st.success("Successfully connected to Strava!")

        # Setup Database
        database = DatabaseManager()
        database.create_tables()

        # Run Import
        importer = StravaImporter(database, api)

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
        st.cache_data.clear()
        st.rerun()

    except Exception as exc:  # pylint: disable=broad-exception-caught
        st.error(f"An error occurred during setup: {exc}")
        if "401" in str(exc):
            st.error(
                "The authorization code might be expired or invalid. "
                "Please try the 'Authorize' step again."
            )


def show_welcome_page():
    """Show the welcome page for initial setup."""
    st.title("🏃 Welcome to Strava Analytics")

    st.markdown(
        """
    This application allows you to analyze your Strava activities in depth.
    To get started, follow these steps:

    1. **Authorize the App**: Click the button below to go to Strava and grant permissions.
    2. **Copy the Code**: After authorizing, you will be redirected to `localhost`.
       Copy the `code` parameter from the address bar.
    3. **Connect**: Paste the code below and click 'Complete Connection'.
    """
    )

    try:
        api = StravaAPI()
        auth_url = api.get_authorization_url()
        st.link_button("🔑 Authorize Strava", auth_url, type="primary")
    except Exception as exc:  # pylint: disable=broad-exception-caught
        st.error(f"Failed to generate authorization URL: {exc}")
        st.info("Make sure `STRAVA_CLIENT_ID` is set in your `.env` file.")

    st.divider()

    auth_code = st.text_input(
        "Step 3: Paste Authorization Code here", placeholder="e.g. a1b2c3d4..."
    )

    if st.button("Complete Connection & Import Data"):
        if not auth_code:
            st.error("Please paste the authorization code from the Strava redirect URL.")
            return

        api = StravaAPI()
        handle_authorization(api, auth_code)


def handle_refresh(database: DatabaseManager):
    """Handle the sidebar refresh logic."""
    if st.sidebar.button("🔄 Refresh Data from Strava"):
        try:
            api = StravaAPI()
            importer = StravaImporter(database, api)

            progress_bar = st.sidebar.progress(0)
            status_text = st.sidebar.empty()

            def update_progress(msg, percent):
                status_text.text(msg)
                progress_bar.progress(percent)

            with st.spinner("Refreshing data..."):
                count = importer.import_all_data(progress_callback=update_progress)

            if count > 0:
                st.sidebar.success(f"Successfully imported {count} new activities!")
                st.cache_data.clear()
                st.rerun()
            else:
                st.sidebar.info("Data is already up to date.")
                # Still offer to clear cache if they suspect stale data
                if st.sidebar.button("🧹 Clear App Cache"):
                    st.cache_data.clear()
                    st.rerun()

        except Exception as exc:  # pylint: disable=broad-exception-caught
            st.sidebar.error(f"Update failed: {exc}")
            if "401" in str(exc) or "missing" in str(exc).lower():
                st.sidebar.warning("Permissions might be missing or expired.")
                if st.sidebar.button("🔑 Re-authorize Strava"):
                    st.session_state["force_reauth"] = True
                    st.rerun()


def main():
    """Main application entry point."""
    # Check if database exists and has data
    database = DatabaseManager()

    # Check for forced re-authorization
    if st.session_state.get("force_reauth"):
        show_welcome_page()
        return

    # Check if tables exist first
    try:
        activity_count = database.get_activity_count()
    except Exception:  # pylint: disable=broad-exception-caught
        # Tables might not exist
        activity_count = 0

    if activity_count == 0:
        show_welcome_page()
        return

    st.title("🏃 Strava Activity Analytics")

    dataframe = load_data()

    # Navigation
    st.sidebar.title("Navigation")
    page_options = ["General Overview", "Activity Run Details", "Deep Dive", "AI Coach", "Races"]

    # Handle navigation from other pages
    if "requested_page" in st.session_state:
        st.session_state["active_page"] = st.session_state.pop("requested_page")


    # helper for radio button
    # If active_page is not set, default to first option
    if "active_page" not in st.session_state:
        st.session_state.active_page = page_options[0]

    # We use the key="active_page" to automatically sync with session_state
    # No need to manually set index or update session_state manually unless forcing a change
    page = st.sidebar.radio("Go to", page_options, key="active_page")

    handle_refresh(database)

    # Global Zone Settings
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Heart Rate Zones")
    z1 = st.sidebar.number_input("Zone 1 Limit (Recovery)", value=145, step=1, key="global_z1")
    z2 = st.sidebar.number_input("Zone 2 Limit (Aerobic)", value=164, step=1, key="global_z2")
    z3 = st.sidebar.number_input("Zone 3 Limit (Tempo)", value=174, step=1, key="global_z3")
    z4 = st.sidebar.number_input("Zone 4 Limit (Threshold)", value=188, step=1, key="global_z4")

    zones = [z1, z2, z3, z4]

    if page == "General Overview":
        page_general(dataframe, zones)
    elif page == "Activity Run Details":
        page_activity_run_details(dataframe, zones)
    elif page == "Deep Dive":
        page_recent_activities(dataframe, zones)
    elif page == "AI Coach":
        page_ai_training_plan(dataframe, database)
    elif page == "Races":
        page_races(dataframe, zones)


if __name__ == "__main__":
    main()
