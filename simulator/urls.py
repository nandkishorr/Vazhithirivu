from django.urls import path

from . import views

urlpatterns = [
    path(
        "api/simulation/",
        views.api_simulation_state,
        name="api_simulation_state",
    ),
]
