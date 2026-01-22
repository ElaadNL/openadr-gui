# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import datetime
import logging
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, cast

import pycountry
from django import forms
from django.db import models
from django.forms import ValidationError
from django.forms.models import model_to_dict

from openadrgui.forms.fields import (
    ChoiceField,
    CountryField,
    DateTimeRangeField,
    DurationField,
    Select,
)
from openadrgui.utils import dt_to_local_tz, dt_to_utc, unflatten

logger = logging.getLogger(__name__)


class DaisyUIFormMixin:
    """Mixin to map Django form fields to DaisyUI/Tailwind classes."""

    field_classes: Mapping[type[forms.Widget], str] = MappingProxyType(
        {
            forms.Textarea: "textarea w-full",
            forms.Select: "select w-full",
            forms.CheckboxInput: "toggle",
            forms.CheckboxSelectMultiple: "checkbox",
            forms.ClearableFileInput: "file-input w-full",
            forms.FileInput: "file-input w-full",
        }
    )

    default_classes = "input w-full"
    fields: dict[str, Any]

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Initialize the form with DaisyUI classes."""
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            widget_class = self.field_classes.get(type(widget), self.default_classes)
            if widget_class:
                existing_classes = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing_classes} {widget_class}".strip()


class DjangoModelFormMixin[DjangoModelT: models.Model]:
    """Mixin to make forms work with Django's CreateView/UpdateView pattern."""

    model_class: type[DjangoModelT]
    cleaned_data: dict[str, Any]
    instance: DjangoModelT | None

    @property
    def _objects(self) -> models.Manager[DjangoModelT]:
        """Typed access to the model manager (single typing escape hatch)."""
        return cast("models.Manager[DjangoModelT]", cast("Any", self.model_class).objects)

    def __init__(self, *args: Any, instance: DjangoModelT | None = None, **kwargs: Any) -> None:  # noqa: ANN401
        """Initialize the form."""
        if not hasattr(self.model_class, "name"):
            msg = "model_class must have a name property"
            raise ValueError(msg)

        if not hasattr(self.model_class, "user_identifier_field_name"):
            msg = "model_class must have a user_identifier_field_name property"
            raise ValueError(msg)

        # Store instance for Django's UpdateView pattern
        self.instance = instance

        # Convert instance to initial data for form population
        if self.instance is not None:
            initial = model_to_dict(self.instance)
            # Handle Django's foreign key _id_id naming convention
            for field_name in list(initial.keys()):
                if field_name.endswith("_id_id"):
                    value = initial.pop(field_name)
                    new_name = field_name.replace("_id_id", "_id")
                    initial[new_name] = value
            kwargs["initial"] = initial

        super().__init__(*args, **kwargs)

    def save(self, *, commit: bool = True) -> DjangoModelT:
        """Save method to work with Django's CreateView/UpdateView."""
        # Convert form fields back to Django model field naming
        for field_name in list(self.cleaned_data.keys()):
            if field_name.endswith("_id"):
                value = self.cleaned_data.pop(field_name)
                if value:  # Only convert if value is not None/empty
                    self.cleaned_data[f"{field_name}_id"] = int(value)

        if self.instance is None:
            # Create new instance
            self.cleaned_data["id"] = None
            if commit:
                self.instance = self._objects.create(**self.cleaned_data)
            else:
                self.instance = self.model_class(**self.cleaned_data)
        elif commit:
            # Update existing instance
            self._objects.filter(pk=self.instance.pk).update(**self.cleaned_data)
            self.instance.refresh_from_db()
        else:
            for key, value in self.cleaned_data.items():
                setattr(self.instance, key, value)

        if self.instance is None:
            msg = "Form instance was not created or updated."
            raise ValueError(msg)
        return self.instance


