# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

"""
Base view abstractions for OpenADR GUI.

This module provides generic base classes and mixins that eliminate
code duplication across entity views while preserving existing
functionality including HTMX integration, logging, and error handling.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cached_property
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

from django.contrib import messages
from django.db import DatabaseError, IntegrityError, models
from django.forms import BaseForm
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.views import View
from django.views.generic import CreateView, DeleteView, FormView, ListView, UpdateView
from django.views.generic.base import TemplateResponseMixin
from openadr3_client.bl._client import BusinessLogicClient
from openadr3_client.models.model import OpenADRResource
from view_breadcrumbs import (
    BaseBreadcrumbMixin,
    CreateBreadcrumbMixin,
    DeleteBreadcrumbMixin,
    ListBreadcrumbMixin,
    UpdateBreadcrumbMixin,
)

from openadrgui.models.djangomodels import LogEntry
from openadrgui.models.models import Target
from openadrgui.request_utils import (
    RequestType,
    get_bl_client,
    request_succeeded,
    request_to_form_errors,
    request_to_messages,
)
from openadrgui.services.services import aggregate_targets, split_targets
from openadrgui.types import HtmxHttpRequest
from openadrgui.views.utils import dynamic_formset_helper, get_targets_formset_factory


class ContextMixin:
    """Mixin that provides get_context_data for views that don't have it."""

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Provide base context data method."""
        return kwargs


if TYPE_CHECKING:
    from django.forms.formsets import BaseFormSet

    from openadrgui.forms.forms import TargetForm

logger = logging.getLogger(__name__)

Targets = tuple[Target[Any], ...]
TargetsMaybe = Targets | None
UpdateTargetsResult = tuple[TargetsMaybe, str | None]


class DjangoModelFormClass[DjangoModelT: models.Model](Protocol):
    """A Django form *class* that exposes a typed model_class attribute."""

    model_class: type[DjangoModelT]

    def __call__(self, *args: Any, **kwargs: Any) -> BaseForm:  # noqa: ANN401
        """Instantiate the form (class is callable)."""
        ...


@dataclass
class EntityConfig[FormClassT: Callable[..., BaseForm]]:
    """Configuration for entity views."""

    entity_name: str  # "event", "program", "ven"
    entity_name_plural: str  # "events", "programs", "vens"
    log_entry_type: LogEntry.LogEntryType

    # Templates
    list_template: str
    form_template: str
    delete_partial_template: str

    # Classes
    form_class: FormClassT

    # Context object name - defaults to lowercase plural entity name
    context_object_name: str = ""

    def __post_init__(self) -> None:
        """Set default values that depend on other fields."""
        if not self.context_object_name:
            self.context_object_name = self.entity_name_plural.lower()


class DjangoEntityConfig[DjangoModelT: models.Model](EntityConfig[DjangoModelFormClass[DjangoModelT]]):
    """EntityConfig variant for Django model-backed views."""


class BaseViewMixin:
    """Common functionality for all views."""

    class LoggableConfig(Protocol):
        """Minimum config surface required for logging actions."""

        entity_name: str
        log_entry_type: LogEntry.LogEntryType

    config: LoggableConfig
    request: HttpRequest
    args: tuple[Any, ...]
    kwargs: dict[str, Any]

    def log_action(
        self,
        action: str,
        instance: object,
        details: dict[str, Any] | None = None,
        name: str | None = None,
    ) -> None:
        """Log user actions consistently."""
        if name is None and not (hasattr(instance, "name") and instance.name):
            msg = "name must be provided if instance does not have a name attribute"
            raise ValueError(msg)

        name = instance.name if hasattr(instance, "name") else name

        LogEntry.log_gui_action(
            message=f"{action.title()} {self.config.entity_name}: {name}",
            action=f"{action}_{self.config.entity_name.lower()}",
            entry_type=self.config.log_entry_type,
            name=str(name),
            details=details or {},
        )


class HtmxResponseMixin(TemplateResponseMixin):
    """Mixin for handling HTMX responses consistently."""

    request: HttpRequest

    def render_to_response(self, context: dict[str, Any], **response_kwargs: object) -> HttpResponse:
        """Handle HTMX-aware rendering."""
        if bool(getattr(self.request, "htmx", False)):
            # For HTMX requests, use fragment templates
            template_names = self.get_template_names()
            if template_names:
                return render(self.request, template_names[0], context)

        return super().render_to_response(context, **response_kwargs)


# Base classes for API-based views (using OpenADR client)
class BaseAPIView[ResourceT: OpenADRResource](BaseViewMixin, HtmxResponseMixin, ABC):
    """Base for views that interact with OpenADR API."""

    config: EntityConfig[Any]

    @cached_property
    def client(self) -> BusinessLogicClient:
        """
        Lazily create the BL client.

        This must not run at import/class-definition time because Django imports URLconfs and view modules during
        management commands (e.g. `migrate`) as part of system checks.
        """
        return get_bl_client()

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        super().__init__(*args, **kwargs)
        self.form_class = self.config.form_class

    def get_api_object(self, object_id: str) -> ResourceT | None:
        """Get single object from API by ID. Override if different pattern."""
        # This is a fallback - specific views should override
        msg = "Subclasses must implement get_api_object"
        raise NotImplementedError(msg)

    def get_template_names(self) -> list[str]:
        """Get template names."""
        return [self.config.form_template]


class APIListView[ResourceT: OpenADRResource](BaseAPIView[ResourceT], BaseBreadcrumbMixin, ContextMixin, View):
    """Generic list view for API objects."""

    @cached_property
    def crumbs(self) -> list[tuple[str, str | None]]:
        """Override breadcrumbs to work with existing URL patterns."""
        return [
            (f"{self.config.entity_name_plural.title()}", None),
        ]

    @abstractmethod
    def get_api_objects(self, **kwargs: object) -> Sequence[ResourceT]:
        """Get objects from API."""

    def get(self, request: HtmxHttpRequest, **kwargs: Any) -> HttpResponse:  # noqa: ARG002, ANN401
        """Handle GET request."""
        self.request = request  # Store request for get_context_data
        context = self.get_context_data()

        return render(request, self.config.list_template, context)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Get context for list view."""
        context = super().get_context_data(**kwargs)

        result = request_to_messages(
            self.request, lambda: self.get_api_objects(**self.kwargs), request_type=RequestType.READ
        )
        context = {
            "id": self.kwargs.get("id"),
        }
        context_object_name = self.config.context_object_name
        if not context_object_name:
            msg = "context_object_name must be set in EntityConfig"
            raise ValueError(msg)
        if not request_succeeded(result):
            return {
                **context,
                context_object_name: [],
                "total_count": 0,
            }

        objects, _ = result
        return {
            **context,
            context_object_name: objects,
            "total_count": len(objects),
            **kwargs,
        }


