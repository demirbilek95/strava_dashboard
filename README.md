# Strava Analytics Dashboard

A comprehensive analytics dashboard and **AI Training Coach** for Strava activity data. Gain insights into training patterns, fatigue levels, and performance trends through an interactive Streamlit application powered by Gemini.

## 🚀 Quick Start

1.  **Clone and Install**
    ```bash
    git clone <repository-url>
    cd strava
    poetry install
    ```

2.  **API Configuration**
    The application requires its own credentials to perform the OAuth exchange. Create a `.env` file with your Client ID and Secret from the [Strava API settings](https://www.strava.com/settings/api):
    ```env
    STRAVA_CLIENT_ID=your_client_id
    STRAVA_CLIENT_SECRET=your_client_secret
    GOOGLE_API_KEY=your_gemini_api_key
    ```

3.  **Run the App**
    ```bash
    poetry run streamlit run src/strava/app.py
    ```

## 🔐 How API & OAuth Works

This project connects directly to the **Strava API** to fetch your activities. Here's the flow:

1.  **Authorization**: When you first open the app, you'll be prompted to "Authorize Strava". This redirects you to Strava's secure login page.
2.  **Permissions**: You grant the app `activity:read_all` permissions. Strava then redirects you back to a local URL with a temporary `code` in the address bar.
3.  **Token Exchange**: You paste this `code` into the app. The app then exchanges it for:
    -   An **Access Token**: Used to make API calls (expires every 6 hours).
    -   A **Refresh Token**: Used to automatically get a new access token when it expires.
4.  **Automatic Refresh**: The app handles token refreshing in the background. You only need to authorize once.

## 🤖 AI Training Coach

The dashboard includes an **agentic AI coach** powered by Gemini 2.5 Flash. It has direct access to your activity database via function calling to provide data-driven feedback:

-   **Automated Planning**: Generates personalized training plans based on your recent mileage, fatigue levels, and goals.
-   **Performance Analysis**: Deep dives into individual activities to detect aerobic decoupling (cardiac drift) and zone compliance.
-   **Zone Deduction**: Automatically suggests heart rate zones based on your recent best efforts and race history.

## 📉 Training Load & Metrics

Monitor your fitness and fatigue with advanced volume tracking:

-   **Suffer Score (Relative Effort)**: Integrated tracking of Strava's effort metric to quantify training stress.
-   **Acute vs. Chronic Load**: Analyzes the ratio of your 7-day load vs. 28-day average to ensure optimal progression and avoid overtraining.
-   **Per-Km Split Analysis**: Precise pace and heart rate data for every kilometer, derived from high-resolution stream data.

## 📊 Features

-   **AI Training Coach**: Personalized feedback and planning powered by LLMs.
-   **General Overview**: High-level training metrics, volume trends, and training load ratios.
-   **Run Details**: Deep analysis of running activities with zone overlays.
-   **Deep Dive**: Interactive GPS maps, heart rate profiles, per-km splits, and aerobic decoupling.
-   **Race Analysis**: Automatic identification of best efforts for standard distances (5K, 10K, HM, Marathon).

## 🛠 Tech Stack

-   **Python 3.11+**, **Streamlit**, **SQLite**, **Pandas**, **Plotly**.
-   **Google Gemini (GenAI)**: Advanced reasoning and tool use for coaching.

## 🧪 Development

```bash
# Run tests
poetry run pytest tests/

# Linting
poetry run black src/
poetry run flake8 src/
poetry run pylint src/strava/
```
