import json
import logging

from asgiref.sync import sync_to_async
from django.core.exceptions import ObjectDoesNotExist

from api.bookings.consumers.consumer_handlers.session_handler import (
    SessionHandler,
)
from api.bookings.consumers.provider_base_consumer import (
    ProviderBaseConsumer,
)
from api.bookings.models import Session, SessionLocationPing, Shipment
from api.bookings.serializers import SessionLocationPingReadSerializer, ShipmentRouteReadSerializer
from api.bookings.services.calculate_distance_meters import calculate_distance_meters
from api.bookings.services.shipment_route_service import (
    ShipmentRouteService,
)
from plug_backend import settings

logger = logging.getLogger(__name__)


class ProviderSessionConsumer(
    ProviderBaseConsumer,
    SessionHandler,
):

    async def connect(self):
        await super().connect()

        self.shipment_id = self.scope["url_route"]["kwargs"]["shipment_id"]

        shipment = await self.get_shipment()

        if shipment is None:
            await self.close(code=4004)
            return

        self.shipment = shipment
        self.client_group = (
    f"client_{shipment.service_ordered.order.client.client_profile.id}"
)
        self.route_group = f"shipment_route_{shipment.shipment_id}"

        

        await self.send_json({
            "type": "session_connected",
            "shipment_id": shipment.shipment_id,
        })

    async def disconnect(self, close_code):

        

        await super().disconnect(close_code)

    async def receive(self, text_data=None, bytes_data=None):
        """
        Receives websocket messages after ProviderBaseConsumer has already
        handled ping/pong and token refresh.
        """
        logger.info("[Provider WS] receive() called")
        logger.info("[Provider WS] Raw message: %s", text_data)

        await super().receive(text_data, bytes_data)

        if not text_data:
            return

        try:
            data = json.loads(text_data)

        except json.JSONDecodeError:
            await self.send_json({
                "type": "error",
                "message": "Invalid JSON.",
            })
            return

        handlers = {
            "route_update": self.handle_route_update,
            "geofence_ping": self.handle_geofence_ping,
        }

        handler = handlers.get(data.get("type"))

        if handler:
            await handler(data)

    async def handle_route_update(self, data):
            """
            Creates a shipment route and broadcasts it to:
            - Everyone tracking this shipment
            - The owning client's personal websocket
            """

            try:
                logger.info(
                    "[Provider WS] Received route update for shipment=%s",
                    self.shipment.shipment_id,
                )

                route = await self.create_route(data)

                logger.info(
                    "[Provider WS] Route created (id=%s)",
                    route.route_id,
                )

                payload = await self.serialize_route(route)

                logger.info(
                    "[Provider WS] Route serialized for shipment=%s",
                    self.shipment.shipment_id,
                )
                await self.channel_layer.group_send(
        self.route_group,
        {
            "type": "shipment_route_updated",
            "data": payload,
        },
    )

                client_id = self.shipment.service_ordered.order.client.client_profile.id

                logger.info(
        "[Provider WS] Broadcasting to shipment group '%s'",
        self.route_group,
    )

                # Shipment tracking socket
                await self.channel_layer.group_send(
                    self.route_group,
                    {
                        "type": "shipment_route_updated",
                        "data": payload,
                    },
                )

                logger.info(
                    "[Provider WS] Shipment group broadcast complete."
                )

                logger.info(
        "[Provider WS] Broadcasting to route group '%s'",
        self.route_group,
    )

                # Client personal socket
                await self.channel_layer.group_send(
        self.route_group,
        {
            "type": "shipment_route_updated",
            "data": payload,
        },
    )

                logger.info(
                    "[Provider WS] Client broadcast complete."
                )

            except Exception:
                logger.exception(
                    "[Provider WS] Failed to create/broadcast shipment route."
                )

                await self.send_json({
                    "type": "error",
                    "message": "Failed to create shipment route.",
                })
    @sync_to_async
    def get_shipment(self):
        try:
            return Shipment.objects.select_related(
                "service_ordered",
                "service_ordered__order",
                "service_ordered__order__client",
                "service_ordered__order__client__client_profile",
                "service_ordered__order__provider_for_service",
                "service_ordered__order__provider_for_service__provider",
                "service_ordered__order__provider_for_service__provider__sp_profile",
            ).get(
                shipment_id=self.shipment_id,
                service_ordered__order__provider_for_service__provider__sp_profile=self.provider,
            )

        except ObjectDoesNotExist:
            return None
        
    @sync_to_async
    def process_geofence_ping(self, latitude, longitude):
        session = (
            Session.objects
            .select_related(
                "shipment",
                "shipment__service_ordered",
                "shipment__service_ordered__order",
                "shipment__service_ordered__order__delivery_address",
            )
            .get(shipment=self.shipment)
        )

        address = session.shipment.service_ordered.order.delivery_address

        center_lat = float(address.latitude)
        center_lng = float(address.longitude)

        distance = calculate_distance_meters(
            center_lat,
            center_lng,
            latitude,
            longitude,
        )

        inside_geofence = (
            distance <= getattr(
                settings,
                "SESSION_GEOFENCE_RADIUS_METERS",
                50,
            )
        )

        ping = SessionLocationPing.objects.create(
            session=session,
            latitude=latitude,
            longitude=longitude,
            distance_from_site_meters=distance,
            inside_geofence=inside_geofence,
        )

        return SessionLocationPingReadSerializer(ping).data

    @sync_to_async
    def create_route(self, data):
        return ShipmentRouteService.create(
            shipment=self.shipment,
            data=data,
        )

    @sync_to_async
    def serialize_route(self, route):
        return ShipmentRouteReadSerializer(route).data
    
    async def handle_geofence_ping(self, data):
        try:
            latitude = data.get("latitude")
            longitude = data.get("longitude")

            if latitude is None or longitude is None:
                await self.send_json({
                    "type": "error",
                    "message": "latitude and longitude are required",
                })
                return

            try:
                latitude = float(latitude)
                longitude = float(longitude)
            except (TypeError, ValueError):
                await self.send_json({
                    "type": "error",
                    "message": "Invalid coordinates.",
                })
                return

            result = await self.process_geofence_ping(
                latitude=latitude,
                longitude=longitude,
            )

            await self.send_json({
                "type": "geofence_ping_ack",
                "data": result,
            })
            logger.info(
    "Sending geofence update to group %s",
    self.route_group,
)

            await self.channel_layer.group_send(
                self.route_group,
                {
                    "type": "geofence_ping_updated",
                    "data": result,
                },
            )

            logger.info("group_send completed")

        except Exception:
            logger.exception(
                "[Provider WS] Failed processing geofence ping."
            )

            await self.send_json({
                "type": "error",
                "message": "Unable to process geofence ping.",
            })