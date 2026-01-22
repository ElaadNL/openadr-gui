# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

import datetime
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, cast

import pycountry
from django import forms
from django.forms.widgets import Select as DjangoSelect
from django.template import Context, Template
from django.template.loader import get_template
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import lazy
from django.utils.html import escape
from django.utils.safestring import SafeString

from openadrgui.utils import emoji_flag

if TYPE_CHECKING:
    from django.template.backends.django import Template as DjangoBackendTemplate


# Sets the widget to a time input for the duration field instead of text input.
class DurationField(forms.DurationField):
    """Duration field that uses a time input widget by default."""

    def __init__(self, *args: Any, widget: forms.TimeInput | None = None, **kwargs: Any) -> None:  # noqa: ANN401
        widget = widget or forms.TimeInput(
            attrs={
                "type": "time",
                # Step 1 enables users to put in seconds.
                "step": "1",
            }
        )
        super().__init__(*args, widget=widget, **kwargs)


class TimeField(forms.TimeField):
    """Time field that uses a time input widget by default."""

    def __init__(self, *args: Any, widget: forms.TimeInput | None = None, **kwargs: Any) -> None:  # noqa: ANN401
        widget = widget or forms.TimeInput(
            attrs={
                "type": "time",
                # Step 1 enables users to put in seconds.
                "step": "1",
            }
        )
        super().__init__(*args, widget=widget, **kwargs)


