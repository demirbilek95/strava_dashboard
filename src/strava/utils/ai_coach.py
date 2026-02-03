import os
import datetime
import google.generativeai as genai
from dotenv import load_dotenv


class AICoach:  # pylint: disable=too-few-public-methods
    def __init__(self):
        load_dotenv()
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment variables.")

        genai.configure(api_key=api_key)
        # Switching to gemini-flash-latest as verified working model for free tier
        self.model = genai.GenerativeModel("gemini-flash-latest")

    def generate_training_plan(self, user_goal: str, activity_data: str, race_data: str) -> str:
        """
        Generates a training plan based on user goal and history.

        Args:
            user_goal: The user's specific running goal.
            activity_data: A summary string of the last 4 weeks of activities.
            race_data: A summary string of recent race performances.

        Returns:
            A markdown string containing the training plan.
        """
        current_date = datetime.date.today().strftime("%Y-%m-%d")

        prompt = f"""
        You are an expert running coach. Today is {current_date}.
        
        My Goal: {user_goal}
        
        Here is my activity data for the last 4 weeks:
        {activity_data}
        
        Here are my recent race performances:
        {race_data}
        
        Based on this data, please provide a detailed training plan.
        - Analyze my recent training load and race performance.
        - Create a structured plan (e.g., weekly schedule) to help me achieve my goal.
        - Include specific paces/heart rate zones if possible based on my data.
        - Limit the output to a reasonable length for a web view, but be comprehensive.
        
        Format your response in Markdown.
        """

        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:  # pylint: disable=broad-exception-caught
            return f"Error generating plan: {str(e)}"
