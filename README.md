# Strava Analytics Dashboard

A fun project to have a comprehensive analytics dashboard for Strava activity data. This project provides detailed insights into your training patterns, heart rate zones, pace distributions, and race performances through an interactive Streamlit web application.

## Features

- **Activity Data Management**
  - Import activities from Strava CSV export
  - Parse detailed stream data from TCX and FIT files
  - SQLite database for efficient data storage and querying
  - Automatic data deduplication and updates

- **Interactive Dashboard**
  - Multiple analysis views (General Overview, Run Details, Deep Dive, Race Analysis)
  - Interactive date range filtering
  - Responsive visualizations with Plotly

- **Performance Analytics (WIP)**
  - Heart rate zone distribution analysis
  - Pace and speed metrics
  - Weekly/monthly training volume tracking
  - Best effort identification for standard race distances
  - Individual activity deep dive with GPS data visualization

- **Data Visualization (WIP)**
  - Weekly training volume trends
  - Activity type distribution
  - Heart rate vs. pace correlation scatter plots
  - Zone-based time and distance breakdowns
  - Altitude and cadence profiles

## Technology Stack

- **Python 3.11+** - Core programming language
- **Streamlit** - Interactive web dashboard framework
- **SQLite** - Local database for data persistence
- **Pandas** - Data manipulation and analysis
- **Plotly** - Interactive data visualizations
- **TCXParser** - TCX file parsing
- **FitParse / Garmin FIT SDK** - FIT file parsing
- **Poetry** - Dependency management and packaging

## Installation

### Prerequisites

- Python 3.11 or higher
- [Poetry](https://python-poetry.org/docs/#installation) for dependency management
- (Optional) pyenv for Python version management

### Setup Steps

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd strava
   ```

2. **Install dependencies with Poetry**
   ```bash
   poetry install
   ```

3. **Initialize the database**
   ```bash
   poetry run python src/strava/db/import_all.py
   ```

   This will:
   - Create the SQLite database at `data/strava.db`
   - Import activities from CSV files in the `data/` directory
   - Parse and import detailed stream data from TCX/FIT files

## Usage

### Running the Dashboard

Start the Streamlit application:

```bash
cd /path/to/strava
poetry run streamlit run src/strava/app.py
```

The dashboard will open in your default web browser at `http://localhost:8502`.

### Dashboard Views

#### General Overview
- Total activities, distance, and duration
- Weekly training volume by sport type
- Activity distribution pie charts
- Heart rate zone intensity distribution
- Recent activities table

#### Activity Run Details
- Non-commute run analysis
- Average, median, and fastest pace calculations
- Weekly distance trends
- Heart rate vs. pace scatter plot with zone overlays
- Training intensity distribution (time or distance-based)

#### Deep Dive Analysis
- Select individual activities with TCX/FIT data
- Detailed heart rate profile with zone overlays
- Pace profile over time
- Zone distribution for the specific activity
- GPS-based metrics

#### Race Analysis
- Automatic identification of best efforts for standard distances (5K, 10K, Half Marathon, Marathon)
- Top 3 performances for each distance
- Time, pace, and heart rate metrics for each effort

## Project Structure

```
strava/
├── data/                          # Data directory (gitignored)
│   ├── strava.db                 # SQLite database
│   ├── activities.csv            # Strava activity CSV export
│   └── *.tcx, *.fit              # Activity track files
├── src/strava/
│   ├── app.py                    # Main Streamlit application
│   ├── data.py                   # Data loading functions
│   ├── db/
│   │   ├── db_manager.py         # Database operations
│   │   ├── import_activities.py  # CSV import script
│   │   ├── import_streams.py     # TCX/FIT import script
│   │   ├── import_all.py         # Combined import script
│   │   └── queries/              # SQL query files
│   │       ├── create_schema.sql
│   │       ├── get_all_activities.sql
│   │       ├── get_activities_with_streams.sql
│   │       └── get_activity_stream.sql
│   └── views/
│       ├── general.py            # General overview page
│       ├── activities.py         # Run details page
│       ├── deep_dive.py          # Individual activity analysis
│       └── races.py              # Race analysis page
├── tests/                         # Test files (placeholder)
├── .github/workflows/             # GitHub Actions CI
│   └── lint.yml                  # Code quality checks
├── .pylintrc                      # Pylint configuration
├── .flake8                        # Flake8 configuration
├── pyproject.toml                 # Project metadata and dependencies
└── README.md                      # This file
```

## Data Flow

1. **Data Import**
   - Export activities from Strava as CSV
   - Place CSV and TCX/FIT files in `data/` directory
   - Run import scripts to populate SQLite database

2. **Database Storage**
   - `activities` table: Summary data for all activities
   - `activity_streams` table: Detailed time-series data (GPS, HR, pace, etc.)
   - Indexed for efficient querying by date, type, and activity ID

3. **Dashboard Loading**
   - Application loads data from database using SQL queries from `queries/` directory
   - Pandas DataFrames for data manipulation
   - Streamlit caching for performance (@st.cache_data)

4. **Visualization**
   - User interacts with filters and selectors
   - Data processed and aggregated based on selections
   - Plotly generates interactive charts
   - Metrics displayed in real-time

## Development

### Code Quality

This project uses several tools to maintain code quality:

- **Black** - Code formatting (line length: 100)
- **Flake8** - Style guide enforcement
- **Pylint** - Code analysis and quality checks

Run linters locally:

```bash
# Format code with black
poetry run black src/

# Check code with flake8
poetry run flake8 src/

# Run pylint
poetry run pylint src/strava/
```

### GitHub Actions

The project includes automated code quality checks that run on every push and pull request:
- Black formatting verification
- Flake8 linting
- Pylint analysis

### Contributing

1. Ensure all linters pass before committing
2. Follow existing code style and patterns
3. Use snake_case for variable and column names
4. Keep SQL queries in separate files under `db/queries/`
5. Add docstrings to functions and classes
6. Update README if adding new features

## Database Schema

### activities table
Stores summary information for each activity including:
- Activity metadata (ID, date, name, type, description)
- Time metrics (elapsed, moving)
- Distance and speed metrics
- Elevation data
- Heart rate statistics
- Cadence and power data
- Temperature and calories

### activity_streams table
Stores time-series data for activities with detailed tracking:
- Timestamp and elapsed time
- GPS coordinates (latitude, longitude)
- Distance and speed
- Heart rate
- Altitude
- Cadence, power, temperature (when available)
- Source type (TCX or FIT)

## Heart Rate Zones

The application uses customizable heart rate zones for training analysis. Default zones can be configured in `app.py`:

- **Zone 1**: Easy/Recovery (< 139 bpm)
- **Zone 2**: Aerobic/Base (139-150 bpm)
- **Zone 3**: Tempo (150-165 bpm)
- **Zone 4**: Threshold (165-178 bpm)
- **Zone 5**: VO2 Max (> 178 bpm)

## License

This project is for personal use. If you plan to use or distribute this code, please add an appropriate license.

## Acknowledgments

- Strava for providing activity export functionality
- The open-source Python community for excellent tools and libraries
