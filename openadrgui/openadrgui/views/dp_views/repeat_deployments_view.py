# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

from functools import cached_property

from django.db.models import QuerySet
from django.urls import reverse
from django.views.generic import ListView
from view_breadcrumbs import ListBreadcrumbMixin

from openadrgui.models.djangomodels import ProgramDeploymentLogModel
from openadrgui.views.base_views import HtmxResponseMixin
from openadrgui.views.types import Crumbs


class RepeatDeploymentsView(HtmxResponseMixin, ListBreadcrumbMixin, ListView[ProgramDeploymentLogModel]):
    """View for the repeat deployments of a deployment package."""

    model = ProgramDeploymentLogModel
    template_name = "openadrgui/dp_repeat_deployments.html"
    context_object_name = "deployments"

    def get_queryset(self) -> QuerySet[ProgramDeploymentLogModel]:
        """Get the repeat deployments of a deployment package."""
        return ProgramDeploymentLogModel.objects.all().order_by("-deployment_date")

    @cached_property
    def crumbs(self) -> Crumbs:
        """Override breadcrumbs to work with existing URL patterns."""
        return [
            ("Programs", reverse("programs")),
            ("Repeat Program Deployments", None),
        ]