class IntervalPeriodMixin(forms.Form):
    """Mixin to add interval period fields to a form."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        initial = kwargs.get("initial") or {}
        if "interval_period" in initial and initial["interval_period"] is not None:
            start_datetime = dt_to_utc(initial["interval_period"]["start"])
            duration = initial["interval_period"]["duration"]
            randomize_start = initial["interval_period"]["randomize_start"]
            # Remove old interval_period
            del initial["interval_period"]
            # Calculate end_datetime in utc to avoid timezone issues
            end_datetime = start_datetime + duration
            # Convert to local timezone
            start_datetime = dt_to_local_tz(start_datetime)
            end_datetime = dt_to_local_tz(end_datetime)
            # Set the new interval_period
            initial["interval_period__range"] = {
                "start": start_datetime,
                "end": end_datetime,
            }
            initial["interval_period__randomize_start"] = randomize_start

    field_order: tuple[str, ...] = (
        "interval_period__range",
        "interval_period__randomize_start",
    )

    interval_period__range = DateTimeRangeField(
        required=False,
        help_text="Start and end of the interval period.",
    )

    interval_period__randomize_start = DurationField(
        required=False,
        help_text="Randomize the duration of the interval period. Format: HH:MM:SS",
    )

    def clean_interval_period(self, interval_period: dict[str, Any]) -> dict[str, Any] | None:
        """Clean the interval period."""
        if interval_period.get("randomize_start") is datetime.timedelta(0):
            interval_period["randomize_start"] = None
        else:
            interval_period["randomize_start"] = interval_period["randomize_start"]

        if interval_period["range"]["end"] is None or interval_period["range"]["start"] is None:
            return None

        return {
            "start": interval_period["range"]["start"],
            "duration": dt_to_utc(interval_period["range"]["end"]) - dt_to_utc(interval_period["range"]["start"]),
            "randomize_start": interval_period.get("randomize_start"),
        }

    def clean(self) -> dict[str, Any]:
        """Clean the form data."""
        cleaned_data = super().clean() or {}
        cleaned_data = unflatten(cleaned_data, "__")
        interval_period = cleaned_data.get("interval_period", {})
        cleaned_data["interval_period"] = self.clean_interval_period(interval_period)
        return cleaned_data


class SubdivisionsMixin(forms.Form):
    """Form for subdivision selection with DaisyUI styling."""

    principal_subdivision = ChoiceField(
        required=False,
        help_text="Coding per ISO 3166-2. E.g. state in US.",
        initial=None,
        widget=Select(
            attrs={
                # Store the value in localStorage when set, and restore it when the page is loaded.
                "x-data": "{ storageKey() { return `select-${$el.name}` } }",
                "@change": "localStorage.setItem(storageKey(), $event.target.value)",
                "x-init": """
                () => {
                    // Only restore the value if it exists and the option is present.
                    // This way, it is set after the HTMX swap.
                    if (localStorage.getItem(storageKey()) &&
                        $el.querySelector(`option[value='${localStorage.getItem(storageKey())}']`)) {
                        $el.value = localStorage.getItem(storageKey())
                    }
                }
                """,
            }
        ),
    )


class CountryMixin(SubdivisionsMixin, forms.Form):
    """Mixin to add country and principal subdivision fields to a form."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Initialize the form and set up subdivision choices based on initial country."""
        super().__init__(*args, **kwargs)

        cast("forms.ChoiceField", self.fields["principal_subdivision"]).choices = [
            (Select.DISABLED, "Select a country first")
        ]

        # Update subdivision choices based on initial data or instance
        initial_country = None
        if self.initial.get("country"):
            initial_country = self.initial["country"]

        if initial_country:
            self.update_subdivision_choices(initial_country)

    field_order: tuple[str, ...] = (
        "country",
        "principal_subdivision",
    )

    country = CountryField(
        required=False,
        help_text="Select a country.",
        initial="Select a country",
        top_countries={"BE", "FR", "DE", "NL", "UK"},
    )

    def update_subdivision_choices(self, country: str | None) -> None:
        """Update the choices for principal_subdivision based on country."""
        if not country:
            choices = [(Select.DISABLED, "Select a country first")]
        else:
            subdivisions = pycountry.subdivisions.get(country_code=country)  # type: ignore[no-untyped-call]
            if subdivisions:
                choices = [(Select.DISABLED, "Select a subdivision"), ("", "No subdivision")] + [
                    (s.code, s.name) for s in subdivisions
                ]
            else:
                choices = [("", "This country has no subdivisions")]
        cast("forms.ChoiceField", self.fields["principal_subdivision"]).choices = choices

    def clean_country(self) -> str | None:
        """Clean the country and update subdivision choices."""
        country = self.cleaned_data.get("country")
        self.update_subdivision_choices(country)
        return country

    def clean_principal_subdivision(self) -> str | None:
        """Clean the principal subdivision."""
        country = self.cleaned_data.get("country")
        principal_subdivision: str | None = self.cleaned_data.get("principal_subdivision")

        if not principal_subdivision:
            return None

        if not country:
            msg = "Cannot specify a principal subdivision without a country."
            raise ValidationError(msg)

        # Get valid subdivisions for the country
        subdivisions = pycountry.subdivisions.get(country_code=country)  # type: ignore[no-untyped-call]
        if not subdivisions:
            msg = "This country has no subdivisions."
            raise ValidationError(msg)

        valid_codes = [s.code for s in subdivisions]
        if principal_subdivision not in valid_codes:
            msg = "Invalid subdivision for selected country."
            raise ValidationError(msg)

        # Take only the subdivision part of the code. E.g. "US-CO" -> "CO"
        return principal_subdivision.split("-", 1)[1]
