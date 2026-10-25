from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Keep our own login/logout first so they win over allauth's
    # account_login/account_logout at the same paths (ADR-019).
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(),
        name="login",
    ),
    path(
        "accounts/logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),
    path("accounts/", include("allauth.urls")),
    path("", include("core.urls")),
    path("", include("incidents.urls")),
    path("", include("navigation.urls")),
    path("", include("simulator.urls")),
]