class APICreateView[ResourceT: OpenADRResource](
    BaseAPIView[ResourceT], HtmxResponseMixin, BaseBreadcrumbMixin, FormView[BaseForm]
):
    """Generic create view for API objects."""

    @cached_property
    def crumbs(self) -> list[tuple[str, str | None]]:
        """Override breadcrumbs to work with existing URL patterns."""
        return [
            (f"Create {self.config.entity_name.title()}", self.get_success_url()),
        ]

    @abstractmethod
    def create_api_object(self, form_data: dict[str, Any]) -> ResourceT:
        """Create object via API."""

    @abstractmethod
    def get_success_url(self) -> str:
        """Get success URL after creation."""

    def form_valid[FormT: BaseForm](self, form: FormT) -> HttpResponse:
        """Handle valid form submission."""
        model = request_to_form_errors(
            form,
            lambda: self.create_api_object(form.cleaned_data),
            request_type=RequestType.CREATE,
        )

        if form.errors:
            return self.form_invalid(form)

        # Log the creation
        if model is None:
            msg = "Expected model to be created when form has no errors"
            raise ValueError(msg)
        self.log_action("created", model, {"id": str(getattr(model, "id", "unknown"))})

        # Add success message
        messages.success(self.request, f"{self.config.entity_name.title()} created successfully.")
        return HttpResponseRedirect(self.get_success_url())

    def form_invalid[FormT: BaseForm](self, form: FormT) -> HttpResponse:
        """Handle invalid form submission."""
        logger.error("Form validation errors: %s", form.errors)
        return super().form_invalid(form)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Get context data."""
        context = super().get_context_data(**kwargs)
        context["request"] = self.request  # Add request for breadcrumb support

        return {
            **context,
            "back_url": self.get_success_url(),
        }


class APIUpdateView[ResourceT: OpenADRResource](BaseAPIView[ResourceT], BaseBreadcrumbMixin, FormView[BaseForm]):
    """Generic update view for API objects."""

    existing_resource: ResourceT | None = None

    @cached_property
    def crumbs(self) -> list[tuple[str, str | None]]:
        """Override breadcrumbs to work with existing URL patterns."""
        return [
            (f"Edit {self.config.entity_name.title()}", self.get_success_url()),
        ]

    @abstractmethod
    def update_api_object(self, object_id: str, form_data: dict[str, Any]) -> ResourceT:
        """Update object via API."""

    @abstractmethod
    def get_success_url(self) -> str:
        """Get success URL after update."""

    def get_initial(self) -> dict[str, Any]:
        """Get initial form data from API object."""
        result = request_to_messages(
            self.request,
            lambda: self.get_api_object(str(self.kwargs["id"])),
            request_type=RequestType.READ,
        )
        if not request_succeeded(result):
            return {}
        obj, _ = result
        if obj is None:
            return {}
        # Reuse the prefetched object during this request (e.g. breadcrumbs) to avoid
        # multiple BL calls / lock acquisitions for the same entity.
        self.existing_resource = obj
        return obj.model_dump(mode="python") if hasattr(obj, "model_dump") else obj.__dict__

    def form_valid[FormT: BaseForm](self, form: FormT) -> HttpResponse:
        """Handle valid form submission."""
        model = request_to_form_errors(
            form,
            lambda: self.update_api_object(str(self.kwargs["id"]), form.cleaned_data),
            request_type=RequestType.UPDATE,
        )

        if form.errors:
            return self.form_invalid(form)

        changed_fields = getattr(form, "changed_data", [])
        if model is None:
            msg = "Expected model to be updated when form has no errors"
            raise ValueError(msg)
        self.log_action("updated", model, {"changes": changed_fields})
        messages.success(self.request, f"{self.config.entity_name.title()} updated successfully.")

        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Get context data."""
        context = super().get_context_data(**kwargs)
        return {
            **context,
            "back_url": self.get_success_url(),
        }


