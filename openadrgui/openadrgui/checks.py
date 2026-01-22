# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

# Checker does not work unless I leave the app_config argument in. Allow print statement to be like the System checker.
# ruff: noqa: ANN401, ARG001, T201
# From: https://www.ralphminderhoud.com/blog/django-mypy-check-runs/
import re
from typing import Any

from django.conf import settings
from django.core.checks import register
from django.core.checks.messages import DEBUG, ERROR, INFO, WARNING, CheckMessage
from mypy import api


# The check framework is used for multiple different kinds of checks. As such, errors
# and warnings can originate from models or other django objects. The `CheckMessage`
# requires an object as the source of the message and so we create a temporary object
# that simply displays the file and line number from mypy (i.e. "location")
class MyPyErrorLocation:
    """Temporary object to display the file and line number from mypy."""

    def __init__(self, location: str) -> None:
        """Initialize the MyPyErrorLocation object."""
        self.location = location

    def __str__(self) -> str:
        """Return the location as a string."""
        return self.location


# Example: myproject/checks.py:17: error: Need type annotation for 'errors'
PATTERN = re.compile(r"^(.+\d+): (\w+): (.+)")


@register()
def mypy(app_configs: Any, **_kwargs: Any) -> list[CheckMessage]:
    """Perform mypy checks and crash if there are any errors."""
    print("Performing mypy checks...")

    # By default run mypy against the whole database everytime checks are performed.
    # If performance is an issue then `app_configs` can be inspected and the scope
    # of the mypy check can be restricted
    mypy_args = [str(settings.BASE_DIR)]
    results = api.run(mypy_args)
    error_messages = results[0]

    if not error_messages:
        return []

    errors = []
    for error_line in error_messages.rstrip().split("\n"):
        parsed = re.match(PATTERN, error_line)
        if not parsed:
            continue

        location = parsed.group(1)
        mypy_level = parsed.group(2)
        message = parsed.group(3)

        level = DEBUG
        if mypy_level == "note":
            level = INFO
        elif mypy_level == "warning":
            level = WARNING
        elif mypy_level == "error":
            level = ERROR
        else:
            print("Unrecognized mypy level: %s", mypy_level)

        errors.append(CheckMessage(level, message, obj=MyPyErrorLocation(location)))

    return errors
