# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import datetime
from typing import TYPE_CHECKING, Any, cast

from django import template
from django.template.context import RequestContext
from django.template.loader import render_to_string

from openadrgui.utils import dt_to_local_tz, dt_to_utc

if TYPE_CHECKING:
    from django.http import HttpRequest

register = template.Library()


class NestedObject:
    """A simple object that allows setting nested attributes via dot notation."""

    def __init__(self, object_str_field: str, **kwargs: object) -> None:
        """Initialize the object."""
        self.object_str_field = object_str_field
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __str__(self) -> str:
        """Return the string representation of the object."""
        return str(getattr(self, self.object_str_field))


@register.simple_tag
def create_object(object_str_field: str, **kwargs: object) -> NestedObject:
    """
    Creates an object with nested properties that can be accessed via dot notation.

    Usage: {% create_object tags="error" message="Something went wrong" as my_message %}
    Then you can use: {{ my_message.tags }} and {{ my_message }}
    """
    return NestedObject(object_str_field, **kwargs)


@register.filter
def get_dict_item(dictionary: dict[str, Any], key: str) -> Any:  # noqa: ANN401
    """Like dict.get(key) but as a template filter."""
    return dictionary.get(key)


@register.filter
def add_time(datetime_obj: datetime.datetime, time_obj: datetime.timedelta) -> datetime.datetime:
    """
    Add a time to a datetime object, properly handling timezone transitions like DST.

    When a datetime spans DST transitions, we need to ensure the timezone rules are applied.
    """
    # Use Django's timezone utilities to ensure proper DST handling

    # First convert to UTC
    utc_datetime = dt_to_utc(datetime_obj)
    # Apply the timedelta in UTC (where there's no DST)
    utc_result = utc_datetime + time_obj
    # Convert to our timezone
    return dt_to_local_tz(utc_result)


@register.simple_tag(takes_context=True)
def render_partial_with_context(
    context: RequestContext,
    template_name: str,
    context_dict: dict[str, Any],
    **kwargs: object,
) -> str:
    """
    Renders any template with unpacked context dictionary and additional kwargs.

    Usage: {% render_partial_with_context "partials/programs-partial.html" context_var_name other_kwarg="other_value" %}
    """
    flattened = cast("dict[str, Any]", context.flatten())
    merged_context: dict[str, Any] = {
        **flattened,
        **context_dict,
        **kwargs,
    }

    request = cast("HttpRequest | None", context.get("request"))
    return render_to_string(template_name, merged_context, request=request)