class APIDeleteView[ResourceT: OpenADRResource](BaseAPIView[ResourceT], BaseBreadcrumbMixin, ContextMixin, View):
    """Generic delete view for API objects."""

    @cached_property
    def crumbs(self) -> list[tuple[str, str | None]]:
        """Override breadcrumbs to work with existing URL patterns."""
        return [
            (f"Delete {self.config.entity_name.title()}", self.get_success_url()),
        ]

    list_view: APIListView[OpenADRResource] | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        if not hasattr(self, "list_view") or self.list_view is None:
            msg = "list_view must be provided"
            raise ValueError(msg)

        super().__init__(*args, **kwargs)

    @abstractmethod
    def delete_api_object(self, object_id: str) -> ResourceT:
        """Delete object via API."""

    def delete(self, request: HtmxHttpRequest, **kwargs: Any) -> HttpResponse:  # noqa: ANN401
        """Handle DELETE request."""
        object_id = kwargs["id"]
        result = request_to_messages(
            request,
            lambda: self.delete_api_object(object_id),
            request_type=RequestType.DELETE,
        )

        if not request_succeeded(result):
            if request.htmx:
                response = HttpResponse(
                    status=HTTPStatus.UNPROCESSABLE_CONTENT,
                )
                response.headers["HX-Reswap"] = "none"
                response.headers["HX-Trigger-After-Settle"] = "closeModal"
                return response
            return HttpResponseRedirect(self.get_success_url())

        obj, _ = result
        obj_data = obj.model_dump(mode="json") if hasattr(obj, "model_dump") else obj.__dict__
        self.log_action("deleted", obj, obj_data)
        messages.success(request, f"{self.config.entity_name.title()} deleted successfully.")

        if request.htmx:
            # Set request on the list view instance and get context
            list_view = self.list_view
            if list_view is None:
                msg = "list_view must be provided"
                raise ValueError(msg)
            list_view.args = self.args
            list_view.request = self.request
            list_view.kwargs = self.get_list_context_data(**self.kwargs)

            return render(request, self.config.delete_partial_template, list_view.get_context_data())

        return HttpResponseRedirect(self.get_success_url())

    @abstractmethod
    def get_success_url(self) -> str:
        """Get success URL after deletion."""

    def get_list_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Override to mutate list context data, for instance to change the id field."""
        return {**kwargs}


# Base classes for Django model views
class BaseDjangoView(BaseViewMixin, ABC):
    """Base for views that work with Django models."""

    config: DjangoEntityConfig[Any]
    model: Any
    form_class: Any

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        self.model = self.config.form_class.model_class
        self.form_class = self.config.form_class
        super().__init__(*args, **kwargs)


class DjangoListView(BaseDjangoView, HtmxResponseMixin, ListBreadcrumbMixin, ListView[models.Model]):
    """Generic list view for Django models."""

    def get_template_names(self) -> list[str]:
        """Get template names."""
        return [self.config.list_template]

    def get_context_object_name(self, _object_list: Any) -> str:  # noqa: ANN401
        """Get the name to use for the object list in the context."""
        return self.config.context_object_name

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Get context for list view."""
        context = super().get_context_data(**kwargs)

        return {
            **context,
            "total_count": len(context.get(self.config.context_object_name, [])),
            "url_prefix": "dp-",
            "id": self.kwargs.get("id"),
        }

    @cached_property
    def crumbs(self) -> list[tuple[str, str | None]]:
        """Override breadcrumbs to work with existing URL patterns."""
        return [
            (f"{self.config.entity_name_plural.title()}", None),
        ]


