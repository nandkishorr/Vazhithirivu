from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("ui/", views.ui_gallery, name="ui_gallery"),
    path("healthz/", views.healthz, name="healthz"),
    path("readyz/", views.readyz, name="readyz"),
]
