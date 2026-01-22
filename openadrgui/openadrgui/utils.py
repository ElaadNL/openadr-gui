# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import datetime
import logging
import zoneinfo
from collections.abc import Callable
from http import HTTPStatus
from typing import Any, overload

import pycountry
from django.contrib import messages
from django.db import DatabaseError, IntegrityError
from django.forms import BaseForm
from django.http import HttpResponse, HttpResponseRedirect
from django.utils import timezone

from openadrgui.types import HtmxHttpRequest

logger = logging.getLogger(__name__)


def htmx_redirect(request: HtmxHttpRequest, url: str) -> HttpResponse:
    """HTMX redirect."""
    if request.htmx:
        # Put messages in session.
        # HtmxBoostedMiddleware will take them out and add them to the response after the redirect.
        msgs = messages.get_messages(request)
        if msgs:
            request.session["messages"] = []
            for msg in msgs:
                request.session["messages"].append((msg.level, msg.message))
        response = HttpResponse(status=HTTPStatus.OK)
        response.headers["HX-Location"] = url
        return response
    return HttpResponseRedirect(url)


def snake_case_to_title(string: str) -> str:
    """Convert a snake case string to a title case string."""
    return string.replace("_", " ").title()


# From: https://stackoverflow.com/a/6037657
def unflatten(dictionary: dict[str, Any], separator: str = ".") -> dict[str, Any]:
    """
    Unflatten a dictionary with a separator.

    E.g. {'a.b.c': 1} -> {'a': {'b': {'c': 1}}}

    Args:
        dictionary: The dictionary to unflatten.
        separator: The separator to use.

    Returns:
        The unflattened dictionary.

    """
    result_dict: dict[str, Any] = {}
    for key, value in dictionary.items():
        parts = key.split(separator)
        d: dict[str, Any] = result_dict
        for part in parts[:-1]:
            if part not in d:
                d[part] = {}
            d = d[part]
        d[parts[-1]] = value
    return result_dict


def flatten(dictionary: dict[str, Any], parent_key: str = "", separator: str = "__") -> dict[str, Any]:
    """
    Flatten a nested dictionary with a separator.

    E.g. {'a': {'b': {'c': 1}}} -> {'a__b__c': 1}

    Args:
        dictionary: The dictionary to flatten.
        parent_key: The base key for the current level of recursion.
        separator: The separator to use between keys.

    Returns:
        The flattened dictionary.

    """
    items = {}
    for key, value in dictionary.items():
        new_key = f"{parent_key}{separator}{key}" if parent_key else key
        if isinstance(value, dict):
            items.update(flatten(value, new_key, separator=separator))
        else:
            items[new_key] = value
    return items


# From: https://web.archive.org/web/20180425063617/https://schinckel.net/2015/10/29/unicode-flags-in-python/

OFFSET = ord("🇦") - ord("A")


def emoji_flag(code: str) -> str:
    """Returns a flag emoji for a given ISO 3166-1 alpha-2 country code, E.G US."""
    return chr(ord(code[0]) + OFFSET) + chr(ord(code[1]) + OFFSET)


def get_country_display_string(
    country_code: str | None, subdivision_code: str | None = None
) -> tuple[str | None, str | None, str | None]:
    """
    Get flag emoji and full name for a country and optional subdivision.

    Args:
        country_code: ISO 3166-1 alpha-2 country code
        subdivision_code: Optional ISO 3166-2 subdivision code

    Returns:
        Tuple of (flag, subdivision_name)
        - flag: Flag emoji or country code if no emoji available
        - subdivision_name: Full name of subdivision or the subdivision code if no subdivision is provided

    """
    if country_code is None:
        return (None, None, None)
    try:
        # Convert country code to regional indicator symbols
        flag = emoji_flag(country_code)
        country = pycountry.countries.get(alpha_2=country_code)
        country_name = country.name if country is not None else country_code
        if subdivision_code:
            try:
                subdivision = pycountry.subdivisions.get(  # type: ignore[no-untyped-call]
                    code=f"{country_code}-{subdivision_code}"
                )
                subdivision_name = subdivision.name
            except (LookupError, AttributeError):
                logger.exception("Error getting subdivision for %s-%s", country_code, subdivision_code)
                return (flag, country_name, subdivision_code)
            else:
                return (flag, country_name, subdivision_name)
        else:
            return (flag, country_name, subdivision_code)

    except (LookupError, AttributeError):
        return (None, country_code, subdivision_code)


def populate_flags(programs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Populate flag, country_long_name, and subdivision_long_name fields for a list of programs.

    Args:
        programs: List of program dictionaries or objects to enhance with flag information

    Returns:
        List of enhanced program dictionaries with flag information

    """
    formatted_programs = []
    for program in programs:
        # Add country display information
        country_info = get_country_display_string(program.get("country"), program.get("principal_subdivision")) or [
            "",
            "",
            "",
        ]

        formatted_program = {
            **program,
            **dict(
                zip(
                    ["flag", "country_long_name", "subdivision_long_name"],
                    country_info,
                    strict=True,
                )
            ),
        }
        formatted_programs.append(formatted_program)

    return formatted_programs


# Default database error messages
DEFAULT_ERROR_MESSAGES: dict[str, str] = {
    "unique_constraint_failed": "An entity with this name already exists.",
    "database_error": "An error occurred while saving the instance.",
}


def db_call_to_form_errors[T](
    form: BaseForm,
    user_identifier_field_name: str | None,
    db_method: Callable[[], T],
    error_messages: dict[str, str] | None = None,
) -> T | None:
    """
    Handle an API request and add errors to a Django form.

    Args:
        form: Django form to add errors to
        user_identifier_field_name: Name of the field that is used to identify the entity
        db_method: Callable that executes the request and returns type T
        error_messages: Partial error messages to override defaults (optional)

    Returns:
        T | None: model object if successful, None if errors occurred

    """
    # Merge defaults with user overrides
    final_messages: dict[str, str] = {**DEFAULT_ERROR_MESSAGES, **(error_messages or {})}
    try:
        return db_method()
    except IntegrityError as e:
        logger.exception("Error creating model")
        if "UNIQUE constraint failed" in str(e) or "unique constraint" in str(e).lower():
            form.add_error(user_identifier_field_name, final_messages["unique_constraint_failed"])
        else:
            # Convert model errors to form errors
            logger.exception("Error creating model")
            form.add_error(None, final_messages["database_error"])
        return None
    except DatabaseError:
        # Convert model errors to form errors
        logger.exception("Error creating model")
        form.add_error(None, final_messages["database_error"])
        return None


@overload
def dt_to_utc(datetime_obj: datetime.datetime) -> datetime.datetime: ...


@overload
def dt_to_utc(datetime_obj: None) -> None: ...


def dt_to_utc(datetime_obj: datetime.datetime | None) -> datetime.datetime | None:
    """Convert a datetime object to UTC."""
    if datetime_obj is None:
        return None
    return datetime_obj.astimezone(zoneinfo.ZoneInfo("UTC"))


@overload
def dt_to_local_tz(datetime_obj: datetime.datetime) -> datetime.datetime: ...


@overload
def dt_to_local_tz(datetime_obj: None) -> None: ...


def dt_to_local_tz(datetime_obj: datetime.datetime | None) -> datetime.datetime | None:
    """Convert a datetime object to the local timezone."""
    if datetime_obj is None:
        return None
    return datetime_obj.astimezone(zoneinfo.ZoneInfo(timezone.get_current_timezone_name()))
