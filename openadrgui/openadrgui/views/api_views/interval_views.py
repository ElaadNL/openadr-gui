# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import logging
from datetime import datetime
from typing import Any

from django.contrib import messages
from django.http import HttpRequest
from django.urls import reverse
from django.utils.functional import cached_property
from lockmgr.lockmgr import Locked, LockMgr
from openadr3_client.bl._client import BusinessLogicClient
from openadr3_client.models.common.interval import Interval as VtnInterval
from openadr3_client.models.event.event import EventUpdate, ExistingEvent
from openadr3_client.models.event.event_payload import EventPayload, EventPayloadDescriptor

from openadrgui.forms.forms import FilterIntervalsForm
from openadrgui.models.djangomodels import ProgramDeploymentsModel
from openadrgui.models.models import NormalizedInterval, ValidatedEvent
from openadrgui.request_utils import RequestType, get_bl_client, request_succeeded, request_to_messages
from openadrgui.services.services import (
    intervals_to_vtn_intervals,
)
from openadrgui.types import HtmxHttpRequest
from openadrgui.views import intervals as intervals_views
from openadrgui.views.api_views.event_views import get_program_breadcrumb_base
from openadrgui.views.types import PayloadTab

logger = logging.getLogger(__name__)

# API Configuration
API_INTERVAL_CONFIG = intervals_views.IntervalViewConfig(
    intervals_url_name="intervals-payload",
    program_id_key="program_id",
    url_prefix="",
)


def _save_event(
    request: HtmxHttpRequest | HttpRequest,
    client: BusinessLogicClient,
    event_id: str,
    intervals: tuple[VtnInterval[EventPayload[Any]], ...] | None,
    payload_descriptors: tuple[EventPayloadDescriptor, ...],
) -> None:
    """Save updated event via API."""
    try:
        with LockMgr("bl_operations", expires=10):
            result = request_to_messages(
                request,
                lambda: client.events.get_event_by_id(event_id),
                request_type=RequestType.READ,
                auto_lock=False,
            )
            if not request_succeeded(result):
                msg = "Event not found"
                raise ValueError(msg)
            event, _ = result

            if intervals is None:
                msg = "Intervals cannot be None"
                raise ValueError(msg)

            _, success = request_to_messages(
                request,
                lambda: client.events.update_event_by_id(
                    event_id,
                    event.update(
                        EventUpdate(intervals=intervals, payload_descriptors=payload_descriptors, interval_period=None)
                    ),
                ),
                request_type=RequestType.UPDATE,
                auto_lock=False,
            )
            if not success:
                msg = "Failed to update event"
                raise ValueError(msg)
    except Locked:
        logger.exception("BL client is locked")
        messages.error(request, "Somebody else is already using the VTN. Please try again in a few seconds.")
        return


