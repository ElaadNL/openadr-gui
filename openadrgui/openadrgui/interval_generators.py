# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import numpy as np
import numpy.typing as npt


def generate_curve(
    min_limit: int,
    max_limit: int,
    noise: float,
    n_days: int,
    seed: int | None = None,
) -> npt.NDArray[np.int_]:
    """
    Generate a deterministic 24-hour power capacity profile.

    Generates a deterministic 24-hour profile for Grid Aware Charging.
    Morning and evening peaks have reduced capacity. Other times have default capacity.

    Parameters
    ----------
    min_limit : int
        Minimum capacity limit
    max_limit : int
        Maximum capacity limit
    noise : float
        Amount of random noise to add (0-1)
    n_days : int
        Number of days in the curve
    seed : int | None
        Optional seed for the random number generator to make the function deterministic.
        Useful for testing.

    Returns
    -------
        numpy.ndarray: 2d array of 96 integer values * n_days (one per 15 minutes).

    """

    def generate_day_curve() -> npt.NDArray[np.int_]:
        profile = np.full(96, max_limit)  # Default base capacity in kW

        if max_limit < 0 or min_limit < 0:
            msg = "Maximum and minimum limits must be greater than 0."
            raise ValueError(msg)

        if min_limit > (max_limit // 3):
            msg = "Maximum limit must be at least 3 times the minimum limit."
            raise ValueError(msg)

        if noise < 0 or noise > 1:
            msg = "Noise must be between 0 and 1."
            raise ValueError(msg)

        # Create a random number generator
        rng = np.random.default_rng(seed)

        # Morning peak: 07:00-09:00 (intervals 28-36)
        # Calculate base value for morning peak
        morning_peak_base = ((max_limit - min_limit) * 0.70) + min_limit

        # Calculate maximum allowed noise to stay within bounds
        max_noise_morning = min(morning_peak_base - min_limit, max_limit - morning_peak_base)
        noise_amount = max_noise_morning * noise

        # Apply bounded noise
        morning_peak = morning_peak_base + rng.uniform(-noise_amount, noise_amount)

        profile[28:30] = morning_peak  # Ramp down
        profile[30:34] = 0.8 * morning_peak  # Peak
        profile[34:36] = morning_peak  # Ramp up

        # Evening peak: 17:00-21:00 (intervals 68-84)
        # Calculate base value for evening peak
        evening_peak_base = ((max_limit - min_limit) * 0.50) + min_limit

        # Calculate maximum allowed noise to stay within bounds
        max_noise_evening = min(evening_peak_base - min_limit, max_limit - evening_peak_base)
        noise_amount = max_noise_evening * noise

        # Apply bounded noise
        evening_peak_ramps = evening_peak_base + rng.uniform(-noise_amount, noise_amount)

        profile[68:73] = evening_peak_ramps  # Ramp down
        profile[73:79] = 0.8 * evening_peak_ramps  # Peak
        profile[79:84] = evening_peak_ramps  # Ramp up

        return profile

    return np.array([value for _ in range(n_days) for value in generate_day_curve()])
