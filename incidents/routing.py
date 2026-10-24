from django.urls import path

from .consumers import CrossingStatusConsumer

websocket_urlpatterns = [
    path("ws/crossings/", CrossingStatusConsumer.as_asgi()),
]
