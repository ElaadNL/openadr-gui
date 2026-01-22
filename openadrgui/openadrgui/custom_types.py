# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

from django.http import HttpRequest


class HtmxHttpRequest(HttpRequest):
    """Htmx request object."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """Initialize the HtmxHttpRequest object."""
        super().__init__(*args, **kwargs)
        self.htmx: bool = False


class RepeatedProgramError(Exception):
    """Error deploying program task."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("Error deploying program task: " + ", ".join(errors))


class DeploymentSkippedError(Exception):
    """Deployment skipped: VTN program already contains intervals for the coming week."""

    def __init__(self, event_id: str) -> None:
        super().__init__(f"VTN event '{event_id}' already has intervals for the coming week.")


class BLClientLockError(RuntimeError):
    """Raised when BL client operations are attempted without an active lock."""
