from django.urls import path

from . import views

urlpatterns = [
    path("crossings/<int:pk>/", views.crossing_detail, name="crossing_detail"),
    path(
        "crossings/<int:pk>/report/",
        views.crossing_report_submit,
        name="crossing_report_submit",
    ),
    path(
        "api/crossings/",
        views.api_crossings_in_bbox,
        name="api_crossings",
    ),
    path(
        "api/crossings/<int:pk>/status/",
        views.api_crossing_status,
        name="api_crossing_status",
    ),
    path(
        "api/crossings/<int:pk>/reports/",
        views.api_crossing_reports,
        name="api_crossing_reports",
    ),
]
