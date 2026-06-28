import json
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from api.bookings.models import Negotiation
from api.bookings.utils.ws_auth import authenticate_ws_token
from rest_framework_simplejwt.exceptions import TokenError


class NegotiationConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.negotiation_id = self.scope["url_route"]["kwargs"]["negotiation_id"]

        # -------------------------
        # Token
        # -------------------------m,
        token = self.get_token_from_query()

        if not token:
            await self.close(code=4001)
            return

        # -------------------------
        # Auth
        # -------------------------
        try:
            user, role = await sync_to_async(authenticate_ws_token)(token)
        except Exception:
            await self.close(code=4003)
            return

        if not user:
            await self.close(code=4003)
            return

        self.scope["user"] = user
        self.scope["role"] = role

        # -------------------------
        # Load negotiation
        # -------------------------
        try:
            negotiation = await self.get_negotiation(self.negotiation_id)
        except Negotiation.DoesNotExist:
            await self.close(code=4004)
            return

        # -------------------------
        # Access check
        # -------------------------
        access = await self.check_access(user.id, role, self.negotiation_id)

        if not access:
            await self.close(code=4003)
            return

        self.negotiation = negotiation
        self.group_name = f"negotiation_{self.negotiation_id}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        await self.accept()

    # -------------------------
    # Token extraction
    # -------------------------
    def get_token_from_query(self):
        query_string = self.scope["query_string"].decode()

        for param in query_string.split("&"):
            if param.startswith("token="):
                return param.split("token=")[1]

        return None

    # -------------------------
    # DB: load negotiation
    # -------------------------
    @sync_to_async
    def get_negotiation(self, negotiation_id):
        return (
            Negotiation.objects
            .select_related("service_order")
            .get(pk=negotiation_id)
        )

    # -------------------------
    # DB: access check
    # -------------------------
    @sync_to_async
    def check_access(self, user_id, role, negotiation_id):
        negotiation = (
            Negotiation.objects
            .select_related("service_order")
            .get(pk=negotiation_id)
        )

        if role == "client":
            return negotiation.service_order.client_id == user_id

        if role == "provider":
            return negotiation.provider_for_negotiation_id == user_id

        return False

    # -------------------------
    # Events
    # -------------------------
    async def negotiation_round_created(self, event):
        await self.send(text_data=json.dumps(event))

    async def negotiation_status_changed(self, event):
        await self.send(text_data=json.dumps(event))

    async def negotiation_counter_offer(self, event):
        await self.send(text_data=json.dumps(event))

    # -------------------------
    # Disconnect
    # -------------------------
    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )