# Strava Analytics Dashboard

A comprehensive analytics dashboard for Strava activity data. Gain insights into training patterns, heart rate zones, pace distributions, and race performances through an interactive Streamlit web application.

## 🚀 Quick Start

1.  **Clone and Install**
    ```bash
    git clone <repository-url>
    cd strava
    poetry install
    ```

2.  **Configuration**
    Create a `.env` file with your Strava API credentials:
    ```env
    STRAVA_CLIENT_ID=your_client_id
    STRAVA_CLIENT_SECRET=your_client_secret
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

## 📊 Features

-   **General Overview**: High-level training metrics and volume trends.
-   **Run Details**: Deep analysis of running activities with zone overlays.
-   **Deep Dive**: Interactive GPS maps, heart rate profiles, and split analysis for individual activities.
-   **Race Analysis**: Automatic identification of best efforts for standard distances (5K, 10K, HM, Marathon).

## 🛠 Tech Stack

-   **Python 3.11+**, **Streamlit**, **SQLite**, **Pandas**, **Plotly**.

## 🧪 Development

```bash
# Run tests
poetry run pytest tests/

# Linting
poetry run black src/
poetry run flake8 src/
poetry run pylint src/strava/
```
