# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

"""Models for the OpenADR GUI application."""

import datetime
import json
import logging
import uuid
from abc import abstractmethod
from collections.abc import Sequence
from typing import Any

from django.core.validators import MinLengthValidator
from django.db import models
from django.utils.translation import gettext_lazy
from django_stubs_ext.db.models import TypedModelMeta
from pydantic import TypeAdapter

logger = logging.getLogger(__name__)

# List of commonly used currencies
TOP_CURRENCIES = ("USD", "EUR", "JPY", "GBP", "AUD", "CAD", "CHF", "CNY", "HKD", "SEK", "MXN")


class JSONEncoder(json.JSONEncoder):
    """JSONEncoder that supports datetime and timedelta."""

    def default(self, obj: Any) -> Any:  # noqa: ANN401, D102
        if isinstance(obj, datetime.datetime):
            return {"_type": "datetime", "value": TypeAdapter(datetime.datetime).dump_python(obj, mode="json")}
        if isinstance(obj, datetime.timedelta):
            return {"_type": "timedelta", "value": TypeAdapter(datetime.timedelta).dump_python(obj, mode="json")}
        if isinstance(obj, uuid.UUID):
            return {"_type": "uuid", "value": str(obj)}

        return super().default(obj)


class JSONDecoder(json.JSONDecoder):
    """JSONDecoder that supports datetime and timedelta."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs, object_hook=self.object_hook)

    def object_hook(self, dct: dict[str, Any]) -> dict[str, Any]:
        """
        Custom JSON decoder that converts datetime and timedelta objects to Python objects.

        Also converts empty strings and null values to None.

        Args:
            dct (dict[str, Any]): The JSON dictionary to decode.

        """
        # Convert empty strings (and null values in the JSON) to None
        for key, value in dct.items():
            if value == "":
                dct[key] = None

        if "_type" not in dct:
            return dct
        if dct["_type"] == "datetime":
            return TypeAdapter(datetime.datetime).validate_python(dct["value"])
        if dct["_type"] == "timedelta":
            return TypeAdapter(datetime.timedelta).validate_python(dct["value"])
        if dct["_type"] == "uuid":
            return uuid.UUID(dct["value"])
        return dct


class JSONField(models.JSONField):
    """JSONField that supports datetime and timedelta."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs["encoder"] = JSONEncoder
        kwargs["decoder"] = JSONDecoder
        super().__init__(*args, **kwargs)

    def get_prep_value(self, value) -> Any:  # noqa: ANN001, ANN401, D102
        return super().get_prep_value(value)


class NullCharField(models.CharField):
    """CharField that stores empty strings as null."""

    def get_prep_value(self, value) -> Any:  # noqa: ANN001, ANN401, D102
        # Convert empty strings to None
        if value == "":
            return None
        return super().get_prep_value(value)


class NullTextField(models.TextField):
    """TextField that stores empty strings as null."""

    def get_prep_value(self, value) -> Any:  # noqa: ANN001, ANN401, D102
        # Convert empty strings to None
        if value == "":
            return None
        return super().get_prep_value(value)


