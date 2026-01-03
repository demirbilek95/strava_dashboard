
import pandas as pd
import plotly.graph_objects as go
from unittest.mock import MagicMock
import sys
import os

# Add src to path
sys.path.append(os.path.abspath("src"))

# Mock streamlit before importing deep_dive
sys.modules["streamlit"] = MagicMock()
sys.modules["streamlit_folium"] = MagicMock()

from strava.views.deep_dive import _create_track_df, _render_plots

def test_create_track_df():
    print("Testing _create_track_df...")
    timestamps = ["2023-01-01 10:00:00", "2023-01-01 10:00:01"]
    hrs = [140, 142]
    alts = [10, 11]
    dists = [0, 5]
    lats = [123456789, 123456790]  # Semicircles (approx) or just raw
    lons = [-123456789, -123456790]
    
    # Test with lats/lons
    df = _create_track_df(timestamps, hrs, alts, dists, lats, lons)
    
    assert "latitude" in df.columns, "latitude column missing"
    assert "longitude" in df.columns, "longitude column missing"
    assert not df["latitude"].isnull().all(), "latitude is all null"
    
    # Check conversion (heuristic > 180)
    # 123456789 is way > 180, so it should be converted to degrees (~10 deg)
    assert abs(df["latitude"].iloc[0]) < 180, "latitude not converted to degrees"
    
    print("✅ _create_track_df passed.")

def test_render_plots():
    print("Testing _render_plots (Zone Shading)...")
    
    # Create dummy DF
    df = pd.DataFrame({
        "Elapsed Seconds": [0, 10, 20, 30],
        "Pace_Decimal": [5.0, 5.0, 5.0, 5.0],
        "HR": [140, 150, 160, 170],
        "cadence": [180, 180, 180, 180]
    })
    
    zones = (120, 140, 160, 180) # z1, z2, z3, z4
    pace_zones = [(3.0, 4.0), (4.0, 5.0)] # Dummy
    
    # We need to capture the figure passed to st.plotly_chart
    # inner st.plotly_chart is a mock
    
    _render_plots(df, zones, pace_zones)
    
    # Get the figure argument
    args, _ = sys.modules["streamlit"].plotly_chart.call_args
    fig = args[0]
    
    # Inspect shapes
    # We expect shapes in row 3 (HR), NOT in row 1 (Pace)
    # The layout.shapes list contains all shapes.
    
    # Shapes have yref/xref. For subplots, they match the axis anchor.
    # But make_subplots usually assigns 'y3' to row 3.
    
    hr_shapes = 0
    pace_shapes = 0
    
    for shape in fig.layout.shapes:
        # Our code sets row=3, col=1 for HR.
        # But fig.layout.shapes is a list of layout shapes.
        # When using add_shape with row/col, it maps to the axis.
        # HR is row 3 -> y axis 3?
        # Pace is row 1 -> y axis 1?
        
        # We can check the y range.
        # Pace ranges are small (3-12 min/km). HR ranges are big (0-220 bpm).
        y0 = shape.y0
        y1 = shape.y1
        
        if y1 > 50: # Likely HR
            hr_shapes += 1
        elif y1 < 20: # Likely Pace
            pace_shapes += 1
            
    print(f"Found {hr_shapes} HR shapes and {pace_shapes} Pace shapes.")
    
    assert hr_shapes == 5, f"Expected 5 HR zone shapes, found {hr_shapes}"
    assert pace_shapes == 0, f"Expected 0 Pace zone shapes, found {pace_shapes}"
    
    # Check annotations (labels)
    annotations = fig.layout.annotations
    hr_labels = [a for a in annotations if a.text in ["Z1", "Z2", "Z3", "Z4", "Z5"]]
    print(f"Found {len(hr_labels)} HR zone labels.")
    assert len(hr_labels) == 5, f"Expected 5 HR zone labels, found {len(hr_labels)}"

    print("✅ _render_plots passed.")

def test_render_route_map():
    print("Testing _render_route_map (Map Width)...")
    from strava.views.deep_dive import _render_route_map
    
    # Mock DF with lat/lon
    df = pd.DataFrame({
        "latitude": [10.0, 10.1],
        "longitude": [20.0, 20.1],
        "Time": ["2022-01-01", "2022-01-01"] # Dummy
    })
    
    # Call render
    _render_route_map(df, "Test Activity")
    
    # Check folium_static call
    # sys.modules["streamlit_folium"] was mocked at top of file
    folium_static_mock = sys.modules["streamlit_folium"].folium_static
    
    # Get kwargs
    args, kwargs = folium_static_mock.call_args
    
    width = kwargs.get("width")
    print(f"Map width used: {width}")
    
    assert width >= 1300, f"Expected map width >= 1300, got {width}"
    print("✅ _render_route_map passed.")

if __name__ == "__main__":
    try:
        test_create_track_df()
        test_render_plots()
        test_render_route_map()
        print("\nAll tests passed!")
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        exit(1)
