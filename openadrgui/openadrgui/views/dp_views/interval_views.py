# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import logging
from datetime import datetime
from typing import Any

from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.functional import cached_property
from openadr3_client.models.common.interval import Interval as VtnInterval
from openadr3_client.models.event.event import ExistingEvent
from openadr3_client.models.event.event_payload import EventPayload, EventPayloadDescriptor

from openadrgui.forms.forms import FilterIntervalsForm
from openadrgui.models.djangomodels import DjangoEventModel
from openadrgui.models.models import NormalizedInterval, ValidatedEvent
from openadrgui.views import intervals as intervals_views
from openadrgui.views.dp_views.event_views import get_program_breadcrumb_base
from openadrgui.views.types import PayloadTab

logger = logging.getLogger(__name__)

# DP Configuration
DP_INTERVAL_CONFIG = intervals_views.IntervalViewConfig(
    intervals_url_name="dp-intervals-payload",
    program_id_key="dp_id",
    url_prefix="dp-",
)


def _save_event(
    intervals: tuple[VtnInterval[EventPayload[Any]], ...] | None,
    payload_descriptors: tuple[EventPayloadDescriptor, ...],
    event_id: str,
) -> None:
    """Save updated event via Django model."""
    django_event = get_object_or_404(DjangoEventModel, id=event_id)
    django_event.payload_descriptors = [payload_descriptor.model_dump() for payload_descriptor in payload_descriptors]
    if intervals is not None:
        django_event.intervals = [interval.model_dump() for interval in intervals]
    django_event.save()


class IntervalsView(intervals_views.BaseIntervalsView):
    """Class-based intervals view using mixins."""

    config = DP_INTERVAL_CONFIG

    def get_event(self, event_id: str) -> ValidatedEvent:
        """Get event by ID from Django model."""
        event = get_object_or_404(DjangoEventModel, id=event_id)
        return ValidatedEvent.from_django_event_model(event)

    def save_event(
        self,
        intervals: tuple[VtnInterval[EventPayload[Any]], ...] | None,
        payload_descriptors: tuple[EventPayloadDescriptor, ...],
        event_id: str,
    ) -> None:
        """Save updated event via Django model."""
        _save_event(intervals, payload_descriptors, event_id)

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
        # Build breadcrumbs with event if provided to avoid extra DB query
        if event is not None:
            program_id = self.kwargs["dp_id"]
            base_crumbs = get_program_breadcrumb_base(program_id)
            self._breadcrumbs = [
                *base_crumbs,
                (f"Events - {event.event_name}", reverse("dp-events", kwargs={"id": program_id})),
                ("Intervals", None),
            ]
        return super().get_context_data(event=event, payload=payload, form=form, start=start, end=end, **kwargs)

    @cached_property
    def crumbs(self) -> list[tuple[str, str | None]]:
        """Breadcrumbs property - uses cached breadcrumbs if available."""
        if hasattr(self, "_breadcrumbs"):
            return self._breadcrumbs
        # Fallback: fetch event from DB if breadcrumbs not cached
        program_id = self.kwargs["dp_id"]
        base_crumbs = get_program_breadcrumb_base(program_id)
        event_name = DjangoEventModel.objects.get(id=self.kwargs["id"]).event_name
        return [
            *base_crumbs,
            (f"Events - {event_name}", reverse("dp-events", kwargs={"id": program_id})),
            ("Intervals", None),
        ]


class GenerateIntervalCurveView(intervals_views.BaseGenerateIntervalCurveView):
    """Generate curve data based on form parameters. POST only endpoint."""

    config = DP_INTERVAL_CONFIG

    def get_event(self, event_id: str) -> ValidatedEvent:
        """Get event by ID from Django model."""
        event = get_object_or_404(DjangoEventModel, id=event_id)
        return ValidatedEvent.from_django_event_model(event)

    def save_event(
        self, event: ValidatedEvent | ExistingEvent, intervals: tuple[NormalizedInterval, ...]
    ) -> ValidatedEvent | ExistingEvent:
        """Save event with updated intervals via Django model."""
        # Get the Django model instance
        django_event = get_object_or_404(DjangoEventModel, id=event.id)
        django_event.interval_period = None
        django_event.intervals = [interval.model_dump() for interval in intervals]
        django_event.save()

        return ValidatedEvent.from_django_event_model(django_event)


class PayloadDescriptorView(intervals_views.BasePayloadDescriptorView):
    """Edit a signal."""

    config = DP_INTERVAL_CONFIG

    def get_event(self, event_id: str) -> ValidatedEvent:
        """Get event by ID from Django model."""
        event = get_object_or_404(DjangoEventModel, id=event_id)
        return ValidatedEvent.from_django_event_model(event)

    def save_event(
        self,
        intervals: tuple[VtnInterval[EventPayload[Any]], ...] | None,
        payload_descriptors: tuple[EventPayloadDescriptor, ...],
        event_id: str,
    ) -> None:
        """Save updated event via Django model."""
        _save_event(intervals, payload_descriptors, event_id)


class ImportCsvView(intervals_views.BaseImportCsvView):
    """Import a CSV file."""

    config = DP_INTERVAL_CONFIG

    def get_event(self, event_id: str) -> ValidatedEvent:
        """Get event by ID from Django model."""
        event = get_object_or_404(DjangoEventModel, id=event_id)
        return ValidatedEvent.from_django_event_model(event)

    def save_event(
        self, event: ValidatedEvent | ExistingEvent, intervals: tuple[NormalizedInterval, ...]
    ) -> ValidatedEvent | ExistingEvent:
        """Save event with updated intervals via Django model."""
        # Get the Django model instance
        django_event = get_object_or_404(DjangoEventModel, id=event.id)
        django_event.interval_period = None
        django_event.intervals = [interval.model_dump() for interval in intervals]
        django_event.save()

        return ValidatedEvent.from_django_event_model(django_event)