class IntervalsView(intervals_views.BaseIntervalsView):
    """Class-based intervals view using mixins to enable breadcrumbs."""

    @cached_property
    def client(self) -> BusinessLogicClient:
        """
        Lazily create the BL client.

        This must not run at import/class-definition time because Django imports URLconfs and view modules during
        management commands (e.g. `migrate`) as part of system checks.
        """
        return get_bl_client()

    config = API_INTERVAL_CONFIG

    def get_event(self, event_id: str) -> ExistingEvent | None:
        """Get event by ID from API."""
        obj, success = request_to_messages(
            self.request, lambda: self.client.events.get_event_by_id(event_id), request_type=RequestType.READ
        )
        if not success:
            return None
        return obj

    def save_event(
        self,
        intervals: tuple[VtnInterval[EventPayload[Any]], ...] | None,
        payload_descriptors: tuple[EventPayloadDescriptor, ...],
        event_id: str,
    ) -> None:
        """Save updated event via API."""
        _save_event(
            self.request,
            self.client,
            event_id,
            intervals,
            payload_descriptors,
        )

    def get_context_data(  # type: ignore[override]
        self,
        event: ValidatedEvent | ExistingEvent | None,
        payload: PayloadTab,
        form: FilterIntervalsForm | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> dict[str, Any]:
        """Override to optimize breadcrumb generation by reusing event data."""
        deployed_program_names = set(
            ProgramDeploymentsModel.objects.select_related("program").values_list("program__program_name", flat=True)
        )

        program_id = self.kwargs["program_id"]
        result = request_to_messages(
            self.request,
            lambda: self.client.programs.get_program_by_id(program_id),
            request_type=RequestType.READ,
        )
        if request_succeeded(result):
            program, _ = result
            program_is_deployed = program.name in deployed_program_names
            program_name = program.name
        else:
            program_is_deployed = False
            program_name = None

        # Build breadcrumbs with event if provided to avoid extra API call
        if event is not None:
            program_id = str(self.kwargs["program_id"])
            base_crumbs = get_program_breadcrumb_base(self.request, program_id)
            event_name = getattr(event, "name", None) or getattr(event, "event_name", None) or "Unknown Event"
            self._breadcrumbs = [
                *base_crumbs,
                (f"Events - {event_name}", reverse("events", kwargs={"id": program_id})),
                ("Intervals", None),
            ]
        return super().get_context_data(
            event=event,
            payload=payload,
            form=form,
            start=start,
            end=end,
            program_is_deployed=program_is_deployed,
            program_name=program_name,
            **kwargs,
        )

    @cached_property
    def crumbs(self) -> list[tuple[str, str | None]]:
        """Breadcrumbs property - uses cached breadcrumbs if available."""
        if hasattr(self, "_breadcrumbs"):
            return self._breadcrumbs
        # Fallback: fetch event from API if breadcrumbs not cached
        program_id = str(self.kwargs["program_id"])
        base_crumbs = get_program_breadcrumb_base(self.request, program_id)
        result = request_to_messages(
            self.request,
            lambda: self.client.events.get_event_by_id(self.kwargs["id"]),
            request_type=RequestType.READ,
        )
        if not request_succeeded(result):
            return [*base_crumbs, ("Events", reverse("events", kwargs={"id": program_id})), ("Intervals", None)]
        event, _ = result
        event_name = event.name or "Unknown Event"
        return [
            *base_crumbs,
            (f"Events - {event_name}", reverse("events", kwargs={"id": program_id})),
            ("Intervals", None),
        ]


class GenerateIntervalCurveView(intervals_views.BaseGenerateIntervalCurveView):
    """Generate curve data based on form parameters. POST only endpoint."""

    @cached_property
    def client(self) -> BusinessLogicClient:
        """
        Lazily create the BL client.

        This must not run at import/class-definition time because Django imports URLconfs and view modules during
        management commands (e.g. `migrate`) as part of system checks.
        """
        return get_bl_client()

    config = API_INTERVAL_CONFIG

    def get_event(self, event_id: str) -> ExistingEvent | None:
        """Get event by ID from API."""
        result = request_to_messages(
            self.request,
            lambda: self.client.events.get_event_by_id(event_id),
            request_type=RequestType.READ,
        )
        if not request_succeeded(result):
            return None
        event, _ = result
        return event

    def save_event(
        self,
        event: ValidatedEvent | ExistingEvent,
        intervals: tuple[NormalizedInterval, ...],
    ) -> ExistingEvent:
        """Save event with updated intervals via API."""
        if not isinstance(event, ExistingEvent):
            msg = "Expected ExistingEvent for API interval update"
            raise TypeError(msg)
        # Convert back to VTN format for API update
        vtn_intervals = intervals_to_vtn_intervals(intervals)

        updated_event = event.update(
            EventUpdate(
                intervals=vtn_intervals,
                interval_period=None,
            )
        )

        result = request_to_messages(
            self.request,
            lambda: self.client.events.update_event_by_id(str(event.id), updated_event),
            request_type=RequestType.UPDATE,
        )
        if not request_succeeded(result):
            # Base view will keep rendering based on the pre-save event; errors are shown via messages.
            return event
        saved_event, _ = result
        return saved_event


class PayloadDescriptorView(intervals_views.BasePayloadDescriptorView):
    """Edit a signal."""

    @cached_property
    def client(self) -> BusinessLogicClient:
        """
        Lazily create the BL client.

        This must not run at import/class-definition time because Django imports URLconfs and view modules during
        management commands (e.g. `migrate`) as part of system checks.
        """
        return get_bl_client()

    config = API_INTERVAL_CONFIG

    def get_event(self, event_id: str) -> ExistingEvent | None:
        """Get event by ID from API."""
        obj, success = request_to_messages(
            self.request, lambda: self.client.events.get_event_by_id(event_id), request_type=RequestType.READ
        )
        if not success:
            return None
        return obj

    def save_event(
        self,
        intervals: tuple[VtnInterval[EventPayload[Any]], ...] | None,
        payload_descriptors: tuple[EventPayloadDescriptor, ...],
        event_id: str,
    ) -> None:
        """Save updated event via API."""
        _save_event(self.request, self.client, event_id, intervals, payload_descriptors)


class ImportCsvView(intervals_views.BaseImportCsvView):
    """Import a CSV file."""

    @cached_property
    def client(self) -> BusinessLogicClient:
        """
        Lazily create the BL client.

        This must not run at import/class-definition time because Django imports URLconfs and view modules during
        management commands (e.g. `migrate`) as part of system checks.
        """
        return get_bl_client()

    config = API_INTERVAL_CONFIG

    def get_event(self, event_id: str) -> ExistingEvent | None:
        """Get event by ID from API."""
        result = request_to_messages(
            self.request,
            lambda: self.client.events.get_event_by_id(str(event_id)),
            request_type=RequestType.READ,
        )
        if not request_succeeded(result):
            return None
        event, _ = result
        return event

    def save_event(
        self,
        event: ValidatedEvent | ExistingEvent,
        intervals: tuple[NormalizedInterval, ...],
    ) -> ExistingEvent:
        """Save event with updated intervals via API."""
        if not isinstance(event, ExistingEvent):
            msg = "Expected ExistingEvent for API interval update"
            raise TypeError(msg)
        # Convert back to VTN format for API update
        vtn_intervals = intervals_to_vtn_intervals(intervals)

        updated_event = event.update(
            EventUpdate(
                interval_period=None,
                intervals=vtn_intervals,
            )
        )
        result = request_to_messages(
            self.request,
            lambda: self.client.events.update_event_by_id(str(event.id), updated_event),
            request_type=RequestType.UPDATE,
        )
        if not request_succeeded(result):
            return event
        saved_event, _ = result
        return saved_event
