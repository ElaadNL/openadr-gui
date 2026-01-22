# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

from typing import cast

import numpy as np
import pytest
from openadrgui.interval_generators import generate_curve


def test_generate_curve_basic_shape() -> None:
    """Test the basic shape of the generated curve."""
    result = generate_curve(min_limit=10, max_limit=100, noise=0, n_days=1)

    # Check array shape (1 day = 96 intervals)
    assert result.shape == (96,)

    # Check data type
    assert result.dtype == np.int_

    # Check bounds
    assert np.all(result >= 10)
    assert np.all(result <= 100)


def test_generate_curve_multiple_days() -> None:
    """Test generating curves for multiple days."""
    n_days = 3
    result = generate_curve(min_limit=10, max_limit=100, noise=0, n_days=n_days)

    # Check array shape
    assert result.shape == (96 * 3,)

    # Each day should have the same pattern when noise=0
    assert np.allclose(result[0], result[1])
    assert np.allclose(result[1], result[2])


def test_generate_curve_morning_peak() -> None:
    """Test the morning peak pattern."""
    result = generate_curve(min_limit=10, max_limit=100, noise=0, n_days=1)

    # Morning peak: 07:00-09:00 (intervals 28-36)
    morning_peak = result[28:36]

    # Check that morning peak has lower capacity than default
    assert np.all(morning_peak < 100)

    # Check peak pattern (ramp down, peak, ramp up)
    ramp_down = morning_peak[0:2]
    peak = morning_peak[2:6]
    assert np.all(ramp_down[:, np.newaxis] > peak)  # Each ramp down value should be higher than all peak values
    assert np.allclose(morning_peak[2:6], morning_peak[2])  # Peak period consistent


def test_generate_curve_evening_peak() -> None:
    """Test the evening peak pattern."""
    result = generate_curve(min_limit=10, max_limit=100, noise=0, n_days=1)

    # Evening peak: 17:00-21:00 (intervals 68-84)
    evening_peak = result[68:84]

    # Check that evening peak has lower capacity than default
    assert np.all(evening_peak < 100)

    # Check peak pattern (ramp down, peak, ramp up)
    ramp_down = evening_peak[0:5]
    peak = evening_peak[5:11]
    assert np.all(ramp_down[:, np.newaxis] > peak)  # Each ramp down value should be higher than all peak values
    assert np.allclose(evening_peak[5:11], evening_peak[5])  # Peak period consistent


@pytest.fixture(params=(0.1, 0.5, 0.9))
def noise_level(request: pytest.FixtureRequest) -> float:  # noqa: D103
    return cast("float", request.param)


# Seeds from https://www.random.org/
@pytest.fixture(params=((748, 1058), (3498, 4256)))
def seeds(request: pytest.FixtureRequest) -> tuple[int, int]:  # noqa: D103
    return cast("tuple[int, int]", request.param)


def test_generate_curve_with_noise(noise_level: float, seeds: tuple[int, int]) -> None:
    """Test that noise creates variation between days while respecting bounds."""
    result = generate_curve(min_limit=10, max_limit=100, noise=noise_level, n_days=1, seed=seeds[0])
    result2 = generate_curve(min_limit=10, max_limit=100, noise=noise_level, n_days=1, seed=seeds[1])

    # Days should be different with noise
    day1 = result[0:96]
    day2 = result2[0:96]
    assert not np.allclose(day1, day2)

    # Check global bounds
    assert np.all(result >= 10), f"Values below minimum with noise={noise_level}"
    assert np.all(result <= 100), f"Values above maximum with noise={noise_level}"


@pytest.fixture(params=(5784,))
def seed(request: pytest.FixtureRequest) -> int:  # noqa: D103
    return cast("int", request.param)


def test_generate_curve_invalid_limits(seed: int) -> None:
    """Test input validation for limits."""
    # Max limit less than 3x min limit
    with pytest.raises(ValueError, match="Maximum limit must be at least 3 times the minimum limit"):
        generate_curve(min_limit=40, max_limit=100, noise=0, n_days=1, seed=seed)

    # Negative limits
    with pytest.raises(ValueError, match="Maximum and minimum limits must be greater than 0"):
        generate_curve(min_limit=-10, max_limit=100, noise=0, n_days=1, seed=seed)

    with pytest.raises(ValueError, match="Maximum and minimum limits must be greater than 0"):
        generate_curve(min_limit=10, max_limit=-100, noise=0, n_days=1, seed=seed)


def test_generate_curve_invalid_noise(seed: int) -> None:
    """Test input validation for noise parameter."""
    # Noise below 0
    with pytest.raises(ValueError, match="Noise must be between 0 and 1"):
        generate_curve(min_limit=10, max_limit=100, noise=-0.1, n_days=1, seed=seed)

    # Noise above 1
    with pytest.raises(ValueError, match="Noise must be between 0 and 1"):
        generate_curve(min_limit=10, max_limit=100, noise=1.1, n_days=1, seed=seed)
