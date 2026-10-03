"""Demand forecast and LOW / MEDIAN / HIGH scenarios.

Supporting capability, deliberately simple and explainable: damped Holt linear
trend on a monthly series, with scenario bands taken from a rolling-origin
back-test of the same model on the same series.
"""
import numpy as np

PHI = 0.95          # trend damping, so an 18-month extrapolation does not run away
GRID = (0.1, 0.3, 0.5, 0.7, 0.9)
MIN_TRAIN = 24      # months of history before the first back-test origin
FALLBACK_BAND = (-0.25, 0.25)  # used only when history is too short to back-test


def _holt(y, alpha, beta, h):
    """Return (h-step forecasts, sum of squared one-step errors)."""
    level, trend, sse = y[0], y[1] - y[0], 0.0
    for obs in y[1:]:
        pred = level + PHI * trend
        sse += (obs - pred) ** 2
        new_level = alpha * obs + (1 - alpha) * pred
        trend = beta * (new_level - level) + (1 - beta) * PHI * trend
        level = new_level
    damp = np.cumsum(PHI ** np.arange(1, h + 1))
    return np.maximum(0.0, level + damp * trend), sse


def forecast(y, h):
    """Monthly forecast for the next h months; smoothing weights picked by one-step error."""
    y = np.asarray(y, dtype=float)
    if len(y) < 3:
        raise ValueError("need at least 3 months of history to forecast")
    best = min(((a, b) for a in GRID for b in GRID), key=lambda ab: _holt(y, *ab, h)[1])
    return _holt(y, *best, h)[0]


def backtest(y, h):
    """Relative errors of the h-month total, forecasting from every origin with enough history."""
    y = np.asarray(y, dtype=float)
    errors = []
    for origin in range(MIN_TRAIN, len(y) - h + 1):
        predicted = forecast(y[:origin], h).sum()
        if predicted > 0:
            errors.append(y[origin:origin + h].sum() / predicted - 1)
    return errors


def scenarios(y, h, quantiles=(0.1, 0.9)):
    """Total demand over the next h months under LOW / MEDIAN / HIGH."""
    monthly = forecast(y, h)
    median = float(monthly.sum())
    errors = backtest(y, h)
    if len(errors) >= 5:
        lo, hi = np.quantile(errors, quantiles)
        lo, hi = min(float(lo), 0.0), max(float(hi), 0.0)  # the band always contains the median
        method = (f"damped Holt forecast; band = {int(quantiles[0]*100)}th/{int(quantiles[1]*100)}th percentile of "
                  f"{len(errors)} rolling-origin back-test errors on this series")
    else:
        lo, hi = FALLBACK_BAND
        method = "damped Holt forecast; default +/-25% band (history too short to back-test)"
    return {
        "monthly": [round(float(v), 1) for v in monthly],
        "LOW": median * (1 + lo), "MEDIAN": median, "HIGH": median * (1 + hi),
        "band": [float(lo), float(hi)],
        "backtest_errors": [round(float(e), 3) for e in errors],
        "method": method,
    }
