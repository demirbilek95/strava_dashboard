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

    def start_training_chat(self, user_goal: str, activity_data: str, race_data: str):
        """
        Starts a chat session for training planning.
        
        Args:
            user_goal: The user's specific running goal.
            activity_data: A summary string of recent activities.
            race_data: A summary string of recent race performances.
            
        Returns:
            A ChatSession object and the initial response text.
        """
        current_date = datetime.date.today().strftime("%Y-%m-%d")
        
        system_instruction = f"""
        You are an expert running coach. Today is {current_date}.
        
        Your Mission:
        - Analyze the user's running data deeply.
        - Create a personalized, realistic training plan based ONLY on the provided data.
        - Be honest about their goal feasibility. If the goal is unrealistic given their history (e.g., lack of volume, pace discrepancy), tell them politely but firmly and suggest an adjusted goal.
        - Do not hallucinate workouts or metrics not supported by their fitness level.
        
        My Goal: {user_goal}
        
        My Activity Data (Last 4 Weeks):
        {activity_data}
        
        My Race History:
        {race_data}
        
        Please provide a detailed training plan.
        - Analyze my recent training load (volume, intensity) and race performance.
        - Create a structured plan (e.g., weekly schedule).
        - Include specific paces and heart rate zones derived from my actual data.
        """
        
        # Initialize chat with history containing the system instruction as the user's first prompt
        # (Gemini API chat history is User/Model/User/Model...)
        chat = self.model.start_chat(history=[])
        
        try:
            response = chat.send_message(system_instruction)
            return chat, response.text
        except Exception as e:  # pylint: disable=broad-exception-caught
            return None, f"Error generating plan: {str(e)}"
