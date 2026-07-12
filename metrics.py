"""Localization metrics: signed error, front-back / left-right confusion, binning."""
import numpy as np


def norm180(a):
    """Normalize to [-180, 180)."""
    return ((a + 180.0) % 360.0) - 180.0


def signed_error(target, response):
    """Shortest angular distance target->response, range [-180, 180)."""
    return norm180(response - target)


def abs_error(target, response):
    return abs(signed_error(target, response))


def _is_front(az):
    """Front hemisphere: |az| < 90 (across the interaural left-right axis)."""
    return abs(norm180(az)) < 90.0


def _is_right(az):
    """Right hemisphere: az > 0 (across the median front-back axis)."""
    return norm180(az) > 0.0


def front_back_confusion(target, response):
    """Mirror target across interaural axis (az -> 180-az); flag if response within 30 deg
    of the mirror AND response hemisphere (front/back) differs from target's.
    Targets at exactly +-90 excluded (on the axis)."""
    t = norm180(target)
    if abs(abs(t) - 90.0) < 1e-6:
        return False
    mirror = norm180(180.0 - t)
    near_mirror = abs(signed_error(mirror, response)) <= 30.0
    hemi_flip = _is_front(response) != _is_front(t)
    return bool(near_mirror and hemi_flip)


def left_right_confusion(target, response):
    """Response and target on opposite left/right hemispheres. Targets at 0 and 180 excluded."""
    t = norm180(target)
    if abs(t) < 1e-6 or abs(abs(t) - 180.0) < 1e-6:
        return False
    return bool(_is_right(response) != _is_right(t))


def bin_az(az, step=30.0):
    """Bin an azimuth to the nearest grid multiple of `step`, returned in [-180, 180)."""
    return norm180(round(norm180(az) / step) * step)


def grid_azimuths(step=30.0):
    """Ordered list of target azimuths on the grid, [-180, 180)."""
    n = int(round(360.0 / step))
    return [norm180(i * step) for i in range(n)]


def _selfcheck():
    # Signed error shortest arc.
    assert signed_error(170, -170) == 20.0, signed_error(170, -170)
    assert signed_error(-170, 170) == -20.0
    assert signed_error(0, 90) == 90.0
    assert abs_error(170, -170) == 20.0

    # Front-back: target 30 (front-right), mirror = 150 (back-right). Response 150 -> confusion.
    assert front_back_confusion(30, 150) is True
    assert front_back_confusion(30, 155) is True     # within 30 of 150, back hemi
    assert front_back_confusion(30, 35) is False     # correct-ish, same hemi
    # Excluded at +-90.
    assert front_back_confusion(90, 90) is False
    # Mirror near but same hemisphere shouldn't flag: target 60 front, mirror 120 back;
    # response 60 is front -> no flip -> False.
    assert front_back_confusion(60, 60) is False

    # Left-right: target +30 (right), response -30 (left) -> confusion.
    assert left_right_confusion(30, -30) is True
    assert left_right_confusion(30, 30) is False
    assert left_right_confusion(0, 90) is False      # target 0 excluded
    assert left_right_confusion(180, -90) is False   # target 180 excluded

    # Binning.
    assert bin_az(7, 30) == 0.0
    assert bin_az(22, 30) == 30.0
    assert bin_az(175, 30) == -180.0 or bin_az(175, 30) == 180.0
    assert len(grid_azimuths(30)) == 12
    assert len(grid_azimuths(15)) == 24

    print("metrics.py selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
