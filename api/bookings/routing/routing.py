from django.urls import re_path

from api.bookings.consumers.client_new_negociation_consumer import NegotiationConsumer
from api.bookings.consumers.provider_main_consumer import ProviderMainConsumer
from api.bookings.consumers.provider_session_consumer import ProviderSessionConsumer
from api.bookings.consumers.shipment_route_consumer import ShipmentRouteConsumer
from ..consumers.consumers import ProviderUpdatesConsumer, ClientOrderConsumer

websocket_urlpatterns = [
    re_path(
    r"ws/provider/$",
    ProviderMainConsumer.as_asgi(),
),

re_path(
        r"ws/session/(?P<shipment_id>\d+)/$",
        ProviderSessionConsumer.as_asgi(),
    ),
    re_path(r"ws/client/(?P<user_id>[^/]+)/$", ClientOrderConsumer.as_asgi()),

    re_path(
    r"ws/negotiation/(?P<negotiation_id>\d+)/$",
    NegotiationConsumer.as_asgi()
),

re_path(
        r"ws/shipments/(?P<shipment_id>\d+)/route/$",
        ShipmentRouteConsumer.as_asgi()
    ),
    
]