class DjangoCreateView(BaseDjangoView, HtmxResponseMixin, CreateBreadcrumbMixin, CreateView[models.Model, Any]):
    """Generic create view for Django models."""

    pk_url_kwarg = "id"
    # Breadcrumb configuration
    app_name = None  # Use None to avoid namespace lookup

    def get_template_names(self) -> list[str]:
        """Get template names."""
        return [self.config.form_template]

    @cached_property
    def crumbs(self) -> list[tuple[str, str | None]]:
        """Override breadcrumbs to work with existing URL patterns."""
        return [
            (f"Create {self.config.entity_name.title()}", self.get_success_url()),
        ]

    def form_valid(self, form: BaseForm) -> HttpResponse:
        """Handle valid form submission."""
        response = super().form_valid(form)

        obj = self.object
        if obj is None:
            msg = "Expected object to be set after successful form submission"
            raise ValueError(msg)
        self.log_action("created", obj, {"id": str(obj.pk)})
        messages.success(self.request, f"{self.config.entity_name.title()} created successfully.")

        return response

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Get context data."""
        context = super().get_context_data(**kwargs)
        return {
            **context,
            "back_url": self.get_success_url(),
        }


class DjangoUpdateView(BaseDjangoView, HtmxResponseMixin, UpdateBreadcrumbMixin, UpdateView[models.Model, Any]):
    """Generic update view for Django models."""

    pk_url_kwarg = "id"
    # Breadcrumb configuration
    app_name = None  # Use None to avoid namespace lookup

    def get_template_names(self) -> list[str]:
        """Get template names."""
        return [self.config.form_template]

    @cached_property
    def crumbs(self) -> list[tuple[str, str | None]]:
        """Override breadcrumbs to work with existing URL patterns."""
        return [
            (f"Edit {self.config.entity_name.title()}", self.get_success_url()),
        ]

    def form_valid(self, form: BaseForm) -> HttpResponse:
        """Handle valid form submission."""
        changed_fields = getattr(form, "changed_data", [])
        response = super().form_valid(form)

        self.log_action("updated", self.object, {"changes": changed_fields})
        messages.success(self.request, f"{self.config.entity_name.title()} updated successfully.")

        return response

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Get context data."""
        context = super().get_context_data(**kwargs)
        return {
            **context,
            "back_url": self.get_success_url(),
        }