class Model(models.Model, metaclass=TypedModelMeta):
    """Base model for all models."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Metadata options for the Model."""

        abstract = True

    def __str__(self) -> str:
        """Return a string representation of the model."""
        return self.name

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of the model."""


class DjangoResourceModel(Model):
    """Configuration model for the OpenADR GUI application."""

    objects: models.Manager["DjangoResourceModel"] = models.Manager()

    resource_name = NullCharField(max_length=100, null=False, validators=[MinLengthValidator(1)])

    class Meta(TypedModelMeta):
        """
        Metadata options for the Configuration model.

        Configures default ordering of configurations by section and key.
        """

        constraints = (models.UniqueConstraint(fields=["resource_name"], name="resource_name_unique"),)

    @property
    def name(self) -> str:  # noqa: D102
        return self.resource_name

    @property
    def user_identifier_field_name(self) -> str:  # noqa: D102
        return "resource_name"


class DjangoProgramModel(Model):
    """Configuration model for the OpenADR GUI application."""

    objects: models.Manager["DjangoProgramModel"] = models.Manager()

    program_name = NullCharField(max_length=100)
    program_long_name = NullCharField(max_length=255, null=True)
    retailer_name = NullCharField(max_length=100, null=True)
    retailer_long_name = NullCharField(max_length=255, null=True)
    program_type = NullCharField(max_length=100, null=True)
    country = NullCharField(max_length=100, null=True)
    principal_subdivision = NullCharField(max_length=100, null=True)
    interval_period = JSONField(null=True)
    program_descriptions = JSONField(null=True)
    binding_events = models.BooleanField(default=False)
    local_price = models.BooleanField(default=False)

    class Meta(TypedModelMeta):
        """
        Metadata options for the Configuration model.

        Configures default ordering of configurations by section and key.
        """

        ordering = (
            "id",
            "program_name",
            "program_long_name",
            "retailer_name",
            "retailer_long_name",
            "program_type",
            "program_descriptions",
            "binding_events",
            "local_price",
        )
        constraints = (models.UniqueConstraint(fields=["program_name"], name="program_name_unique"),)

    def __str__(self) -> str:
        """Return a string representation of the Configuration."""
        return self.program_long_name

    @property
    def name(self) -> str:  # noqa: D102
        return self.program_name

    @property
    def user_identifier_field_name(self) -> str:  # noqa: D102
        return "program_name"


class ProgramDeploymentsModel(Model):
    """Configuration model for the OpenADR GUI application."""

    objects: models.Manager["ProgramDeploymentsModel"] = models.Manager()

    program = models.ForeignKey(DjangoProgramModel, on_delete=models.CASCADE)

    class Meta(TypedModelMeta):
        """Metadata options for the DjangoProgramModel model."""

        constraints = (models.UniqueConstraint(fields=["program"], name="program_unique"),)


class DeploymentStatus(models.TextChoices):
    """Status of a program deployment."""

    FAILED = "FAILED", "Failed"
    SKIPPED = "SKIPPED", "Skipped"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    SUCCESS = "SUCCESS", "Success"


class ProgramDeploymentLogModel(Model):
    """Configuration model for the OpenADR GUI application."""

    objects: models.Manager["ProgramDeploymentLogModel"] = models.Manager()

    program_deployment = models.ForeignKey(ProgramDeploymentsModel, on_delete=models.CASCADE)
    deployment_date = models.DateTimeField()
    deployment_status = models.CharField(
        choices=DeploymentStatus,
        default=DeploymentStatus.IN_PROGRESS,
    )
    deployment_error_message = models.TextField(default="")

    class Meta(TypedModelMeta):
        """Metadata options for the ProgramDeploymentLogModel model."""

        constraints = (
            models.UniqueConstraint(
                fields=["program_deployment", "deployment_date", "deployment_status"],
                name="program_deployment_date_status_unique",
            ),
        )


class DjangoEventModel(Model):
    """Configuration model for the OpenADR GUI application."""

    objects: models.Manager["DjangoEventModel"] = models.Manager()

    program_id = models.ForeignKey(DjangoProgramModel, on_delete=models.CASCADE)

    event_name = NullCharField(max_length=100, null=True)

    interval_period = JSONField(null=True)

    intervals = JSONField(null=True)

    targets = JSONField(null=True)

    payload_descriptors = JSONField(null=True)

    # reportDescriptors is not yet implemented.

    # NOTE: Is 0 the same as None?
    priority = models.IntegerField(null=True)

    class Meta(TypedModelMeta):
        """
        Metadata options for the Configuration model.

        Configures default ordering of configurations by section and key.
        """

        ordering = (
            "id",
            "program_id",
            "event_name",
            "priority",
        )
        # Do not know wether this is required in OpenADR.
        constraints = (
            models.UniqueConstraint(
                fields=["program_id", "event_name"],
                name="program_id_event_name_unique",
            ),
        )

    def __str__(self) -> str:
        """Return a string representation of the Configuration."""
        return f"{self.program_id.program_name} - {self.event_name}"

    @property
    def name(self) -> str:  # noqa: D102
        return self.event_name

    @property
    def user_identifier_field_name(self) -> str:  # noqa: D102
        return "event_name"


class LogEntry(Model):
    """Log entry model for the OpenADR GUI application."""

    class LogEntryType(models.TextChoices):
        """Type of log entry."""

        VEN = "VEN", gettext_lazy("VEN")
        PROGRAM = "PROGRAM", gettext_lazy("Program")
        CONFIGURATION = "CONFIGURATION", gettext_lazy("Configuration")
        EVENT = "EVENT", gettext_lazy("Event")
        USER_LOGIN = "USER_LOGIN", gettext_lazy("User login")
        RESOURCE = "RESOURCE", gettext_lazy("Resource")

    objects: models.Manager["LogEntry"]

    LEVEL_CHOICES: Sequence[tuple[str, str]] = (
        ("DEBUG", "Debug"),
        ("INFO", "Info"),
        ("WARNING", "Warning"),
        ("ERROR", "Error"),
    )

    SOURCE_CHOICES: Sequence[tuple[str, str]] = (
        ("GUI", "GUI Action"),
        ("OPENADR", "OpenADR Protocol"),
        ("EVENT", "OpenADR Event"),
        ("SYSTEM", "System"),
    )

    timestamp = models.DateTimeField(auto_now_add=True)
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default="INFO")
    source = models.CharField(max_length=50, choices=SOURCE_CHOICES, default="SYSTEM")
    message = models.TextField()
    action = models.CharField(max_length=50, blank=True, default="")
    details = JSONField(blank=True, default=dict)
    type = models.CharField(max_length=50, choices=LogEntryType.choices, default=LogEntryType.VEN)
    name = models.CharField(max_length=100, blank=True, default="")
    event_id = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        """
        Metadata options for the LogEntry model.

        Configures default ordering of log entries by timestamp in descending order.
        """

        ordering: Sequence[str] = ("-timestamp",)

    def __str__(self) -> str:
        """
        Return a string representation of the LogEntry.

        Returns:
            str: A formatted string containing timestamp, source, level, and message.

        """
        return f"[{self.timestamp}] {self.source} - {self.level}: {self.message}"

    @classmethod
    def log_gui_action(
        cls,
        message: str,
        action: str,
        details: dict[str, Any],
        entry_type: LogEntryType,
        name: str | None = None,
        event_id: str | None = None,
    ) -> "LogEntry":
        """Create a log entry for GUI actions with optional VEN and event IDs."""
        return cls.objects.create(
            level="INFO",
            source="GUI",
            message=message,
            action=action,
            details=details,
            type=entry_type,
            name=name or "",
            event_id=event_id or "",
        )
