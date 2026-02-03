import streamlit as st
import pandas as pd
from strava.utils.ai_coach import AICoach


def get_recent_activities_summary(df: pd.DataFrame) -> str:
    """
    Summarizes the last 4 weeks of activities.
    """
    if df.empty:
        return "No recent activities found."

    # Filter for last 28 days
    cutoff_date = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=28)
    if "activity_date" not in df.columns:
        return "Activity date column missing."

    recent_df = df[df["activity_date"] >= cutoff_date].copy()

    if recent_df.empty:
        return "No activities in the last 4 weeks."

    summary = []
    summary.append(f"Total Activities (last 4 weeks): {len(recent_df)}")

    # Sort by date
    recent_df = recent_df.sort_values("activity_date", ascending=True)

    for _, row in recent_df.iterrows():
        date_str = row["activity_date"].strftime("%Y-%m-%d")
        name = row.get("activity_name", "Unknown Activity")
        type_ = row.get("activity_type", "Run")
        dist = f"{row['distance']:.2f} km" if pd.notnull(row.get("distance")) else "N/A"

        # Pace logic (min/km)
        pace = "N/A"
        if (
            pd.notnull(row.get("moving_time"))
            and pd.notnull(row.get("distance"))
            and row["distance"] > 0
        ):
            pace_decimal = (row["moving_time"] / 60) / row["distance"]
            mins = int(pace_decimal)
            secs = int((pace_decimal - mins) * 60)
            pace = f"{mins}:{secs:02d} /km"

        avg_hr = (
            f"{int(row['average_heart_rate'])} bpm"
            if pd.notnull(row.get("average_heart_rate"))
            else "N/A"
        )
        max_hr = (
            f"{int(row['max_heart_rate'])} max" if pd.notnull(row.get("max_heart_rate")) else ""
        )

        elev = f"{int(row['elevation_gain'])}m" if pd.notnull(row.get("elevation_gain")) else "0m"

        cadence = (
            f"{int(row['average_cadence'])}spm" if pd.notnull(row.get("average_cadence")) else ""
        )

        # Assemble details
        details = [f"Dist: {dist}", f"Pace: {pace}", f"Elev: {elev}"]
        if avg_hr != "N/A":
            details.append(f"HR: {avg_hr} {max_hr}")
        if cadence:
            details.append(f"Cad: {cadence}")

        summary.append(f"- {date_str}: {type_} - {name}, {', '.join(details)}")

    return "\n".join(summary)


def get_race_summary(df: pd.DataFrame) -> str:
    """
    Summarizes race activities.
    Assuming 'workout_type' == 1 indicates a race (Strava API convention usually).
    Or user might have labeled them. For now, let's look for 'Race' in 'workout_type'
    if mapped, or just search for 'Race' in name if unavailable.
    Actually, let's filter by workout_type == 1 (Race) if available.
    """
    if df.empty:
        return "No races found."

    # Strava workout_type: 0=Run, 1=Race, 2=Long Run, 3=Workout
    # We'll valid rows where workout_type is 1/1.0

    races = pd.DataFrame()
    if "workout_type" in df.columns:
        # Check for numeric 1 or string '1' or 'Race' depending on how it's stored
        # In the loaded dataframe it seems to be float or None based on previous file reads
        # We will try to filter broadly
        races = df[df["workout_type"] == 1]

    if races.empty:
        # Fallback: check if 'race' is in activity name
        races = df[df["activity_name"].str.contains("race", case=False, na=False)]

    if races.empty:
        return "No races identified in data."

    summary = []

    # Sort by date DESC
    races = races.sort_values("activity_date", ascending=False).head(5)  # Last 5 races

    for _, row in races.iterrows():
        date_str = row["activity_date"].strftime("%Y-%m-%d")
        name = row.get("activity_name", "Race")
        dist = f"{row['distance']:.2f} km" if pd.notnull(row.get("distance")) else "N/A"

        pace = "N/A"
        if (
            pd.notnull(row.get("moving_time"))
            and pd.notnull(row.get("distance"))
            and row["distance"] > 0
        ):
            pace_decimal = (row["moving_time"] / 60) / row["distance"]
            mins = int(pace_decimal)
            secs = int((pace_decimal - mins) * 60)
            pace = f"{mins}:{secs:02d} /km"

        time_str = "N/A"
        if pd.notnull(row.get("elapsed_time")):
            total_seconds = int(row["elapsed_time"])
            h = total_seconds // 3600
            m = (total_seconds % 3600) // 60
            s = total_seconds % 60
            time_str = f"{h}:{m:02d}:{s:02d}"

        avg_hr = (
            f"{int(row['average_heart_rate'])} bpm"
            if pd.notnull(row.get("average_heart_rate"))
            else "N/A"
        )

        summary.append(
            f"- {date_str}: {name}, Time: {time_str}, Dist: {dist}, Pace: {pace}, Avg HR: {avg_hr}"
        )

    return "\n".join(summary)


