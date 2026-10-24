import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import (  # noqa: E402
    AllowedHostsOriginValidator,
)

from incidents.routing import (  # noqa: E402
    websocket_urlpatterns as incident_ws_urlpatterns,
)
from simulator.routing import (  # noqa: E402
    websocket_urlpatterns as simulator_ws_urlpatterns,
)

websocket_urlpatterns = incident_ws_urlpatterns + simulator_ws_urlpatterns

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
