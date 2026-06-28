import os

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

import api.bookings.routing.routing


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plug_backend.settings")

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": URLRouter(
        api.bookings.routing.routing.websocket_urlpatterns
    ),
})