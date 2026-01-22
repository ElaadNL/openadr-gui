# SPDX-FileCopyrightText: Contributors to openadr-gui<https://github.com/ElaadNL/openadr-gui>
#
# SPDX-License-Identifier: Apache-2.0

"""
URL configuration for openadrgui project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/

Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))

"""

from django.contrib import admin
from django.urls import include, path

# https://github.com/mozilla/mozilla-django-oidc/issues/545#issuecomment-2688760294
# Debugger crashes here
from mozilla_django_oidc import views as oidc_views

from .views import api_views, dp_views, error_views, logged_out, programs_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("oidc/", include("mozilla_django_oidc.urls")),
    path("login/", oidc_views.OIDCAuthenticationRequestView.as_view(), name="login"),
    path("logout/", oidc_views.OIDCLogoutView.as_view(), name="logout"),
    path("logged_out/", logged_out.logged_out, name="logged_out"),
    path("", api_views.ven_views.VenAPIListView.as_view(), name="index"),
    path("vens/new/", api_views.ven_views.VenAPICreateView.as_view(), name="vens-create"),
    path("vens/<uuid:id>/edit/", api_views.ven_views.VenAPIUpdateView.as_view(), name="vens-edit"),
    path("vens/<uuid:id>/delete/", api_views.ven_views.VenAPIDeleteView.as_view(), name="vens-delete"),
    path("vens/<uuid:id>/resources/", api_views.resource_views.ResourceAPIListView.as_view(), name="vens-resources"),
    path(
        "vens/<uuid:id>/resources/new/",
        api_views.resource_views.ResourceAPICreateView.as_view(),
        name="resources-create",
    ),
    path(
        "vens/<uuid:ven_id>/resources/<uuid:id>/edit/",
        api_views.resource_views.ResourceAPIUpdateView.as_view(),
        name="resources-edit",
    ),
    path(
        "vens/<uuid:ven_id>/resources/<uuid:id>/delete/",
        api_views.resource_views.ResourceAPIDeleteView.as_view(),
        name="resources-delete",
    ),
    path(
        "vens/<uuid:ven_id>/resources/<uuid:id>/targets/",
        api_views.resource_target_views.ResourceTargetsView.as_view(),
        name="resource-targets",
    ),
    path(
        "vens/<uuid:ven_id>/resources/<uuid:id>/targets/form/",
        api_views.resource_target_views.resource_targets_form,
        name="resource-targets-form",
    ),
    path("subdivisions/", programs_view.get_subdivisions_choice_field, name="subdivisions"),
    path("subdivisions/<str:country>/", programs_view.get_subdivisions_choice_field, name="subdivisions"),
    path("programs/", programs_view.programs, name="programs"),
    path("programs/<uuid:id>/delete/", api_views.program_views.ProgramAPIDeleteView.as_view(), name="programs-delete"),
    path("programs/<uuid:id>/edit/", api_views.program_views.ProgramAPIUpdateView.as_view(), name="programs-edit"),
    path("programs/<uuid:id>/events/", api_views.event_views.EventAPIListView.as_view(), name="events"),
    path(
        "programs/<uuid:program_id>/events/<uuid:id>/delete",
        api_views.event_views.EventAPIDeleteView.as_view(),
        name="events-delete",
    ),
    path(
        "programs/<uuid:program_id>/events/<uuid:id>/edit",
        api_views.event_views.EventAPIUpdateView.as_view(),
        name="events-edit",
    ),
    path(
        "programs/<uuid:program_id>/events/<uuid:id>/targets/",
        api_views.event_target_views.EventTargetsView.as_view(),
        name="event-targets",
    ),
    path(
        "programs/<uuid:program_id>/events/<uuid:id>/targets/form/",
        api_views.event_target_views.event_targets_form,
        name="event-targets-form",
    ),
    path(
        "programs/<uuid:program_id>/events/<uuid:id>/intervals/",
        api_views.interval_views.IntervalsView.as_view(),
        name="intervals",
    ),
    path(
        "programs/<uuid:program_id>/events/<uuid:id>/intervals/<str:payload_type>/",
        api_views.interval_views.IntervalsView.as_view(),
        name="intervals-payload",
    ),
    path(
        "programs/<uuid:program_id>/events/<uuid:id>/intervals/<str:payload_type>/generate-interval-curve/",
        api_views.interval_views.GenerateIntervalCurveView.as_view(),
        name="generate-interval-curve",
    ),
    path(
        "programs/<uuid:program_id>/events/<uuid:id>/intervals/<str:payload_type>/import-csv/",
        api_views.interval_views.ImportCsvView.as_view(),
        name="import-csv",
    ),
    path(
        "programs/<uuid:program_id>/events/<uuid:id>/intervals/<str:payload_type>/payload-descriptor/",
        api_views.interval_views.PayloadDescriptorView.as_view(),
        name="payload-descriptor",
    ),
    path(
        "deployment-packages/new/",
        dp_views.program_views.ProgramDPCreateView.as_view(),
        name="dp-programs-create",
    ),
    path(
        "deployment-packages/scheduled-deployments/",
        dp_views.repeat_deployments_view.RepeatDeploymentsView.as_view(),
        name="dp-scheduled-deployments",
    ),
    path(
        "deployment-packages/<uuid:id>/schedule-deployment/",
        dp_views.program_views.ScheduledProgramDeploymentView.as_view(),
        name="dp-schedule-deployment",
    ),
    path(
        "deployment-packages/<uuid:id>/deploy/",
        dp_views.program_views.DeployProgramView.as_view(),
        name="dp-deploy-program",
    ),
    path(
        "deployment-packages/<uuid:id>/delete/",
        dp_views.program_views.ProgramDPDeleteView.as_view(),
        name="dp-programs-delete",
    ),
    path(
        "deployment-packages/<uuid:id>/edit/",
        dp_views.program_views.ProgramDPUpdateView.as_view(),
        name="dp-programs-edit",
    ),
    path("deployment-packages/<uuid:id>/events/", dp_views.event_views.EventDPListView.as_view(), name="dp-events"),
    path(
        "deployment-packages/<uuid:id>/events/new",
        dp_views.event_views.EventDPCreateView.as_view(),
        name="dp-events-create",
    ),
    path(
        "deployment-packages/<uuid:dp_id>/events/<uuid:id>/delete",
        dp_views.event_views.EventDPDeleteView.as_view(),
        name="dp-events-delete",
    ),
    path(
        "deployment-packages/<uuid:dp_id>/events/<uuid:id>/edit",
        dp_views.event_views.EventDPUpdateView.as_view(),
        name="dp-events-edit",
    ),
    path(
        "deployment-packages/<uuid:dp_id>/events/<uuid:id>/targets/",
        dp_views.program_target_views.TargetsView.as_view(),
        name="dp-event-targets",
    ),
    path(
        "deployment-packages/<uuid:dp_id>/events/<uuid:id>/targets/form/",
        dp_views.program_target_views.program_targets_form,
        name="dp-event-targets-form",
    ),
    path("__reload__/", include("django_browser_reload.urls")),
    path(
        "deployment-packages/<uuid:dp_id>/events/<uuid:id>/intervals/",
        dp_views.interval_views.IntervalsView.as_view(),
        name="dp-intervals",
    ),
    path(
        "deployment-packages/<uuid:dp_id>/events/<uuid:id>/intervals/<str:payload_type>/",
        dp_views.interval_views.IntervalsView.as_view(),
        name="dp-intervals-payload",
    ),
    path(
        "deployment-packages/<uuid:dp_id>/events/<uuid:id>/intervals/<str:payload_type>/generate-interval-curve/",
        dp_views.interval_views.GenerateIntervalCurveView.as_view(),
        name="dp-generate-interval-curve",
    ),
    path(
        "deployment-packages/<uuid:dp_id>/events/<uuid:id>/intervals/<str:payload_type>/import-csv/",
        dp_views.interval_views.ImportCsvView.as_view(),
        name="dp-import-csv",
    ),
    path(
        "deployment-packages/<uuid:dp_id>/events/<uuid:id>/intervals/<str:payload_type>/payload-descriptor/",
        dp_views.interval_views.PayloadDescriptorView.as_view(),
        name="dp-payload-descriptor",
    ),
    path(
        "deployment-packages/<uuid:dp_id>/deploy/",
        dp_views.program_views.ScheduledProgramDeploymentView.as_view(),
        name="dp-deploy-program",
    ),
]

# Custom error handlers
handler500 = error_views.server_error
handler404 = error_views.page_not_found
