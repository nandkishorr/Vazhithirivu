from django.urls import path

from . import views

urlpatterns = [
    path(
        "api/navigation/sessions/",
        views.api_navigation_start,
        name="api_navigation_start",
    ),
    path(
        "api/navigation/sessions/<uuid:session_id>/position/",
        views.api_navigation_position,
        name="api_navigation_position",
    ),
    path(
        "api/navigation/sessions/<uuid:session_id>/end/",
        views.api_navigation_end,
        name="api_navigation_end",
    ),
]
