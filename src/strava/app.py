import datetime
import os
import time

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


def _check_ip_allowlist() -> None:
    """Block the request if ALLOWED_IPS is set and the client IP is not on the list.

    Configure via env var: ALLOWED_IPS=1.2.3.4,5.6.7.8
    Leave unset (or empty) to allow all IPs (default / local dev).

    Relies on the X-Forwarded-For header set by the upstream proxy (Render,
    Cloudflare, nginx). The first address in that header is the real client IP.
    """
    raw = os.getenv("ALLOWED_IPS", "").strip()
    if not raw:
        return  # No allowlist — open access

    allowed = {ip.strip() for ip in raw.split(",") if ip.strip()}

    # Streamlit >= 1.31 exposes all request headers via st.context.headers
    forwarded_for = st.context.headers.get("X-Forwarded-For", "")
    real_ip = st.context.headers.get("X-Real-Ip", "")
    # X-Forwarded-For is a comma-separated chain; leftmost entry is the client
    client_ip = (forwarded_for.split(",")[0] if forwarded_for else real_ip).strip()

    if client_ip not in allowed:
        st.error("403 — Access denied.")
        st.stop()


def handle_authorization(api: StravaAPI, auth_code: str):
    """Handle the OAuth code exchange and initial data import."""
    try:
        with st.spinner("Exchanging code for tokens..."):
            token_data = api.exchange_code_for_tokens(auth_code)

        st.success("Successfully connected to Strava!")

        # Setup Database
        database = DatabaseManager()
        database.create_tables()

        # Store athlete info in session
        athlete = token_data.get("athlete") or {}
        athlete_id = athlete.get("id")
        if athlete_id:
            database.upsert_user_tokens(
                athlete_id,
                api.access_token,
                api.refresh_token,
                token_data.get("expires_at", 0),
            )
            st.session_state["athlete_id"] = athlete_id
            st.session_state["athlete_name"] = athlete.get("firstname", "Athlete")

        # Run Import
        scoped_db = DatabaseManager(athlete_id=athlete_id) if athlete_id else database
        importer = StravaImporter(scoped_db, api)

        progress_bar = st.progress(0)
        status_text = st.empty()

        def update_progress(msg, percent):
            status_text.text(msg)
            progress_bar.progress(percent)

        with st.spinner("Importing last 3 months of data from Strava… Rate-limited for safety."):
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
                width="stretch",
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


_PERIOD_OPTIONS = {
    "Last month": 30,
    "Last 3 months": 90,
    "Last 6 months": 180,
    "Last year": 365,
    "All time": None,
}

# Session-state key for the global period selector.
# Cleared on sync so the selector resets after new data arrives.
_DATE_FILTER_KEYS = ("period",)

# How often (in seconds) to automatically check Strava for new activities.
_AUTO_SYNC_INTERVAL_S = 5 * 60  # 5 minutes


def auto_sync(database: DatabaseManager) -> None:
    """Incrementally sync new activities. Shows a spinner on the first run only."""
    athlete_id = st.session_state.get("athlete_id")
    is_first = "last_sync_time" not in st.session_state
    st.session_state["last_sync_time"] = time.time()
    try:
        base_db = DatabaseManager()
        tokens = base_db.get_user_tokens(athlete_id) if athlete_id else None
        if tokens:
            api = StravaAPI(
                access_token=tokens["access_token"],
                refresh_token=tokens["refresh_token"],
                athlete_id=athlete_id,
                db=base_db,
            )
        else:
            api = StravaAPI()  # Fall back to .env for local dev
        importer = StravaImporter(database, api)
        if is_first:
            with st.spinner("Checking for new activities..."):
                count = importer.import_all_data()
        else:
            count = importer.import_all_data()
        if count:
            # Drop stale date-filter state so plots pick up fresh defaults.
            for key in _DATE_FILTER_KEYS:
                st.session_state.pop(key, None)
            st.cache_data.clear()
            st.rerun()
    except Exception:  # pylint: disable=broad-exception-caught
        pass  # Silent failure — don't interrupt the dashboard


def main():  # pylint: disable=too-many-branches,too-many-statements
    """Main application entry point."""
    _check_ip_allowlist()
    athlete_id = st.session_state.get("athlete_id")
    database = DatabaseManager(athlete_id=athlete_id)

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

    # ── Auto-sync: run on first load, then every 5 minutes ────────
    last_sync = st.session_state.get("last_sync_time", 0)
    if time.time() - last_sync > _AUTO_SYNC_INTERVAL_S:
        auto_sync(database)

    # ── Main dashboard ─────────────────────────────────────────────
    st.title("🏃 Strava Activity Analytics")

    dataframe = load_data(athlete_id=athlete_id)

    # Navigation
    st.sidebar.title("Navigation")

    # Show athlete name if logged in
    athlete_name = st.session_state.get("athlete_name")
    if athlete_name:
        st.sidebar.markdown(f"👤 **{athlete_name}**")

    page_options = [
        "General Overview",
        "Activity Run Details",
        "Deep Dive",
        "AI Coach",
        "Races & PRs",
    ]

    if "requested_page" in st.session_state:
        st.session_state["active_page"] = st.session_state.pop("requested_page")

    if "active_page" not in st.session_state:
        st.session_state.active_page = page_options[0]

    page = st.sidebar.radio("Go to", page_options, key="active_page")

    # ── Period selector (above HR zones) ───────────────────────────
    st.sidebar.markdown("---")
    selected_period = st.sidebar.selectbox(
        "Period",
        list(_PERIOD_OPTIONS.keys()),
        index=0,  # default: Last month
        key="period",
    )
    days = _PERIOD_OPTIONS[selected_period]

    start_date = (
        (datetime.date.today() - datetime.timedelta(days=days)) if days is not None else None
    )

    # Global Zone Settings
    st.sidebar.markdown("---")
    st.sidebar.markdown("### Heart Rate Zones")
    z1 = st.sidebar.number_input("Zone 1 Limit (Recovery)", value=145, step=1, key="global_z1")
    z2 = st.sidebar.number_input("Zone 2 Limit (Aerobic)", value=164, step=1, key="global_z2")
    z3 = st.sidebar.number_input("Zone 3 Limit (Tempo)", value=174, step=1, key="global_z3")
    z4 = st.sidebar.number_input("Zone 4 Limit (Threshold)", value=188, step=1, key="global_z4")

    zones = [z1, z2, z3, z4]

    # ── Logout button ───────────────────────────────────────────────
    st.sidebar.markdown("---")
    if st.sidebar.button("Log out"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.cache_data.clear()
        st.rerun()

    if page == "General Overview":
        page_general(dataframe, zones, start_date)
    elif page == "Activity Run Details":
        page_activity_run_details(dataframe, zones, start_date)
    elif page == "Deep Dive":
        page_recent_activities(dataframe, zones)
    elif page == "AI Coach":
        page_ai_training_plan(dataframe, database)
    elif page == "Races & PRs":
        page_races(dataframe, zones, database, start_date)


if __name__ == "__main__":
    main()
