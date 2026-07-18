import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plug_backend.settings")

from django.core.asgi import get_asgi_application

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
import api.bookings.routing.routing

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": URLRouter(
        api.bookings.routing.routing.websocket_urlpatterns
    ),
})