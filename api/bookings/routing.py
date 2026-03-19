from django.urls import re_path
from .consumers import ProviderUpdatesConsumer, ClientOrderConsumer

websocket_urlpatterns = [
    re_path(
        r"ws/provider-bookings/(?P<email>[^/]+)/$",
        ProviderUpdatesConsumer.as_asgi(),
    ),
    re_path(r"ws/client/(?P<email>[^/]+)/$", ClientOrderConsumer.as_asgi()),
    
]