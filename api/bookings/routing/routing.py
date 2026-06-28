from django.urls import re_path

from api.bookings.consumers.client_new_negociation_consumer import NegotiationConsumer
from api.bookings.consumers.shipment_route_consumer import ShipmentRouteConsumer
from ..consumers.consumers import ProviderUpdatesConsumer, ClientOrderConsumer

websocket_urlpatterns = [
    re_path(
        r"ws/provider-bookings/(?P<user_id>[^/]+)/$",
        ProviderUpdatesConsumer.as_asgi(),
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