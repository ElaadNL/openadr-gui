# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

"""Forms for the OpenADR GUI application."""

import logging
from typing import Any

import pycountry
from django import forms
from django.core.validators import FileExtensionValidator, URLValidator
from django.utils.safestring import mark_safe
from openadr3_client.models.common.unit import Unit
from openadr3_client.models.event.event_payload import EventPayloadType

from openadrgui.forms.validators import MaxSizeValidator
from openadrgui.models.djangomodels import DjangoEventModel, DjangoProgramModel, DjangoResourceModel
from openadrgui.models.models import TargetType

from .fields import ChoiceField, ChoiceWithCustomField, DateRangeField, DateTimeRangeField, FloatField
from .mixins import (
    CountryMixin,
    DaisyUIFormMixin,
    DjangoModelFormMixin,
    IntervalPeriodMixin,
    SubdivisionsMixin,
)

logger = logging.getLogger(__name__)


class SubdivisionsForm(DaisyUIFormMixin, SubdivisionsMixin):
    """Form for subdivision selection with DaisyUI styling."""


ID_FIELD = forms.CharField(required=False, help_text="VTN-generated ID", widget=forms.HiddenInput())


class VenForm(DaisyUIFormMixin, forms.Form):
    """Form for creating and updating VEN connections."""

    ven_name = forms.CharField(
        min_length=1,
        max_length=128,
        required=True,
        help_text="Unique identifier for the VEN",
    )


class ResourceForm(DaisyUIFormMixin, forms.Form):
    """Form for creating and updating resources."""

    resource_name = forms.CharField(
        min_length=1,
        max_length=128,
        required=True,
        help_text="Unique identifier for the resource",
    )


class DjangoResourceForm(DjangoModelFormMixin[DjangoResourceModel], ResourceForm):
    """Form for creating and updating resources."""

    model_class = DjangoResourceModel


class ProgramForm(DaisyUIFormMixin, IntervalPeriodMixin, CountryMixin, forms.Form):
    """Form for creating and updating programs."""

    field_order = (
        "program_name",
        "program_long_name",
        "retailer_name",
        "retailer_long_name",
        "program_type",
        *CountryMixin.field_order,
        *IntervalPeriodMixin.field_order,
        "program_descriptions",
        "binding_events",
        "local_price",
    )

    program_name = forms.CharField(
        min_length=1,
        max_length=128,
        required=True,
        help_text="Unique identifier for the program",
        empty_value=None,
    )

    program_long_name = forms.CharField(
        required=False,
        help_text="Long name of program for human readability.",
        empty_value=None,
    )

    retailer_name = forms.CharField(
        required=False, help_text="Short name of energy retailer providing the program.", empty_value=None
    )

    retailer_long_name = forms.CharField(
        required=False, help_text="Long name of energy retailer for human readability.", empty_value=None
    )

    program_type = forms.CharField(required=False, help_text="A program defined categorization.", empty_value=None)

    program_descriptions_help_text = (
        "Enter valid URLs, seperated by commas. URLs have to include the protocol (http or https)."
    )

    program_descriptions = forms.CharField(
        required=False, widget=forms.Textarea, help_text=program_descriptions_help_text
    )

    binding_events = forms.BooleanField(required=False, help_text="True if events are fixed once transmitted.")

    local_price = forms.BooleanField(required=False, help_text="True if events have been adapted from a grid event.")

    # PayloadDescriptors and targets should be handled in seperate put forms.

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        # Call the parent constructor
        super().__init__(*args, **kwargs)

        # Convert the list of dictionaries to a comma-separated string
        if "initial" in kwargs and "program_descriptions" in kwargs["initial"]:
            urls = kwargs["initial"]["program_descriptions"]
            if isinstance(urls, list | tuple):
                # Extract URLs from the list of dictionaries
                urls = tuple(str(url_dict["url"]) for url_dict in urls)
                # Join them into a comma-separated string
                self.initial["program_descriptions"] = ", ".join(urls)

    def clean_program_descriptions(self) -> tuple[dict[str, str], ...] | None:
        """Convert newline-separated URLs into a tuple and validate each URL."""
        urls = self.cleaned_data["program_descriptions"].strip().split(",")
        urls = [url.strip() for url in urls if url.strip()]
        if not urls:
            return None
        validator = URLValidator(
            schemes=["http", "https"],
            message="Please enter valid URLs.",
        )
        for url in urls:
            validator(url)
        return tuple({"url": url} for url in urls)


class DjangoProgramForm(DjangoModelFormMixin[DjangoProgramModel], ProgramForm):
    """Form for creating and updating programs."""

    model_class = DjangoProgramModel


