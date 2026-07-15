"""QUEST-style threshold estimation for concurrent minimum audible angle."""
import math

import numpy as np

GRID = np.linspace(np.log10(1.0), np.log10(60.0), 61)
SIGMA = 0.12
LAPSE = 0.02
MAX_TRIALS = 40
MIN_TRIALS = 20
SD_STOP = 0.06

_ERF = np.frompyfunc(math.erf, 1, 1)


def prior():
    """Normalized normal prior over log10 threshold."""
    mean = np.log10(15.0)
    sd = 0.35
    density = np.exp(-0.5 * ((GRID - mean) / sd) ** 2)
    return density / density.sum()


def _ndtr(x):
    """Standard normal CDF using only numpy and the standard library."""
    x = np.asarray(x, dtype=float)
    erf = np.asarray(_ERF(x / np.sqrt(2.0)), dtype=float)  # frompyfunc yields object dtype
    return 0.5 * (1.0 + erf)


def p_correct(delta_deg, T_grid):
    """Probability of a correct two-alternative response."""
    delta = float(delta_deg)
    if delta <= 0.0:
        raise ValueError("delta_deg must be positive.")
    threshold = np.asarray(T_grid, dtype=float)
    z = (np.log10(delta) - threshold) / SIGMA
    return 0.5 + (0.5 - LAPSE) * _ndtr(z)


def posterior_from_history(history):
    """Rebuild the posterior from a sequence of (delta_deg, correct) trials."""
    posterior = prior()
    for delta, correct in history:
        likelihood = p_correct(delta, GRID)
        posterior *= likelihood if bool(correct) else (1.0 - likelihood)
        total = posterior.sum()
        if not np.isfinite(total) or total <= 0.0:
            raise ValueError("Posterior normalization failed.")
        posterior /= total
    return posterior


def next_delta(posterior):
    """Place the next trial at the posterior mean threshold."""
    posterior = _normalized(posterior)
    mean = float(np.sum(posterior * GRID))
    delta = np.clip(10.0 ** mean, 1.0, 60.0)
    return round(float(delta), 1)


def estimate(posterior):
    """Return threshold, log-normal confidence interval, and log-space SD."""
    posterior = _normalized(posterior)
    mean = float(np.sum(posterior * GRID))
    variance = float(np.sum(posterior * (GRID - mean) ** 2))
    sd = math.sqrt(max(0.0, variance))
    return {
        "threshold": float(10.0 ** mean),
        "ci_lo": float(10.0 ** (mean - 1.96 * sd)),
        "ci_hi": float(10.0 ** (mean + 1.96 * sd)),
        "sd_log": sd,
    }


def is_done(history, posterior):
    """Stop at the trial cap or once the posterior is sufficiently narrow."""
    n = len(history)
    return n >= MAX_TRIALS or (
        n >= MIN_TRIALS and estimate(posterior)["sd_log"] <= SD_STOP
    )


def _normalized(posterior):
    posterior = np.asarray(posterior, dtype=float)
    if posterior.shape != GRID.shape:
        raise ValueError(f"posterior must have shape {GRID.shape}.")
    total = posterior.sum()
    if not np.all(np.isfinite(posterior)) or total <= 0.0:
        raise ValueError("posterior must contain finite, nonnegative mass.")
    return posterior / total


def _selfcheck():
    true_log_threshold = np.log10(8.0)
    for seed in (0, 1, 2):
        rng = np.random.default_rng(seed)
        history = []
        posterior = posterior_from_history(history)
        while not is_done(history, posterior):
            delta = next_delta(posterior)
            correct = rng.random() < float(p_correct(delta, true_log_threshold))
            history.append((delta, correct))
            posterior = posterior_from_history(history)
        result = estimate(posterior)
        assert 5.0 <= result["threshold"] <= 13.0, (seed, result)
        assert result["sd_log"] < 0.12, (seed, result)

    assert 10.0 <= next_delta(prior()) <= 20.0
    print("cmaa.py selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
