import os
import sys
from unittest.mock import MagicMock
import pandas as pd

# Add src to path
sys.path.append(os.path.abspath("src"))

# Mock streamlit before importing deep_dive.
# fragment must be a pass-through so decorated functions remain callable.
mock_st = MagicMock()
mock_st.fragment = lambda f: f
sys.modules["streamlit"] = mock_st
sys.modules["streamlit_folium"] = MagicMock()

# pylint: disable=wrong-import-position
from strava.views.deep_dive import _render_plots, _render_route_map


def test_render_plots():
    print("Testing _render_plots (Zone-colored HR line)...")

    df = pd.DataFrame(
        {
            "Elapsed Seconds": [0, 10, 20, 30],
            "Pace_Decimal": [5.0, 5.0, 5.0, 5.0],
            "HR": [140, 150, 160, 170],
            "cadence": [180, 180, 180, 180],
        }
    )

    zones = (120, 140, 160, 180)

    _render_plots(df, zones)

    args, _ = sys.modules["streamlit"].plotly_chart.call_args
    fig = args[0]

    # HR zones are now rendered as colored Scatter traces, not shapes.
    # Each trace in the HR subplot has a legendgroup of "hr_zone_<n>".
    hr_zone_traces = [
        t for t in fig.data if (getattr(t, "legendgroup", "") or "").startswith("hr_zone_")
    ]
    print(f"Found {len(hr_zone_traces)} HR zone trace(s).")
    assert (
        len(hr_zone_traces) >= 1
    ), f"Expected at least 1 HR zone trace, found {len(hr_zone_traces)}"

    # No HR shapes should remain (replaced by colored line segments)
    hr_shapes = sum(1 for s in fig.layout.shapes if getattr(s, "y1", 0) > 50)
    assert hr_shapes == 0, f"Expected 0 HR shapes after refactor, found {hr_shapes}"

    print("✅ _render_plots passed.")


def test_render_route_map():
    print("Testing _render_route_map (Map Width)...")

    df = pd.DataFrame(
        {
            "latitude": [10.0, 10.1],
            "longitude": [20.0, 20.1],
            "Time": ["2022-01-01", "2022-01-01"],
        }
    )

    zones = (145, 164, 174, 188)

    _render_route_map(df, zones)

    folium_static_mock = sys.modules["streamlit_folium"].folium_static
    assert folium_static_mock.called, "folium_static was not called"

    _, kwargs = folium_static_mock.call_args
    width = kwargs.get("width")
    print(f"Map width used: {width}")

    assert width >= 1300, f"Expected map width >= 1300, got {width}"
    print("✅ _render_route_map passed.")


if __name__ == "__main__":
    try:
        test_render_plots()
        test_render_route_map()
        print("\nAll tests passed!")
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:  # pylint: disable=broad-exception-caught
        print(f"\n❌ Error: {e}")
        sys.exit(1)
