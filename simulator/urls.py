from django.urls import path

from . import views

urlpatterns = [
    path(
        "api/simulation/",
        views.api_simulation_state,
        name="api_simulation_state",
    ),
    path(
        "api/simulation/prompts/<int:pk>/confirm/",
        views.api_simulation_prompt_confirm,
        name="api_simulation_prompt_confirm",
    ),
    path(
        "api/simulation/prompts/<int:pk>/dismiss/",
        views.api_simulation_prompt_dismiss,
        name="api_simulation_prompt_dismiss",
    ),
]