class DjangoDeleteView(BaseDjangoView, HtmxResponseMixin, DeleteBreadcrumbMixin, DeleteView[models.Model, Any]):
    """Generic delete view for Django models."""

    pk_url_kwarg = "id"
    # Breadcrumb configuration
    app_name = None  # Use None to avoid namespace lookup
    list_view: DjangoListView | None = None
    """The field to use for the ID in the list view."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        if not hasattr(self, "list_view") or self.list_view is None:
            msg = "list_view must be provided"
            raise ValueError(msg)
        super().__init__(*args, **kwargs)

    @cached_property
    def crumbs(self) -> list[tuple[str, str | None]]:
        """Override breadcrumbs to work with existing URL patterns."""
        return [
            (f"Delete {self.config.entity_name.title()}", self.get_success_url()),
        ]

    def delete(self, request: HttpRequest, *args: object, **kwargs: object) -> HttpResponse:
        """Handle deletion with logging."""
        response = super().delete(request, *args, **kwargs)

        self.log_action("deleted", self.object, {"id": str(self.object.pk)})
        messages.success(request, f"{self.config.entity_name.title()} deleted successfully.")

        if bool(getattr(request, "htmx", False)):
            list_view = cast("DjangoListView", self.list_view)
            list_view.args = args
            list_view.request = request
            list_view.kwargs = self.get_list_context_data(**kwargs)
            list_view.object_list = list_view.get_queryset()
            return render(request, self.config.delete_partial_template, list_view.get_context_data())

        return HttpResponseRedirect(self.get_success_url())

        return response

    def get_list_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Override to mutate list context data, for instance to change the id field."""
        return {**kwargs}


@dataclass
class TargetsConfig:
    """Configuration for targets views."""

    entity_name: str  # "event", "resource", "program"
    log_entry_type: LogEntry.LogEntryType
    template_name: str = "openadrgui/targets.html"


