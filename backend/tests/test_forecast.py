import numpy as np
import pytest

from kaushalniti.forecast import backtest, forecast, scenarios


def test_forecast_follows_a_trend():
    y = [10 + 2 * t for t in range(36)]
    f = forecast(y, 6)
    assert len(f) == 6
    assert f[0] == pytest.approx(82, abs=2) and f[-1] > f[0]


def test_forecast_never_negative():
    assert (forecast([50 - 3 * t for t in range(20)], 12) >= 0).all()


def test_forecast_needs_history():
    with pytest.raises(ValueError):
        forecast([1, 2], 3)


def test_backtest_error_is_zero_on_a_flat_series():
    assert backtest([40.0] * 48, 12) == pytest.approx([0.0] * 13)


def test_scenarios_bracket_the_median():
    rng = np.random.default_rng(1)
    y = 60 + np.arange(60) * 0.5 + rng.normal(0, 8, 60)
    s = scenarios(y, 12)
    assert s["LOW"] <= s["MEDIAN"] <= s["HIGH"]
    assert s["MEDIAN"] == pytest.approx(sum(s["monthly"]), abs=1)
    assert "back-test" in s["method"] and len(s["backtest_errors"]) >= 5


def test_short_history_uses_default_band():
    s = scenarios([20, 22, 25, 24, 27, 30], 6)
    assert s["band"] == [-0.25, 0.25] and "default" in s["method"]


def test_scenarios_are_deterministic():
    y = [30 + (t * 7) % 11 for t in range(50)]
    assert scenarios(y, 12) == scenarios(y, 12)