class EventForm(DaisyUIFormMixin, IntervalPeriodMixin, forms.Form):
    """Form for creating and updating events."""

    field_order = (
        "program_id",
        "program_name",
        "event_name",
        "priority",
        *IntervalPeriodMixin.field_order,
    )

    event_name = forms.CharField(
        required=True,
        help_text="Unique identifier for the event",
    )

    priority = forms.IntegerField(
        required=False,
        help_text="Priority of the event",
        initial=None,
    )

    # NOTE: Targets is missing, not clear enough yet what it is.
    # NOTE: Report Descriptors to be added seperately
    # NOTE: Payload Descriptors to be added seperately
    # NOTE: Intervals to be added seperately


class TargetForm(DaisyUIFormMixin, forms.Form):
    """Form for creating and updating targets. Used as a formset with the BaseEventForm."""

    # Custom values for targets will not be supported, since they will be deprecated in OpenADR 3.1
    type = ChoiceField(
        choices=[(None, "No target")] + [(e.name, e.value) for e in TargetType],
        required=True,
        help_text="The type of target.",
    )
    value = forms.CharField(required=True, help_text="The value of the target.")


class DjangoEventForm(DjangoModelFormMixin[DjangoEventModel], EventForm):
    """Form for creating and updating events."""

    model_class = DjangoEventModel


class GenerateCurveForm(DaisyUIFormMixin, forms.Form):
    """Form for generating curve data."""

    min_limit = forms.IntegerField(
        required=True,
        help_text="Minimum limit for the curve",
        min_value=0,
        initial=0,
    )

    max_limit = forms.IntegerField(
        required=True,
        help_text="Maximum limit for the curve",
        min_value=1,
        initial=100,
    )

    noise = FloatField(
        required=True,
        help_text="Amount of random noise to add (0-1)",
        min_value=0,
        max_value=1,
        initial=0.5,
    )

    range = DateRangeField(
        required=True,
        help_text=(
            "The range of dates to generate the curve for. The start and end dates are inclusive. "
            "You may select one day or multiple days."
        ),
    )


class FilterIntervalsForm(DaisyUIFormMixin, forms.Form):
    """Form for filtering intervals."""

    disabled: bool
    filter = DateTimeRangeField(required=False, empty_message="No filter")


TOP_CURRENCIES = ("USD", "EUR", "JPY", "GBP", "AUD", "CAD", "CHF", "CNY", "HKD", "SEK", "MXN")


class PayloadDescriptorForm(DaisyUIFormMixin, forms.Form):
    """Form for creating and updating payload descriptors."""

    payload_type = ChoiceWithCustomField(
        required=True,
        choices=[
            (None, "Select a payload descriptor"),
            (ChoiceWithCustomField.CUSTOM, "Custom payload type"),
            *[(pt.value, pt.value) for pt in EventPayloadType],
        ],
        help_text="The type of payload values.",
    )
    units = ChoiceWithCustomField(
        required=False,
        choices=[
            (None, "No unit"),
            (ChoiceWithCustomField.CUSTOM, "Custom unit"),
            *[(unit.value, unit.value) for unit in Unit],
        ],
        help_text="The unit used in the payload values.",
    )
    currency = ChoiceField(
        choices=[(None, "No currency")]
        + [(currency, f"({currency}) {pycountry.currencies.get(alpha_3=currency).name}") for currency in TOP_CURRENCIES]
        + [ChoiceField.SEPARATOR]
        + [
            (currency.alpha_3, f"({currency.alpha_3}) {currency.name}")
            for currency in pycountry.currencies
            if currency.alpha_3 not in TOP_CURRENCIES
        ],
        required=False,
        help_text="(optional) The currency used in the payload values.",
    )


class ImportCSVForm(DaisyUIFormMixin, forms.Form):
    """Form for importing a CSV file."""

    file = forms.FileField(
        required=True,
        allow_empty_file=False,
        validators=[
            FileExtensionValidator(allowed_extensions=["csv"]),
            # 150MB should allow for ~1 million intervals
            MaxSizeValidator(150),
        ],
        help_text=mark_safe(  # nosec:B308
            """CSV structure (comma separated values):<br />
                1. interval start (ISO 8601 with timezone offset)<br />
                2. interval end (ISO 8601 with timezone offset)<br />
                3. payload value (float)<br />
                Example:<br />
                2024-01-01T00:00:00Z,2024-01-01T01:00:00Z,100<br />
                2024-01-01T01:00:00Z,2024-01-01T02:00:00Z,200<br />
                No headers, just the data.<br />
                Maximum file size is 150MB. Should allow for ~1 million intervals.
                """
        ),
    )


class ScheduleDeploymentForm(DaisyUIFormMixin, forms.Form):
    """Form for scheduling a deployment of a program."""

    repeat = forms.BooleanField(
        required=False,
        label="Enable weekly deployments",
        help_text=(
            "When you enable this function, "
            "the program will be deployed every week on a wednesday at 13:00 Amsterdam time. "
            "It allows you to use a static program with OpenADR. "
            "You can check the deployment status in the task view."
        ),
    )
