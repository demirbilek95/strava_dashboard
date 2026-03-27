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
            "Importing last 3 months of data from Strava… Rate-limited for safety."
        ):
            importer.import_all_data(progress_callback=update_progress, lookback_months=3)

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
    """Show the welcome/onboarding page for initial setup."""
    # ── Header ──────────────────────────────────────────────────────
    st.markdown(
        """
        <div style="text-align:center; padding: 2rem 0 1rem 0;">
            <h1 style="font-size:3rem; margin-bottom:0.25rem;">🏃 Strava Analytics</h1>
            <p style="color:#aaa; font-size:1.1rem;">
                Your personal training dashboard — powered by your Strava data.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Steps card ──────────────────────────────────────────────────
    _, col_center, _ = st.columns([1, 3, 1])
    with col_center:
        st.markdown("---")

        step1, step2 = st.columns(2)
        with step1:
            st.markdown(
                """
                <div style="background:rgba(255,255,255,0.05); border-radius:12px;
                            padding:1.5rem; text-align:center; height:180px;">
                    <div style="font-size:2.5rem;">🔑</div>
                    <h3 style="margin:0.5rem 0 0.25rem">Step 1</h3>
                    <p style="color:#bbb; font-size:0.9rem; margin:0">
                        Click <b>Connect Strava</b> below to authorise this app.
                        After granting access, you will be redirected back here automatically.
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with step2:
            st.markdown(
                """
                <div style="background:rgba(255,255,255,0.05); border-radius:12px;
                            padding:1.5rem; text-align:center; height:180px;">
                    <div style="font-size:2.5rem;">📊</div>
                    <h3 style="margin:0.5rem 0 0.25rem">Step 2</h3>
                    <p style="color:#bbb; font-size:0.9rem; margin:0">
                        Your last 3 months of activities are imported automatically.
                        Fetch more data (up to all time) via the sidebar after connecting.
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("---")

        # ── Primary connect button ───────────────────────────────────
        try:
            api = StravaAPI()
            auth_url = api.get_authorization_url()
            st.link_button(
                "🔗 Connect with Strava",
                auth_url,
                type="primary",
                use_container_width=True,
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            st.error(f"Failed to generate authorization URL: {exc}")
            st.info("Make sure `STRAVA_CLIENT_ID` is set in your `.env` file.")

        # ── Fallback: manual code paste ─────────────────────────────
        with st.expander("⚙️ Manual connection (if automatic redirect didn't work)"):
            st.caption(
                "If you weren't redirected back automatically, copy the `code=...` value "
                "from your browser's address bar and paste it below."
            )
            auth_code = st.text_input("Authorization code", placeholder="e.g. a1b2c3d4ef...")
            if st.button("Complete Connection & Import Data"):
                if not auth_code:
                    st.error("Please paste the authorization code first.")
                    return
                api = StravaAPI()
                handle_authorization(api, auth_code)


_RANGE_OPTIONS = {
    "Last 3 months": 3,
    "Last 6 months": 6,
    "Last year": 12,
    "All time": None,
}


def handle_refresh(database: DatabaseManager):
    """Handle the sidebar refresh logic."""
    selected_label = st.sidebar.selectbox(
        "Data range",
        list(_RANGE_OPTIONS.keys()),
        index=0,
        key="refresh_range",
    )
    lookback_months = _RANGE_OPTIONS[selected_label]
    st.sidebar.caption(
        "Selecting a longer range fetches missing historical data. "
        "Activities already synced are not re-downloaded."
    )

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
                count = importer.import_all_data(
                    progress_callback=update_progress,
                    lookback_months=lookback_months,
                )

            if count > 0:
                st.sidebar.success(f"Successfully imported {count} new activities!")
                st.cache_data.clear()
                st.rerun()
            else:
                st.sidebar.info("Data is already up to date.")
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
    database = DatabaseManager()

    # ── Auto-detect OAuth redirect code from URL query params ──────
    # Strava redirects back to this app with ?code=<auth_code>&scope=...
    # when the redirect URI is set to http://localhost:8501.
    if st.session_state.get("force_reauth"):
        show_welcome_page()
        return

    params = st.query_params
    if "code" in params and not st.session_state.get("oauth_handled"):
        auth_code = params["code"]
        st.session_state["oauth_handled"] = True
        # Clear the URL params so a refresh doesn't re-trigger the flow
        st.query_params.clear()
        api = StravaAPI()
        handle_authorization(api, auth_code)
        return

    # ── Check if database has data ─────────────────────────────────
    try:
        activity_count = database.get_activity_count()
    except Exception:  # pylint: disable=broad-exception-caught
        activity_count = 0

    if activity_count == 0:
        show_welcome_page()
        return

    # ── Main dashboard ─────────────────────────────────────────────
    st.title("🏃 Strava Activity Analytics")

    dataframe = load_data()

    # Navigation
    st.sidebar.title("Navigation")
    page_options = ["General Overview", "Activity Run Details", "Deep Dive", "AI Coach", "Races"]

    if "requested_page" in st.session_state:
        st.session_state["active_page"] = st.session_state.pop("requested_page")

    if "active_page" not in st.session_state:
        st.session_state.active_page = page_options[0]

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