class Select(DjangoSelect):
    """Custom widget to render a select field with an <hr> separator and disabled options."""

    SEPARATOR_VALUE = "$SEPARATOR"
    SEPARATOR_LABEL = "None"
    DISABLED = "$DISABLED"

    def render(
        self,
        name: str,
        value: str,
        attrs: dict[str, Any] | None = None,
        renderer: Any | None = None,  # noqa: ANN401
    ) -> SafeString:
        """
        Replace the separator option with an <hr> tag.

        - The replacement is safe because we only replace a fully-escaped, constant sentinel option we control.
        - No user-controlled content is being marked safe here.
        """
        html = super().render(name, value, attrs, renderer)
        # Match the exact option that Django will have escaped already.
        sentinel = f'<option value="{escape(self.SEPARATOR_VALUE)}">{escape(self.SEPARATOR_LABEL)}</option>'
        return SafeString(str(html).replace(str(sentinel), "<hr>"))  # nosec B703

    def create_option(self, *args: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Create an option for the select field."""
        option = super().create_option(*args, **kwargs)
        if option.get("value") == self.DISABLED:
            option["attrs"]["disabled"] = ""
            option["value"] = ""
        return option


class ChoiceField(forms.ChoiceField):
    """Custom ChoiceField that supports separators in the options."""

    SEPARATOR = (Select.SEPARATOR_VALUE, Select.SEPARATOR_LABEL)
    DISABLED = Select.DISABLED

    def __init__(self, *args: Any, widget: forms.Select | None = None, **kwargs: Any) -> None:  # noqa: ANN401
        widget = widget or Select(attrs={**kwargs.get("attrs", {})})
        super().__init__(*args, widget=widget, **kwargs)

    def clean(self, value: str | None) -> Any:  # noqa: ANN401
        """Clean the value."""
        if value in (self.DISABLED, ""):
            return None
        return super().clean(value)


class FloatField(forms.FloatField):
    """
    Custom FloatField that supports both comma and dot as decimal separators.

    Uses a text input widget to allow that.
    """

    widget = forms.TextInput()

    def to_python(self, value: Any | None) -> float | None:  # type: ignore[override]  # noqa: ANN401
        """Convert comma to dot for decimal numbers during validation."""
        if value is not None and isinstance(value, str):
            value = value.replace(",", ".")
        return super().to_python(value)


class CountryField(ChoiceField):
    """Custom field for selecting a country with emoji flags and names."""

    def __init__(self, *args: Any, top_countries: set[str] | None = None, **kwargs: Any) -> None:  # noqa: ANN401
        # Generate a list of all countries with emoji flags and names
        all_countries = [
            (country.alpha_2, f"{emoji_flag(country.alpha_2)} {country.name}") for country in pycountry.countries
        ]

        # Reorder countries to have top_countries at the top
        if top_countries:
            top_choices = [country for country in all_countries if country[0] in top_countries]
            other_choices = [country for country in all_countries if country[0] not in top_countries]
            ordered_countries = [*top_choices, self.SEPARATOR, *other_choices]
        else:
            ordered_countries = all_countries

        # Create the choices list from the ordered countries
        initial_choices: list[tuple[str | None, str]] = []
        initial_choices.append((self.DISABLED, kwargs["initial"] or "Select a country"))
        if not kwargs.get("required", True):
            initial_choices.append((None, "No country"))
        ordered_countries = [*initial_choices, *ordered_countries]
        kwargs["choices"] = ordered_countries

        kwargs["widget"] = kwargs.get(
            "widget",
            Select(
                attrs={
                    # Replaces the principal_subdivision field with the subdivisions for the selected country.
                    # Also resets the principal_subdivision item in localStorage.
                    "hx-get": lazy(
                        lambda: reverse("subdivisions", kwargs={"country": "replace"}).replace("replace/", "{country}"),
                        str,
                    ),
                    "hx-trigger": "change, load",
                    "hx-target": "#id_principal_subdivision",
                    "hx-swap": "outerHTML",
                    "x-data": "",
                    "@change": "localStorage.removeItem('select-principal_subdivision')",
                }
            ),
        )

        super().__init__(*args, **kwargs)

    def clean(self, value: str | None) -> Any:  # noqa: ANN401
        """Clean the value."""
        if value in (self.DISABLED, ""):
            return None
        return super().clean(value)


class BaseRangeWidget(forms.widgets.MultiWidget):
    """Base widget for capturing start/end ranges."""

    def use_required_attribute(self, _initial: Any) -> bool:  # noqa: ANN401
        """Return False to avoid the required attribute on the widget."""
        return False

    def __init__(self, attrs: dict[str, Any] | None = None) -> None:
        self.attrs = attrs or {}
        super().__init__(self.get_widgets(), attrs)

    def get_widgets(self) -> tuple[forms.widgets.Widget, ...]:
        """Get the widgets for this range field."""
        raise NotImplementedError

    def render(
        self,
        name: str,
        value: Any,  # noqa: ANN401
        attrs: dict[str, Any] | None = None,
        renderer: Any | None = None,  # noqa: ANN401
    ) -> SafeString:
        """
        Render the widget, including the Cally calendar range component.

        Standard render does not render Cotton components.
        """
        _ = renderer
        source = cast("DjangoBackendTemplate", get_template(self.template_name)).template.source
        template = Template(source)
        context = Context(self.get_context(name, value, attrs))
        return template.render(context)


class DateTimeRangeWidget(BaseRangeWidget):
    """Widget for capturing start/end dates and times."""

    template_name = "forms/widgets/date_time_range_widget.html"

    def get_widgets(self) -> tuple[forms.widgets.Widget, ...]:
        """Get the widgets for this range field."""
        return (
            forms.widgets.HiddenInput(attrs={"class": "date-start"}),
            forms.widgets.HiddenInput(attrs={"class": "date-end"}),
            forms.widgets.TimeInput(),
            forms.widgets.TimeInput(),
        )

    def get_context(self, name: str, value: Any, attrs: dict[str, Any] | None) -> dict[str, Any]:  # noqa: ANN401
        """Get the context for this range field. Updates the names of the widgets to human readable names."""
        context = super().get_context(name, value, attrs)

        context["widget"]["subwidgets"][0]["name"] = f"{name}_start_date"
        context["widget"]["subwidgets"][1]["name"] = f"{name}_end_date"
        context["widget"]["subwidgets"][2]["name"] = f"{name}_start_time"
        context["widget"]["subwidgets"][3]["name"] = f"{name}_end_time"

        return context

    def decompress(self, value: Any) -> list[datetime.datetime | None]:  # noqa: ANN401
        """Split value into components for the four widgets."""
        if not value or not isinstance(value, dict):
            return [None, None, None, None]

        start, end = value.get("start"), value.get("end")

        # Format datetime components if they exist
        start_date = start.date().isoformat() if start else None
        end_date = end.date().isoformat() if end else None
        start_time = start.time().isoformat() if start else None
        end_time = end.time().isoformat() if end else None

        return [start_date, end_date, start_time, end_time]

    def value_from_datadict(  # type: ignore[override]
        self,
        data: Mapping[str, Any],
        _files: dict[str, Any],
        name: str,
    ) -> dict[str, datetime.datetime | None]:
        """Extract values from the submitted form data."""
        # Extract date and time values
        start_date = data.get(f"{name}_start_date")
        end_date = data.get(f"{name}_end_date")
        start_time = data.get(f"{name}_start_time")
        end_time = data.get(f"{name}_end_time")

        # If the user does not set the time, set it the end date to the next day.
        if not start_time and start_date:
            start_time = "00:00:00"
        if not end_time and end_date:
            end_date = (datetime.datetime.fromisoformat(end_date) + datetime.timedelta(days=1)).date().isoformat()
            end_time = "00:00:00"

        # Create timezone-aware datetime objects
        start = end = None
        try:
            if start_date and start_time:
                start = timezone.make_aware(datetime.datetime.fromisoformat(f"{start_date}T{start_time}"))

            if end_date and end_time:
                end = timezone.make_aware(datetime.datetime.fromisoformat(f"{end_date}T{end_time}"))
        except (ValueError, TypeError):
            # Let validation handle any errors
            pass

        return {"start": start, "end": end}


class DateRangeWidget(BaseRangeWidget):
    """
    Widget for capturing start/end dates.

    Allows for setting min and max selectable dates via the attrs parameter (min-date and max-date).
    """

    template_name = "forms/widgets/date_range_widget.html"

    def get_widgets(self) -> tuple[forms.widgets.Widget, ...]:
        """Get the widgets for this range field."""
        return (
            forms.widgets.HiddenInput(attrs={"class": "date-start"}),
            forms.widgets.HiddenInput(attrs={"class": "date-end"}),
        )

    def get_context(self, name: str, value: Any, attrs: dict[str, Any] | None) -> dict[str, Any]:  # noqa: ANN401
        """Get the context for this range field. Updates the names of the widgets to human readable names."""
        context = super().get_context(name, value, attrs)

        context["widget"]["subwidgets"][0]["name"] = f"{name}_start_date"
        context["widget"]["subwidgets"][1]["name"] = f"{name}_end_date"

        return context

    def decompress(self, value: Any) -> list[str | None]:  # noqa: ANN401
        """Split value into components for the two widgets."""
        if not value or not isinstance(value, dict):
            return [None, None]

        start, end = value.get("start"), value.get("end")

        # Format date components if they exist
        start_date = start.date().isoformat() if isinstance(start, datetime.datetime) else start
        end_date = end.date().isoformat() if isinstance(end, datetime.datetime) else end

        return [start_date, end_date]

    def value_from_datadict(  # type: ignore[override]
        self,
        data: Mapping[str, Any],
        _files: dict[str, Any],
        name: str,
    ) -> dict[str, datetime.date | None]:
        """Extract values from the submitted form data."""
        # Extract date values
        start_date = data.get(f"{name}_start_date")
        end_date = data.get(f"{name}_end_date")

        # Create date objects
        start = end = None
        try:
            if start_date:
                start = datetime.date.fromisoformat(start_date)

            if end_date:
                end = datetime.date.fromisoformat(end_date)
        except (ValueError, TypeError):
            # Let validation handle any errors
            pass

        return {"start": start, "end": end}


class BaseRangeField(forms.Field):
    """Base field for capturing start/end ranges."""

    range_error_message = "End value must be after start value"

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        self.empty_message = kwargs.pop("empty_message", None)
        super().__init__(*args, **kwargs)

    def widget_attrs(self, widget: forms.Widget) -> dict[str, Any]:
        """Add template variables to widget attributes."""
        attrs = super().widget_attrs(widget)
        attrs["empty_message"] = self.empty_message or "Pick a range"
        return attrs

    def validate(self, value: dict[str, Any]) -> None:
        """Validate the range values."""
        super().validate(value)

        start = value.get("start")
        end = value.get("end")

        if self.required and (not start or not end):
            msg = "Both start and end values are required"
            raise forms.ValidationError(msg)

        if start and end and start > end:
            raise forms.ValidationError(self.range_error_message)


class DateTimeRangeField(BaseRangeField):
    """
    A field that captures start/end dates and times.

    Type is dict with start and end keys, both of which are datetime.datetime.
    """

    widget = DateTimeRangeWidget
    range_error_message = "End date and time must be after start date and time"


class DateRangeField(BaseRangeField):
    """
    A field that captures start/end dates.

    Type is dict with start and end keys, both of which are datetime.date.
    """

    widget = DateRangeWidget
    range_error_message = "End date must be after start date"


class SelectWithCustomWidget(forms.widgets.MultiWidget):
    """Widget that combines a select dropdown with a custom text input."""

    template_name = "forms/widgets/select_with_custom_widget.html"
    CUSTOM_VALUE = "__custom__"

    def __init__(self, choices: Sequence[tuple[str | None, str]] = (), attrs: dict[str, Any] | None = None) -> None:
        self.choices: tuple[tuple[str | None, str], ...] = tuple(choices)

        widgets = (
            Select(choices=self.choices, attrs={"class": "select-dropdown"}),
            forms.widgets.TextInput(attrs={"class": "custom-input", "placeholder": "Enter custom value"}),
        )

        super().__init__(widgets, attrs)

    def get_context(self, name: str, value: Any, attrs: dict[str, Any] | None) -> dict[str, Any]:  # noqa: ANN401
        """Get the context for this widget."""
        context = super().get_context(name, value, attrs)

        context["widget"]["subwidgets"][0]["name"] = f"{name}_select"
        context["widget"]["subwidgets"][1]["name"] = f"{name}_custom"
        context["custom_value"] = self.CUSTOM_VALUE
        context["choices"] = self.choices

        return context

    def decompress(self, value: Any) -> list[str | None]:  # noqa: ANN401
        """Split value into components for the two widgets."""
        if not value:
            return [None, None]

        predefined_values = [choice[0] for choice in self.choices if choice[0] != self.CUSTOM_VALUE]

        if value in predefined_values:
            return [value, None]

        return [self.CUSTOM_VALUE, value]

    def value_from_datadict(self, data: Mapping[str, Any], _files: dict[str, Any], name: str) -> Any:  # noqa: ANN401 # type: ignore[override]
        """Extract values from the submitted form data."""
        select_value = data.get(f"{name}_select")
        custom_value = data.get(f"{name}_custom")

        if select_value == self.CUSTOM_VALUE and custom_value:
            return custom_value
        if select_value and select_value not in (self.CUSTOM_VALUE, "None", ""):
            return select_value

        return None


class ChoiceWithCustomField(forms.Field):
    """
    A field that provides a select dropdown with an option for custom text input.

    When a predefined choice is selected, returns that value.
    When 'Custom' is selected and text is entered, returns the custom text.
    """

    SEPARATOR = (Select.SEPARATOR_VALUE, Select.SEPARATOR_LABEL)
    DISABLED = Select.DISABLED
    CUSTOM = SelectWithCustomWidget.CUSTOM_VALUE

    def __init__(
        self,
        choices: Sequence[tuple[str | None, str]] = (),
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        self.choices: tuple[tuple[str | None, str], ...] = tuple(choices)

        kwargs["widget"] = kwargs.get("widget", SelectWithCustomWidget(choices=self.choices))

        super().__init__(*args, **kwargs)
