from django.conf import settings


def google_auth(request):
    return {
        "GOOGLE_OAUTH_ENABLED": bool(
            getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "")
            and getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "")
        )
    }
