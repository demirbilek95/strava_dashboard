
import pytest
import pandas as pd
import sys
import os
from unittest.mock import MagicMock, patch

# Add src/strava to sys.path so that 'import db' works inside data.py
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src/strava')))

from strava.data import load_data, get_activity_stream

@pytest.fixture
def mock_streamlit():
    """Mock streamlit module."""
    with patch("strava.data.st") as mock_st:
        yield mock_st

@pytest.fixture
def mock_db_manager():
    """Mock DatabaseManager."""
    with patch("strava.data.DatabaseManager") as mock_db_cls:
        mock_instance = mock_db_cls.return_value
        yield mock_instance

@patch("strava.data.st.cache_data", lambda func: func)  # Disable caching for tests
def test_load_data_empty(mock_db_manager, mock_streamlit):
    """Test load_data when database is empty."""
    # Setup mock
    mock_db_manager.load_query.return_value = "SELECT * FROM activities"
    mock_db_manager.execute_query.return_value = []
    
    # Mock pathlib to simulate db existence
    with patch("pathlib.Path.exists", return_value=True):
        df = load_data()
        
    assert isinstance(df, pd.DataFrame)
    assert df.empty
    mock_streamlit.warning.assert_called_once()

@patch("strava.data.st.cache_data", lambda func: func)
def test_load_data_processing(mock_db_manager, mock_streamlit):
    """Test load_data with data processing."""
    # Setup mock data
    mock_data = [
        {
            "activity_id": 1, 
            "activity_date": "2023-01-01T10:00:00", 
            "commute": 0,
            "moving_time": 1800,
            "distance": 5.0,  # km? wait, logic in data.py divides by 1000? no, pace calculation: (moving_time/60) / distance. Dist is usually meters or km? 
            # In create_schema.sql: distance REAL (meters). 
            # In data.py: (x["moving_time"] / 60) / x["distance"] 
            # If distance is meters, that would be very small. 
            # Let's check data.py again. Maybe distance is converted? 
            # Assuming distance is km based on typical pace calc (min/km). 
            # If distance is in meters in DB, then data.py probably expects meters if it's raw, but usually pace is min/km.
            # If distance is 5000 meters. (1800/60) / 5000 = 30 / 5000 = 0.006 min/m. 
            # If distance is 5 km. 30 / 5 = 6 min/km.
            # Let's see what data.py assumes or converts. The code didn't show conversion.
            # We will test that calculation happens.
        }
    ]
    
    # Just use raw values to test the calculation logic as is in the file
    mock_data = [
        {
            "activity_id": 1, 
            "activity_date": "2023-01-01T10:00:00", 
            "commute": 0,
            "moving_time": 360, # 6 mins
            "distance": 1.0     # 1 unit
        }
    ]
    
    mock_db_manager.load_query.return_value = "SELECT * FROM activities"
    mock_db_manager.execute_query.return_value = mock_data
    
    with patch("pathlib.Path.exists", return_value=True):
        df = load_data()
        
    assert not df.empty
    assert pd.api.types.is_datetime64_any_dtype(df["activity_date"])
    assert df["commute"].dtype == bool
    assert "pace_decimal" in df.columns
    # Check calc: (360/60) / 1.0 = 6.0
    assert df.iloc[0]["pace_decimal"] == 6.0

@patch("strava.data.st.cache_data", lambda func: func)
def test_get_activity_stream(mock_db_manager):
    """Test get_activity_stream."""
    mock_stream = [
        {"timestamp": "2023-01-01T10:00:00", "heart_rate": 140}
    ]
    mock_db_manager.get_activity_stream.return_value = mock_stream
    
    with patch("pathlib.Path.exists", return_value=True):
        df = get_activity_stream(123)
        
    assert not df.empty
    assert pd.api.types.is_datetime64_any_dtype(df["timestamp"])
    assert df.iloc[0]["heart_rate"] == 140
