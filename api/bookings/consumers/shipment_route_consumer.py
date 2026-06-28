import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async

from api.bookings.models import Shipment
from api.bookings.utils.ws_auth import authenticate_ws_token


logger = logging.getLogger(__name__)


class ShipmentRouteConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.shipment_id = self.scope["url_route"]["kwargs"]["shipment_id"]
        print(">>> ShipmentRouteConsumer.connect() CALLED <<<")

        # -------------------------
        # Token
        # -------------------------
        token = self.get_token_from_query()

        if not token:
            await self.close(code=4001)
            return

        # -------------------------
        # Authentication
        # -------------------------
        try:
            user, role = await sync_to_async(authenticate_ws_token)(token)

        except Exception:
            logger.exception(
                "Shipment websocket authentication failed. shipment_id=%s",
                self.shipment_id,
            )
            await self.close(code=4003)
            return

        if not user:
            await self.close(code=4003)
            return

        self.scope["user"] = user
        self.scope["role"] = role

        # -------------------------
        # Load shipment + authorize
        # -------------------------
        try:
            shipment = await self.get_shipment(self.shipment_id)

            if shipment is None:
                await self.close(code=4004)
                return

            allowed = await self.check_access(
                user.id,
                role,
                shipment,
            )

            if not allowed:
                await self.close(code=4003)
                return

        except Exception:
            logger.exception(
                "Shipment websocket initialization failed. shipment_id=%s",
                self.shipment_id,
            )
            await self.close(code=4500)
            return

        self.shipment = shipment
        self.group_name = f"shipment_route_{self.shipment_id}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )
        print("=" * 50)
        print("WEBSOCKET CONNECTED")
        print("Shipment:", self.shipment_id)
        print("Group:", self.group_name)
        print("Channel:", self.channel_name)
        print("=" * 50)

        await self.accept()

    # --------------------------------------------------
    # Token
    # --------------------------------------------------

    def get_token_from_query(self):
        query_string = self.scope["query_string"].decode()

        for param in query_string.split("&"):
            if param.startswith("token="):
                return param.split("=", 1)[1]

        return None
    

    # --------------------------------------------------
    # Shipment
    # --------------------------------------------------,m

    @sync_to_async
    def get_shipment(self, shipment_id):
        try:
            return (
                Shipment.objects
                .select_related(
                    "service_ordered__order",
                    "service_ordered__order__provider_for_service",
                    "service_ordered__order__client",
                )
                .get(pk=shipment_id)
            )

        except Shipment.DoesNotExist:
            return None

    # --------------------------------------------------
    # Authorization
    # --------------------------------------------------

    @sync_to_async
    def check_access(self, user_id, role, shipment):

        booking_item = shipment.service_ordered
        order = booking_item.order

        if role == "client":
            return order.client_id == user_id

        if role == "provider":
            return order.provider_for_service_id == user_id

        return False

    # --------------------------------------------------
    # Events (implemented next)
    # --------------------------------------------------

    async def shipment_route_updated(self, event):
        """
        Receives route updates from group_send().
        Implementation will be added next.
        """
        pass

    async def shipment_status_update(self, event):
        print("=" * 50)
        print("shipment_status_update CALLED")
        print(event)
        print("=" * 50)
        await self.send(text_data=json.dumps({
            "type": "shipment_status_update",
            "status": event["status"],
            "updated_at": event["updated_at"],
        }))

    # --------------------------------------------------
    # Disconnect
    # --------------------------------------------------

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name,
            )