# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

"""
Base view classes for interval management.

This module provides base classes that eliminate code duplication between
API and DP interval views while preserving existing functionality including
HTMX integration, form handling, and error management.

This replaces the functionality previously in generic_views.py with a more
structured approach using inheritance.
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from http import HTTPStatus
from typing import Any, TypeGuard

from django.contrib import messages
from django.core.files.uploadedfile import UploadedFile
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views import View
from openadr3_client.models.event.event import ExistingEvent
from openadr3_client.models.event.event_payload import EventPayloadDescriptor, EventPayloadType
from pydantic import ValidationError
from view_breadcrumbs import BaseBreadcrumbMixin

from openadrgui.forms.forms import (
    FilterIntervalsForm,
    GenerateCurveForm,
    ImportCSVForm,
    PayloadDescriptorForm,
)
from openadrgui.interval_generators import generate_curve
from openadrgui.models.models import NormalizedInterval, SinglePayloadInterval, ValidatedEvent
from openadrgui.services.delete_intervals import delete_intervals, delete_payload_descriptor
from openadrgui.services.merge_intervals import IntervalPeriodConflictError, merge_intervals
from openadrgui.services.services import (
    GraphIntervals,
    curve_to_intervals,
    get_min_max_local_date,
    intervals_from_csv,
    intervals_to_graph,
    normalize_intervals,
    to_normalized_intervals,
    to_single_payload_intervals,
    update_intervals_list,
    update_payload_descriptors_list,
)
from openadrgui.types import CopyableInterval, HtmxHttpRequest
from openadrgui.utils import htmx_redirect, snake_case_to_title
from openadrgui.views.base_views import ContextMixin
from openadrgui.views.types import NewEmptyTabs, PayloadTab, TabInfo

logger = logging.getLogger(__name__)


@dataclass
class IntervalViewConfig:
    """Configuration for interval views."""

    # URL configuration
    intervals_url_name: str  # "intervals-payload" or "dp-intervals-payload"
    program_id_key: str  # "program_id" or "dp_id"
    url_prefix: str  # "" or "dp-"


def resolve_payload_tab(event: ValidatedEvent | ExistingEvent, payload_type: str | None) -> tuple[PayloadTab, bool]:
    """
    Resolve the payload tab from the payload_type parameter.

    Returns:
        The resolved payload type,
        and a bool indicating if the payload type was found in the event's payload descriptors

    """
    payload_descriptors = event.payload_descriptors or ()
    if len(payload_descriptors) == 0:
        return NewEmptyTabs.EMPTY, True

    if payload_type is None:
        return payload_descriptors[0].payload_type, True

    if payload_type in (NewEmptyTabs.ADD, NewEmptyTabs.EMPTY):
        return NewEmptyTabs(payload_type), True

    return resolve_payload_type(payload_descriptors, payload_type)


def resolve_payload_type(
    payload_descriptors: tuple[EventPayloadDescriptor, ...],
    payload_type: str | None,
) -> tuple[EventPayloadType, bool]:
    """Resolve the payload type from the payload_type parameter."""
    # Convert string payload_type to EventPayloadType enum if needed
    if payload_type is None:
        return payload_descriptors[0].payload_type, False

    if isinstance(payload_type, str):
        try:
            payload_type_enum = EventPayloadType(payload_type)
        except ValueError:
            logger.warning("%s is not part of the default payload types, making it custom", payload_type)
            EventPayloadType._missing_(payload_type)
            return EventPayloadType(payload_type), True
    else:
        payload_type_enum = payload_type

    # Check if the payload type exists in the event's payload descriptors
    if not any(descriptor.payload_type == payload_type_enum for descriptor in payload_descriptors):
        logger.warning("Payload type %s not found, defaulting to first payload descriptor", payload_type_enum.value)
        return payload_descriptors[0].payload_type, False
    return payload_type_enum, True


def is_event_payload_type(payload: PayloadTab) -> TypeGuard[EventPayloadType]:
    """Type guard to check if payload is EventPayloadType."""
    return isinstance(payload, EventPayloadType)


def is_new_empty_tabs(payload: PayloadTab) -> TypeGuard[NewEmptyTabs]:
    """Type guard to check if payload is NewEmptyTabs."""
    return isinstance(payload, NewEmptyTabs)


def get_payloaddescriptor(
    event: ValidatedEvent | ExistingEvent, payload_type: EventPayloadType | PayloadTab
) -> EventPayloadDescriptor | None:
    """
    Get the payload descriptor for the given payload type.

    Returns:
        The payload descriptor, or None if not found or for special tabs

    """
    # Handle special tab types
    if is_new_empty_tabs(payload_type):
        return None

    if not event.payload_descriptors:
        return None

    for descriptor in event.payload_descriptors:
        if descriptor.payload_type == payload_type:
            return descriptor

    return None


def get_tabs_menu(event: ValidatedEvent | ExistingEvent, current_payload_type: PayloadTab) -> list[TabInfo]:
    """Get list of available tabs for the event."""
    tabs: list[TabInfo] = []

    if not event.payload_descriptors or len(event.payload_descriptors) == 0:
        tabs.append(
            {
                "type": NewEmptyTabs.EMPTY,
                "active": current_payload_type == NewEmptyTabs.EMPTY,
                "display_name": "No Payload",
            }
        )
    else:
        # Add tabs for existing payload descriptors
        tabs.extend(
            [
                {
                    "type": descriptor.payload_type,
                    "active": current_payload_type == descriptor.payload_type,
                    "display_name": (
                        snake_case_to_title(descriptor.payload_type)
                        + (f" ({snake_case_to_title(descriptor.units.value)})" if descriptor.units else "")
                    ),
                }
                for descriptor in event.payload_descriptors
            ]
        )

    # Add "Add Payload" tab
    tabs.append(
        {
            "type": NewEmptyTabs.ADD,
            "active": current_payload_type == NewEmptyTabs.ADD,
            "display_name": "Add new payload",
        }
    )

    return tabs


def get_payload_descriptor_form(payload_descriptor: EventPayloadDescriptor | None) -> PayloadDescriptorForm:
    """Add form to context."""
    if not payload_descriptor:
        return PayloadDescriptorForm()

    return PayloadDescriptorForm(
        initial={
            "payload_type": payload_descriptor.payload_type.value,
            "units": payload_descriptor.units.value if payload_descriptor.units else None,
            "currency": str(payload_descriptor.currency) if payload_descriptor.currency else None,
        }
    )


def get_filter_intervals_form(
    intervals: tuple[SinglePayloadInterval, ...] | None,
    form: FilterIntervalsForm | None = None,
) -> FilterIntervalsForm:
    """Get the filter intervals form."""
    if form is None:
        form = FilterIntervalsForm()
    if intervals is None or len(intervals) == 0:
        form.fields["filter"].widget.attrs["disabled"] = True
        form.disabled = True
        return form
    (min_date, max_date) = get_min_max_local_date(intervals)
    if min_date is not None:
        form.fields["filter"].widget.attrs["min-date"] = min_date.strftime("%Y-%m-%d")
    if max_date is not None:
        form.fields["filter"].widget.attrs["max-date"] = max_date.strftime("%Y-%m-%d")
    return form


# Base Classes
class BaseIntervalViewMixin:
    """Base mixin for interval views that provides config-based methods."""

    config: IntervalViewConfig
    request: HttpRequest
    kwargs: dict[str, Any]

    def get_success_url(self) -> str:
        """Get success URL for redirects."""
        return reverse(
            self.config.intervals_url_name,
            kwargs={
                self.config.program_id_key: self.kwargs[self.config.program_id_key],
                "id": self.kwargs["id"],
                "payload_type": self.kwargs.get("payload_type", NewEmptyTabs.ADD),
            },
        )

    def get_intervals_base_context(
        self,
        event: ValidatedEvent | ExistingEvent,
        payload_type: PayloadTab,
    ) -> dict[str, Any]:
        """Get the complete context for the intervals view including tabs."""
        program_id = self.kwargs.get(self.config.program_id_key)
        available_tabs = get_tabs_menu(event, payload_type)

        return {
            "program_id": program_id,
            "id": event.id,
            "payload_empty": event.payload_descriptors is None or len(event.payload_descriptors) == 0,
            "url_prefix": self.config.url_prefix,
            "current_payload_type": payload_type.value,
            "current_payload_type_display_name": snake_case_to_title(payload_type.value),
            "available_tabs": available_tabs,
        }


class BaseIntervalsView(BaseIntervalViewMixin, BaseBreadcrumbMixin, ContextMixin, View, ABC):
    """Base class for intervals view with common GET logic."""

    template = "openadrgui/intervals.html"
    filter_template = "partials/intervals-filter-form-partial.html"

    def get_context_data(  # type: ignore[override]
        self,
        event: ValidatedEvent | ExistingEvent | None,
        payload: PayloadTab,
        form: FilterIntervalsForm | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        **kwargs: Any,  # noqa: ANN401
    ) -> dict[str, Any]:
        """Get the complete context data shared between filter and normal intervals views."""
        if event is None:
            msg = "event is required"
            raise ValueError(msg)

        base_context = self.get_intervals_base_context(event, payload)
        super_context = super().get_context_data(event=event, **kwargs)

        context = {
            **base_context,
            **super_context,
            "generate_curve_form": GenerateCurveForm(),
            "import_csv_form": ImportCSVForm(),
        }

        if payload == NewEmptyTabs.ADD:
            return {**context, "payload_descriptor_form": PayloadDescriptorForm()}

        try:
            normalized_intervals = (
                normalize_intervals(event.interval_period, event.intervals) if event.intervals else ()
            )

            graph_result: GraphIntervals = {"data": [], "is_decimated": False}
            intervals: tuple[SinglePayloadInterval, ...]
            if payload == NewEmptyTabs.EMPTY:
                intervals = ()
            else:
                if not is_event_payload_type(payload):
                    intervals = ()
                else:
                    intervals = (
                        to_single_payload_intervals(normalized_intervals, payload) if normalized_intervals else ()
                    )

                if start is not None and end is not None:
                    intervals = tuple(
                        interval for interval in intervals if start <= interval.interval_period.start <= end
                    )

                graph_result = intervals_to_graph(intervals) if intervals else {"data": [], "is_decimated": False}

            return {
                **context,
                "payload_descriptor_form": get_payload_descriptor_form(get_payloaddescriptor(event, payload)),
                "filter_intervals_form": get_filter_intervals_form(intervals, form),
                "graph_data": json.dumps(graph_result),
                "payload_empty": (event.payload_descriptors is None or len(event.payload_descriptors) == 0),
            }
        except ValueError:
            logger.exception("Payload type not found in intervals.", extra={"event": event.id, "payload": payload})
            graph_result = {"data": [], "is_decimated": False}
            intervals = ()

            return {
                **context,
                "payload_descriptor_form": get_payload_descriptor_form(get_payloaddescriptor(event, payload)),
                "filter_intervals_form": get_filter_intervals_form(intervals),
                "graph_data": json.dumps(graph_result),
                "payload_empty": (event.payload_descriptors is None or len(event.payload_descriptors) == 0),
            }

    def get(self, request: HtmxHttpRequest, **kwargs: Any) -> HttpResponse:  # noqa: ANN401
        """Handle GET request for intervals view."""
        event = self.get_event(kwargs["id"])
        if event is None:
            return htmx_redirect(request, self.get_success_url())

        # Determine the default payload type to redirect to
        payload, found = resolve_payload_tab(event, kwargs.get("payload_type"))

        if not found:
            # The requested payload type doesn't exist on the event anymore (e.g. user edited the descriptor type).
            # Redirect to the resolved payload tab to avoid redirect loops (HTMX uses HX-Location with HTTP 200).
            requested_payload_type = kwargs.get("payload_type")
            logger.warning(
                "Payload type %s not found, redirecting to %s",
                requested_payload_type,
                payload.value,
                extra={"event": event.id, "requested_payload_type": requested_payload_type, "payload": payload},
            )
            messages.warning(request, "Payload type not found; showing available payload.")
            url = reverse(
                self.config.intervals_url_name,
                kwargs={
                    self.config.program_id_key: kwargs[self.config.program_id_key],
                    "id": kwargs["id"],
                    "payload_type": payload.value,
                },
            )
            return htmx_redirect(request, url)

        if len(request.GET) > 0:
            return self.filter_intervals(request, event, payload, **kwargs)
        return self.intervals_index(request, event, payload, **kwargs)

    def intervals_index(
        self,
        request: HtmxHttpRequest,
        event: ValidatedEvent | ExistingEvent,
        payload: PayloadTab,
        **kwargs: Any,  # noqa: ANN401
    ) -> HttpResponse:
        """Index view."""
        context = self.get_context_data(event=event, payload=payload, **kwargs)
        return render(request, self.template, context)

    def filter_intervals(
        self,
        request: HtmxHttpRequest,
        event: ValidatedEvent | ExistingEvent,
        payload: PayloadTab,
        **kwargs: Any,  # noqa: ANN401
    ) -> HttpResponse:
        """Filter intervals based on form parameters."""
        form = FilterIntervalsForm(request.GET)

        if not form.is_valid():
            logger.error("Form validation errors: %s", form.errors)

            return render(
                request,
                self.filter_template,
                context=self.get_context_data(event=event, payload=payload, **kwargs),
                status=HTTPStatus.UNPROCESSABLE_CONTENT,
            )

        start: datetime = form.cleaned_data["filter"]["start"]
        end: datetime = form.cleaned_data["filter"]["end"]

        context = self.get_context_data(event=event, payload=payload, form=form, start=start, end=end, **kwargs)
        if payload == NewEmptyTabs.EMPTY:
            messages.error(request, "Cannot filter intervals without a payload descriptor.")
            return render(request, self.filter_template, context=context)

        if request.htmx:
            response = render(request, self.filter_template, context=context)
            if start is None and end is None:
                # If the form is valid but filters on nothing, push the 'clean' url instead of an empty query url.
                response.headers["HX-Push-Url"] = request.path
            else:
                # Push the filter url to the browser history.
                # Setting hx-push-url also pushes the url when there is an error.
                response.headers["HX-Push-Url"] = request.get_full_path()

            response.headers["HX-Trigger-After-Settle"] = "chart:refresh"
            return response
        return render(request, "openadrgui/intervals.html", context)

    def delete(self, request: HtmxHttpRequest, **kwargs: Any) -> HttpResponse:  # noqa: ANN401
        """Handle DELETE request for deleting a payload descriptor."""
        event = self.get_event(kwargs["id"])
        if event is None:
            return htmx_redirect(request, self.get_success_url())
        payload, found = resolve_payload_tab(event, kwargs.get("payload_type"))
        url = reverse(
            self.config.intervals_url_name,
            kwargs={
                self.config.program_id_key: kwargs[self.config.program_id_key],
                "id": kwargs["id"],
                "payload_type": payload.value,
            },
        )
        if not found:
            logger.error("Invalid payload type.", extra={"event": event.id, "payload": payload})
            messages.error(request, "Invalid payload type.")
            return htmx_redirect(request, url)

        if is_new_empty_tabs(payload):
            logger.error("Cannot delete payload descriptor.", extra={"event": event.id, "payload": payload})
            messages.error(request, "Cannot delete payload descriptor.")
            return htmx_redirect(request, url)

        if not is_event_payload_type(payload):
            logger.error("Cannot delete payload descriptor.", extra={"event": event.id, "payload": payload})
            messages.error(request, "Cannot delete payload descriptor.")
            return htmx_redirect(request, url)

        try:
            intervals = delete_intervals(event.intervals, payload)
            payload_descriptors = delete_payload_descriptor(event.payload_descriptors, payload)
        except ValueError:
            logger.exception("Cannot delete payload descriptor.", extra={"event": event.id, "payload": payload})
            messages.error(request, "Cannot delete payload descriptor.")
            return htmx_redirect(request, url)

        self.save_event(intervals, payload_descriptors, str(event.id))

        messages.success(request, "Payload descriptor deleted successfully.")

        # After deletion, redirect to the first remaining payload descriptor or empty tab
        updated_event = self.get_event(kwargs["id"])
        if updated_event is None:
            messages.error(request, "Event not found.")
            return htmx_redirect(request, self.get_success_url())
        redirect_payload, _ = resolve_payload_tab(updated_event, None)

        url = reverse(
            self.config.intervals_url_name,
            kwargs={
                self.config.program_id_key: kwargs[self.config.program_id_key],
                "id": kwargs["id"],
                "payload_type": redirect_payload.value,
            },
        )

        return htmx_redirect(request, url)

    @abstractmethod
    def get_event(self, event_id: str) -> ValidatedEvent | ExistingEvent | None:
        """Get event by ID. Implementation differs between API and DP."""

    @abstractmethod
    def save_event(
        self,
        intervals: tuple[Any, ...] | None,
        payload_descriptors: tuple[EventPayloadDescriptor, ...],
        event_id: str,
    ) -> None:
        """Save updated event."""


class BaseGenerateIntervalCurveView(BaseIntervalViewMixin, View, ABC):
    """Base class for generating interval curves."""

    template = "partials/intervals-generate-curve-refresh-partial.html"

    def post(self, request: HtmxHttpRequest, **kwargs: Any) -> HttpResponse:  # noqa: ANN401
        """Handle POST request for generating interval curves."""
        form = GenerateCurveForm(request.POST)

        event = self.get_event(kwargs["id"])
        if event is None:
            return htmx_redirect(request, self.get_success_url())
        payload, found = resolve_payload_tab(event, kwargs.get("payload_type"))
        if not found:
            requested_payload_type = kwargs.get("payload_type")
            logger.warning(
                "Payload type %s not found, redirecting to %s",
                requested_payload_type,
                payload.value,
                extra={"event": event.id, "requested_payload_type": requested_payload_type, "payload": payload},
            )
            messages.warning(request, "Payload type not found; showing available payload.")
            url = reverse(
                self.config.intervals_url_name,
                kwargs={
                    self.config.program_id_key: kwargs[self.config.program_id_key],
                    "id": kwargs["id"],
                    "payload_type": payload.value,
                },
            )
            return htmx_redirect(request, url)
        context = self.get_intervals_base_context(event, payload)

        context = {
            **context,
            "generate_curve_form": form,
        }

        if not form.is_valid():
            logger.error("Form validation errors: %s", form.errors)
            # Get current intervals for form context
            if event.intervals:
                if is_event_payload_type(payload):
                    current_intervals = to_single_payload_intervals(
                        normalize_intervals(event.interval_period, event.intervals),
                        payload,
                    )
                else:
                    current_intervals = ()
            else:
                current_intervals = ()
            context = {
                **context,
                "filter_intervals_form": get_filter_intervals_form(current_intervals),
            }

            return render(
                request,
                self.template,
                context,
                status=HTTPStatus.UNPROCESSABLE_CONTENT,
            )

        min_limit: int = form.cleaned_data["min_limit"]
        max_limit: int = form.cleaned_data["max_limit"]
        noise: float = form.cleaned_data["noise"]

        start: date = form.cleaned_data["range"]["start"]
        end: date = form.cleaned_data["range"]["end"]

        if not payload or not is_event_payload_type(payload) or not event.payload_descriptors:
            logger.error(
                "Cannot generate curve without a payload descriptor.", extra={"event": event.id, "payload": payload}
            )
            messages.error(request, "Cannot generate curve without a payload descriptor.")
            return render(
                request,
                self.template,
                context,
                status=HTTPStatus.UNPROCESSABLE_CONTENT,
            )

        curve_data = generate_curve(
            min_limit=min_limit,
            max_limit=max_limit,
            noise=noise,
            n_days=(end - start).days + 1,
        )
        new_intervals = curve_to_intervals(
            start,
            payload,
            curve_data,
        )

        # Merge with existing intervals, checking for conflicts
        try:
            if event.intervals:
                existing_intervals = normalize_intervals(event.interval_period, event.intervals)
                all_intervals = merge_intervals(existing_intervals, new_intervals)
            else:
                all_intervals = to_normalized_intervals(new_intervals)
        except IntervalPeriodConflictError:
            logger.exception("Cannot merge intervals.", extra={"event": event.id, "payload": payload})
            messages.error(request, "Cannot merge intervals")
            return render(
                request,
                self.template,
                context,
                status=HTTPStatus.UNPROCESSABLE_CONTENT,
            )

        self.save_event(event, all_intervals)

        filtered_intervals = to_single_payload_intervals(all_intervals, payload)
        context["filter_intervals_form"] = get_filter_intervals_form(filtered_intervals)

        graph_result = intervals_to_graph(filtered_intervals)
        context["graph_data"] = json.dumps(graph_result)
        context["payload_empty"] = False

        messages.success(request, "Curve generated successfully.")
        response = render(request, self.template, context)

        # Remove any filter query params (filter params) from the request, since they may now be invalid
        response.headers["HX-Push-Url"] = request.path
        response.headers["HX-Trigger-After-Settle"] = "chart:refresh"

        return response

    @abstractmethod
    def get_event(self, event_id: str) -> ValidatedEvent | ExistingEvent | None:
        """Get event by ID."""

    @abstractmethod
    def save_event(
        self,
        event: ValidatedEvent | ExistingEvent,
        intervals: tuple[NormalizedInterval, ...],
    ) -> ValidatedEvent | ExistingEvent:
        """Save updated event."""


class BasePayloadDescriptorView(BaseIntervalViewMixin, View, ABC):
    """Base class for payload descriptor management."""

    template = "partials/intervals-payload-descriptor-form-partial.html"

    def post(self, request: HtmxHttpRequest, **kwargs: Any) -> HttpResponse:  # noqa: ANN401
        """Handle POST request for editing payload descriptors."""
        form = PayloadDescriptorForm(request.POST)
        event = self.get_event(kwargs["id"])
        if event is None:
            return render(request, self.template, {"payload_descriptor_form": form}, status=HTTPStatus.NOT_FOUND)
        payload, found = resolve_payload_tab(event, kwargs.get("payload_type"))

        context = {
            **self.get_intervals_base_context(event, payload),
            "payload_descriptor_form": form,
        }

        if not found:
            logger.error("Internal server error: Invalid payload type.", extra={"event": event.id, "payload": payload})
            messages.error(request, "Internal server error: Invalid payload type.")
            return render(
                request,
                self.template,
                context,
                status=HTTPStatus.UNPROCESSABLE_CONTENT,
            )

        if not form.is_valid():
            logger.error("Form validation errors: %s", form.errors)
            return render(
                request,
                self.template,
                context,
                status=HTTPStatus.UNPROCESSABLE_CONTENT,
            )

        descriptor_model = EventPayloadDescriptor.model_validate(form.cleaned_data)

        existing_types = {descriptor.payload_type for descriptor in event.payload_descriptors or ()}
        # When editing an existing descriptor, re-submitting the current payload type is valid.
        # Only reject when:
        # - adding a new descriptor and the type already exists, or
        # - editing and changing the type to another already-existing type.
        if is_event_payload_type(payload):
            is_duplicate = descriptor_model.payload_type != payload and descriptor_model.payload_type in existing_types
        else:
            is_duplicate = descriptor_model.payload_type in existing_types
        if is_duplicate:
            form.add_error("payload_type", "Payload descriptor already exists.")
            return render(
                request,
                self.template,
                context,
                status=HTTPStatus.UNPROCESSABLE_CONTENT,
            )

        updated_intervals, updated_descriptors = self.update_payload_descriptor(event, payload, descriptor_model)

        # Save the updated event
        try:
            self.save_event(updated_intervals, updated_descriptors, str(event.id))
        except ValueError:
            logger.exception("Cannot save event.", extra={"event": event.id, "payload": payload})
            messages.error(request, "Cannot save event.")
            return render(
                request,
                self.template,
                context,
                status=HTTPStatus.UNPROCESSABLE_CONTENT,
            )

        messages.success(request, "Payload descriptor updated successfully.")

        # Always redirect to the (possibly updated) payload type.
        # This prevents redirecting back to an old URL when the payload type changed.
        url = reverse(
            self.config.intervals_url_name,
            kwargs={
                self.config.program_id_key: kwargs[self.config.program_id_key],
                "id": kwargs["id"],
                "payload_type": descriptor_model.payload_type.value,
            },
        )

        return htmx_redirect(request, url)

    @abstractmethod
    def get_event(self, event_id: str) -> ValidatedEvent | ExistingEvent | None:
        """Get event by ID."""

    @abstractmethod
    def save_event(
        self,
        intervals: tuple[Any, ...] | None,
        payload_descriptors: tuple[EventPayloadDescriptor, ...],
        event_id: str,
    ) -> None:
        """Save updated event."""

    def update_payload_descriptor(
        self,
        event: ValidatedEvent | ExistingEvent,
        current_payload: PayloadTab,
        new_descriptor: EventPayloadDescriptor,
    ) -> tuple[tuple[CopyableInterval, ...] | None, tuple[EventPayloadDescriptor, ...]]:
        """Generic payload descriptor update logic."""
        payload_descriptors = event.payload_descriptors or ()
        if current_payload == NewEmptyTabs.ADD:
            updated_descriptors = (
                *payload_descriptors,
                new_descriptor,
            )
            return event.intervals, updated_descriptors

        if current_payload == NewEmptyTabs.EMPTY:
            updated_descriptors = (new_descriptor,)
            return event.intervals, updated_descriptors

        if not is_event_payload_type(current_payload):
            msg = "Expected current_payload to be an EventPayloadType at this point"
            raise ValueError(msg)

        updated_descriptors = update_payload_descriptors_list(payload_descriptors, current_payload, new_descriptor)
        updated_intervals = update_intervals_list(event.intervals, current_payload, new_descriptor.payload_type)

        return updated_intervals, updated_descriptors


class BaseImportCsvView(BaseIntervalViewMixin, View, ABC):
    """Base class for CSV import functionality."""

    template = "partials/intervals-import-csv-form-partial.html"

    def post(self, request: HtmxHttpRequest, **kwargs: Any) -> HttpResponse:  # noqa: ANN401
        """Handle POST request for importing CSV files."""
        form = ImportCSVForm(request.POST, request.FILES)
        event = self.get_event(kwargs["id"])
        if event is None:
            return render(request, self.template, {"import_csv_form": form}, status=HTTPStatus.NOT_FOUND)
        payload, _ = resolve_payload_tab(event, kwargs.get("payload_type"))

        payload_type: EventPayloadType | None = payload if is_event_payload_type(payload) else None
        is_valid, validation_result = self._validate_csv_import(form, event, payload_type)
        if not is_valid:
            context = self.get_context_data(event, payload, validation_result or form)
            return render(
                request,
                self.template,
                context,
                status=HTTPStatus.UNPROCESSABLE_CONTENT,
            )

        if payload_type is None:
            form.add_error("file", "Cannot import CSV without a payload type.")
            context = self.get_context_data(event, payload, form)
            return render(request, self.template, context, status=HTTPStatus.UNPROCESSABLE_CONTENT)

        success, result = self._process_csv_intervals(form.cleaned_data["file"], event, payload_type)

        if not success:
            if isinstance(result, list):
                for error in result:
                    form.add_error("file", error)
            context = self.get_context_data(event, payload, form)
            return render(
                request,
                self.template,
                context,
                status=HTTPStatus.UNPROCESSABLE_CONTENT,
            )

        if not isinstance(result, tuple):
            msg = "Expected CSV processing to return intervals"
            raise TypeError(msg)

        self.save_event(event, result)

        updated_intervals = to_single_payload_intervals(result, payload_type)

        context = self.get_context_data(event, payload, ImportCSVForm())
        context["filter_intervals_form"] = get_filter_intervals_form(updated_intervals)
        context["graph_data"] = json.dumps(intervals_to_graph(updated_intervals))
        context["payload_empty"] = False

        messages.success(request, "CSV imported successfully.")

        response = render(request, self.template, context)

        # Remove any filter query params (filter params) from the request, since they may now be invalid
        response.headers["HX-Push-Url"] = request.path
        response.headers["HX-Trigger-After-Settle"] = "chart:refresh"

        return response

    def _validate_csv_import(
        self, form: ImportCSVForm, event: ValidatedEvent | ExistingEvent, payload: EventPayloadType | None
    ) -> tuple[bool, ImportCSVForm | None]:
        """Validate form and check all prerequisites for CSV import."""
        errors = []

        if not form.is_valid():
            return False, None

        if not payload or not is_event_payload_type(payload):
            errors.append("Cannot import CSV without a payload type.")

        if not event.payload_descriptors:
            errors.append("Cannot import CSV without a payload descriptor.")

        if errors:
            for error in errors:
                form.add_error("file", error)
            return False, form

        return True, None

    def _process_csv_intervals(
        self, file: UploadedFile, event: ValidatedEvent | ExistingEvent, payload: EventPayloadType
    ) -> tuple[bool, list[str] | tuple[NormalizedInterval, ...]]:
        """Process CSV file and merge with existing intervals. Returns (success, result_or_errors)."""
        try:
            if file.file is None:
                return False, ["No file provided."]
            new_intervals = intervals_from_csv(file.file, payload)
        except ValidationError as e:
            logger.exception("Error importing CSV")
            return False, [error["msg"] for error in e.errors()]
        except ValueError as e:
            logger.exception("Error importing CSV")
            return False, [str(e)]

        try:
            if event.intervals:
                existing_intervals = normalize_intervals(event.interval_period, event.intervals)
                all_intervals = merge_intervals(existing_intervals, new_intervals)
            else:
                all_intervals = to_normalized_intervals(new_intervals)
        except IntervalPeriodConflictError as e:
            return False, [f"Cannot merge intervals: {e}"]

        return True, all_intervals

    def get_context_data(
        self, event: ValidatedEvent | ExistingEvent, payload: PayloadTab, form: ImportCSVForm | None = None
    ) -> dict[str, Any]:
        """Set up complete context data including intervals and forms."""
        context = self.get_intervals_base_context(event, payload)

        current_intervals = self._get_current_intervals(event, payload) if is_event_payload_type(payload) else ()
        context["filter_intervals_form"] = get_filter_intervals_form(current_intervals)

        if form:
            context["import_csv_form"] = form

        return context

    def _get_current_intervals(
        self, event: ValidatedEvent | ExistingEvent, payload: EventPayloadType
    ) -> tuple[SinglePayloadInterval, ...]:
        """Get current intervals for the given event and payload."""
        if event.intervals:
            return to_single_payload_intervals(
                normalize_intervals(event.interval_period, event.intervals),
                payload,
            )
        return ()

    @abstractmethod
    def get_event(self, event_id: str) -> ValidatedEvent | ExistingEvent | None:
        """Get event by ID."""

    @abstractmethod
    def save_event(
        self, event: ValidatedEvent | ExistingEvent, intervals: tuple[NormalizedInterval, ...]
    ) -> ValidatedEvent | ExistingEvent:
        """Save event with updated intervals."""
