import streamlit as st
from views.general import page_general  # pylint: disable=import-error
from views.activities import page_activity_run_details  # pylint: disable=import-error
from views.races import page_races  # pylint: disable=import-error
from views.deep_dive import page_recent_activities  # pylint: disable=import-error
from data import load_data  # pylint: disable=import-error

# Set page config
st.set_page_config(page_title="Strava Analytics", layout="wide")


def main():
    st.title("🏃 Strava Activity Analytics")

    df = load_data()

    if df.empty:
        return

    # Navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Go to", ["General Overview", "Activity Run Details", "Deep Dive", "Races"]
    )

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
