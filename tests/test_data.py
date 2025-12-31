
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch
import sys

# Mock streamlit before importing strava.data to disable caching and UI errors
mock_st = MagicMock()
mock_st.cache_data = lambda func: func
sys.modules["streamlit"] = mock_st

from strava.data import load_data, get_activity_stream

@pytest.fixture
def mock_streamlit():
    """Mock streamlit module."""
    with patch("strava.data.st") as mock_st:
        yield mock_st

@pytest.fixture
def mock_db_manager():
    """Mock DatabaseManager."""
    # We patch it in strava.data because that's where it's used
    with patch("strava.data.DatabaseManager") as mock_db_cls:
        mock_instance = MagicMock()
        mock_db_cls.return_value = mock_instance
        yield mock_instance

@patch("strava.data.st.cache_data", lambda func: func)
def test_load_data_empty(mock_db_manager, mock_streamlit):
    """Test load_data when database is empty."""
    mock_db_manager.load_query.return_value = "SELECT ..."
    mock_db_manager.execute_query.return_value = []
    
    with patch("pathlib.Path.exists", return_value=True):
        df = load_data()
        
    assert df.empty
    mock_streamlit.warning.assert_called_once()

@patch("strava.data.st.cache_data", lambda func: func)
def test_load_data_processing(mock_db_manager, mock_streamlit):
    """Test load_data with data processing."""
    mock_data = [
        {
            "activity_id": 1, 
            "activity_date": "2023-01-01T10:00:00", 
            "commute": 0,
            "moving_time": 360,
            "distance": 1.0
        }
    ]
    
    mock_db_manager.load_query.return_value = "SELECT ..."
    mock_db_manager.execute_query.return_value = mock_data
    
    with patch("pathlib.Path.exists", return_value=True):
        df = load_data()
        
    assert not df.empty
    assert pd.api.types.is_datetime64_any_dtype(df["activity_date"])
    assert df["commute"].dtype == bool
    assert "pace_decimal" in df.columns
    assert float(df.iloc[0]["pace_decimal"]) == 6.0

@patch("strava.data.st.cache_data", lambda func: func)
def test_get_activity_stream(mock_db_manager, mock_streamlit):
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