# Base class for targets views
class BaseTargetsView(ABC, BaseViewMixin, HtmxResponseMixin, BaseBreadcrumbMixin, ContextMixin, View):
    """Base class for targets management views."""

    config: TargetsConfig

    @abstractmethod
    def get_targets(self) -> TargetsMaybe:
        """Get the targets for the object."""

    @abstractmethod
    def update_targets(self, targets: Targets) -> UpdateTargetsResult:
        """Update the targets and return (targets, name_for_logging)."""

    @abstractmethod
    def handle_exceptions[T](
        self,
        method: Callable[[], T],
        request_type: RequestType,
    ) -> tuple[T, Literal[True]] | tuple[None, Literal[False]]:
        """Handle exceptions for get_targets calls."""

    @abstractmethod
    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        """Get the base context for rendering."""
        context = super().get_context_data(**kwargs)
        return {
            **context,
            "back_url": self.get_success_url(),
            "dynamic_form_id_prefix": "__new-",
        }

    @abstractmethod
    def get_success_url(self) -> str:
        """Get the success URL."""

    def get_template_names(self) -> list[str]:
        """Get template names."""
        return [self.config.template_name]

    def get(self, request: HtmxHttpRequest, **kwargs: Any) -> HttpResponse:  # noqa: ANN401
        """Handle GET request to display targets form."""
        targets_raw, success = self.handle_exceptions(self.get_targets, RequestType.READ)
        if not success:
            if request.htmx:
                return HttpResponse(status=HTTPStatus.INTERNAL_SERVER_ERROR)
            # Exception occurred, return to success URL
            return HttpResponseRedirect(self.get_success_url())

        targets_initial = split_targets(targets_raw)

        targets_formset = get_targets_formset_factory()(initial=targets_initial)

        context = self.get_context_data(**kwargs)
        context.update({"formset": targets_formset})

        return render(request, self.config.template_name, context=context)

    def post(self, request: HtmxHttpRequest, **kwargs: Any) -> HttpResponse:  # noqa: ANN401
        """Handle POST request to update targets."""
        context = self.get_context_data(**kwargs)
        post_data = dynamic_formset_helper(
            request.POST,
            context["dynamic_form_id_prefix"],
            get_targets_formset_factory()(),
        )

        targets_formset: BaseFormSet[TargetForm] = get_targets_formset_factory()(post_data)
        context.update({"formset": targets_formset})

        if targets_formset.is_valid():
            aggregated_targets = aggregate_targets(targets_formset.cleaned_data)
            targets_and_name, success = cast(
                "tuple[UpdateTargetsResult, Literal[True]]",
                self.handle_exceptions(lambda: self.update_targets(aggregated_targets), RequestType.UPDATE),
            )
            targets, name = targets_and_name

            if not success:
                # Exception occurred, return form with error context
                return render(
                    request,
                    f"{self.config.template_name}#targets-table",
                    context=context,
                    status=HTTPStatus.UNPROCESSABLE_CONTENT,
                )

            self.log_action(
                "updated",
                targets,
                {
                    "data": targets_formset.cleaned_data,
                },
                name,
            )
            messages.success(request, f"{self.config.entity_name.title()} updated successfully.")

            targets_initial = split_targets(targets)
            targets_formset = get_targets_formset_factory()(initial=targets_initial)
            context.update({"formset": targets_formset})

            return render(request, f"{self.config.template_name}#targets-table", context=context)

        return render(
            request,
            f"{self.config.template_name}#targets-table",
            context=context,
            status=HTTPStatus.UNPROCESSABLE_CONTENT,
        )


class APITargetsView(BaseTargetsView):
    """Mixin for handling exceptions in API-based targets operations."""

    def handle_exceptions[T](
        self,
        method: Callable[[], T],
        request_type: RequestType,
    ) -> tuple[T, Literal[True]] | tuple[None, Literal[False]]:
        """Handle exceptions for get_targets API calls."""
        return request_to_messages(
            self.request,
            lambda: method(),
            request_type=request_type,
        )


class DbTargetsView(BaseTargetsView):
    """Mixin for handling exceptions in database-based targets operations."""

    def handle_exceptions[T](
        self,
        method: Callable[[], T],
        _request_type: RequestType,
    ) -> tuple[T, Literal[True]] | tuple[None, Literal[False]]:
        """Handle exceptions for get_targets database calls."""
        try:
            return method(), True
        except DatabaseError:
            logger.exception("Error getting targets from database")
            messages.error(self.request, "An error occurred while loading targets.")
            return None, False
        except IntegrityError:
            logger.exception("Validation error while getting targets from database")
            messages.error(self.request, "An error occurred while loading targets.")
            return None, False

    def _update_targets(self, targets: Targets) -> UpdateTargetsResult:
        """Update the targets for the object."""
        return self.update_targets(targets)

    def _get_targets(self) -> TargetsMaybe:
        """Get the targets for the object."""
        return self.get_targets()

    @abstractmethod
    def get_targets(self) -> TargetsMaybe:
        """Get the targets for the object."""

    @abstractmethod
    def update_targets(self, targets: Targets) -> UpdateTargetsResult:
        """Update the targets and return (targets, name_for_logging)."""
