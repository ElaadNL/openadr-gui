# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import re
from collections.abc import Callable

import pycountry
from django.forms import ValidationError

DURATION_PATTERN = re.compile(
    r"^(-?)P(?=\d|T\d)(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)([DW]))?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?$"
)


def as_form_validator[T](validator: Callable[[T], T]) -> Callable[[T], T]:
    """Convert a validator function to a form validator function."""

    def form_validator(value: T) -> T:
        try:
            return validator(value)
        except Exception as e:
            raise ValidationError(str(e)) from e

    return form_validator


def country_validator(value: str) -> str:
    """
    Check whether a string is a valid country code as defined by ISO 3166-1.

    Validates country codes according to ISO 3166-1 alpha-2 format.

    Args:
        value (str): The country code in ISO 3166-1 alpha-2 format (e.g., 'US')

    Returns:
        str: The validated country code

    Raises:
        ValueError: If the country code is not a valid ISO 3166-1 alpha-2 code

    Examples:
        >>> country_validator('US')
        'US'

    """
    if pycountry.countries.get(alpha_2=value) is None:
        msg = "Invalid ISO 3166-1 alpha-2 format"
        raise ValueError(msg)
    return value


def principal_subdivision_validator(country: str, value: str) -> str:
    """
    Check whether a string is a valid principal subdivision for a country.

    Validates subdivision codes according to ISO 3166-2 format. The subdivision code
    should not contain the country prefix.

    Args:
        country (str): The country code in ISO 3166-1 alpha-2 format (e.g., 'US')
        value (str): The subdivision code without country prefix (e.g., 'CO')

    Returns:
        str: The validated subdivision code

    Raises:
        ValueError: If the subdivision code is not valid for the given country

    Examples:
        >>> principal_subdivision_validator('US', 'CO')
        'CO'

    """
    country = country_validator(country)
    full_subdivision_code = f"{country}-{value}"
    if pycountry.subdivisions.get(code=full_subdivision_code) is None:  # type: ignore[no-untyped-call]
        msg = "Invalid ISO 3166-2 alpha-2 format"
        raise ValueError(msg)
    return value
