"""QUEST-style threshold estimation for masked target detection."""
import math

import numpy as np
from scipy.special import ndtr

GRID = np.linspace(-60.0, -6.0, 55)
SIGMA = 4.0
LAPSE = 0.02
MAX_TRIALS = 40
MIN_TRIALS = 20
SD_STOP = 2.0


def prior():
    """Return the normalized normal prior over target threshold in dBFS."""
    mean = -30.0
    sd = 12.0
    density = np.exp(-0.5 * ((GRID - mean) / sd) ** 2)
    return density / density.sum()


def p_correct(level_db, T_grid):
    """Return correct-response probability for two-interval detection."""
    level = float(level_db)
    threshold = np.asarray(T_grid, dtype=float)
    return 0.5 + (0.5 - LAPSE) * ndtr(
        (level - threshold) / SIGMA
    )


def posterior_from_history(history):
    """Rebuild the posterior from (level_db, correct) trials."""
    posterior = prior()
    for level_db, correct in history:
        likelihood = p_correct(level_db, GRID)
        posterior *= likelihood if bool(correct) else (1.0 - likelihood)
        total = posterior.sum()
        if not np.isfinite(total) or total <= 0.0:
            raise ValueError("Posterior normalization failed.")
        posterior /= total
    return posterior


def next_level(posterior):
    """Place the next trial at the rounded posterior-mean threshold."""
    posterior = _normalized(posterior)
    mean = float(np.sum(posterior * GRID))
    level = float(np.clip(mean, GRID[0], GRID[-1]))
    return round(level * 2.0) / 2.0


def estimate(posterior):
    """Return threshold, confidence interval, and posterior SD in dB."""
    posterior = _normalized(posterior)
    mean = float(np.sum(posterior * GRID))
    variance = float(np.sum(posterior * (GRID - mean) ** 2))
    sd = math.sqrt(max(0.0, variance))
    return {
        "threshold": mean,
        "ci_lo": max(float(GRID[0]), mean - 1.96 * sd),
        "ci_hi": min(float(GRID[-1]), mean + 1.96 * sd),
        "sd_db": sd,
    }


def is_done(history, posterior):
    """Stop at the trial cap or once the posterior is sufficiently narrow."""
    count = len(history)
    return count >= MAX_TRIALS or (
        count >= MIN_TRIALS
        and estimate(posterior)["sd_db"] <= SD_STOP
    )


def _normalized(posterior):
    posterior = np.asarray(posterior, dtype=float)
    if posterior.shape != GRID.shape:
        raise ValueError(f"posterior must have shape {GRID.shape}.")

    total = posterior.sum()
    if (
        not np.all(np.isfinite(posterior))
        or np.any(posterior < 0.0)
        or total <= 0.0
    ):
        raise ValueError(
            "posterior must contain finite, nonnegative mass."
        )
    return posterior / total


def _selfcheck():
    true_threshold = -32.0
    for seed in (0, 1, 2):
        rng = np.random.default_rng(seed)
        history = []
        posterior = posterior_from_history(history)

        while not is_done(history, posterior):
            level = next_level(posterior)
            correct = rng.random() < float(
                p_correct(level, true_threshold)
            )
            history.append((level, correct))
            posterior = posterior_from_history(history)

        result = estimate(posterior)
        assert abs(result["threshold"] - true_threshold) <= 5.0, (
            seed, result
        )

    assert -31.0 <= next_level(prior()) <= -29.0
    print("masked.py selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