def page_ai_training_plan(dataframe: pd.DataFrame):  # pylint: disable=too-many-branches, too-many-statements
    st.header("🤖 AI Coach Training Plan")
    st.markdown(
        "Generate a personalized training plan using Google's Gemini AI, based on your recent Strava history."
    )

    # Initialize session state for chat and plan
    if "ai_plan" not in st.session_state:
        st.session_state.ai_plan = None
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "gemini_chat" not in st.session_state:
        st.session_state.gemini_chat = None

    # 1. Input Section (Show only if no plan generated yet)
    if not st.session_state.ai_plan:
        col1, _ = st.columns([1, 1])
        with col1:
            user_goal = st.text_area(
                "What is your running goal?",
                height=100,
                placeholder="e.g. I want to run a sub-4 hour marathon in 3 months. I train 4 times a week.",
            )

        generate_btn = st.button("Generate Training Plan", type="primary")

        if generate_btn:
            if not user_goal:
                st.error("Please enter a goal first.")
                return

            with st.spinner("Analyzing your activity data and generating plan..."):
                # Prepare Data
                recent_activity_summary = get_recent_activities_summary(dataframe)
                race_summary = get_race_summary(dataframe)

                # Call AI
                coach = AICoach()
                chat, plan_text = coach.start_training_chat(
                    user_goal, recent_activity_summary, race_summary
                )

                if chat and plan_text:
                    # Success
                    st.session_state.ai_plan = plan_text
                    st.session_state.gemini_chat = chat
                    # Add simple welcome message to history using the plan
                    st.session_state.chat_history.append(
                        {"role": "assistant", "content": plan_text}
                    )
                    st.rerun()
                else:
                    # Error (plan_text contains error message)
                    st.error(plan_text)
                    st.info("Please check if your GOOGLE_API_KEY is set correctly in .env")

    # 2. Results & Chat Section (Show if plan exists)
    else:
        # Option to reset
        if st.button("🔄 Start Over / New Goal"):
            st.session_state.ai_plan = None
            st.session_state.chat_history = []
            st.session_state.gemini_chat = None
            st.rerun()

        st.divider()

        # Display Chat History
        # We iterate through history. The first message is the plan.
        for message in st.session_state.chat_history:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        # Chat Input
        if prompt := st.chat_input("Ask a follow-up question to your coach..."):
            # Add user message to state
            st.session_state.chat_history.append({"role": "user", "content": prompt})
            # Display user message immediately
            with st.chat_message("user"):
                st.markdown(prompt)

            # Get response from Gemini
            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    try:
                        chat = st.session_state.gemini_chat
                        # If for some reason chat object is lost (unlikely in memory session), handle it
                        if not chat:
                            st.error("Connection lost. Please regenerate the plan.")
                        else:
                            response = chat.send_message(prompt)
                            st.markdown(response.text)
                            st.session_state.chat_history.append(
                                {"role": "assistant", "content": response.text}
                            )
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        st.error(f"Error: {e}")
