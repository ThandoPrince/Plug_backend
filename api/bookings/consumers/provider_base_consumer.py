import json
import logging

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from rest_framework_simplejwt.exceptions import TokenError
from jwt import ExpiredSignatureError

from api.bookings.utils.ws_auth import authenticate_ws_token

logger = logging.getLogger(__name__)


class ProviderBaseConsumer(AsyncWebsocketConsumer):
    """
    Base consumer for all provider websocket connections.

    Handles:
    - JWT authentication
    - Token refresh
    - Ping/Pong
    - Group registration
    """

    async def connect(self):

        token = self.get_token_from_query()

        if not token:
            await self.close(code=4001)
            return

        try:
            user, role = await sync_to_async(authenticate_ws_token)(token)

        except Exception:
            logger.exception("Provider websocket authentication failed.")
            await self.close(code=4003)
            return

        if not user or role != "provider":
            await self.close(code=4003)
            return

        self.scope["user"] = user
        self.scope["role"] = role

        self.provider = user

        self.group_name = f"provider_{self.provider.id}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )
        

        await self.accept()
        await self.send_json({
    "type": "connected",
    "provider_id": self.provider.id,
})

    async def disconnect(self, close_code):

        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name,
            )

    async def receive(self, text_data=None, bytes_data=None):

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

        message_type = data.get("type")

        if message_type == "ping":

            await self.send_json({
                "type": "pong",
            })

            return

        if message_type == "refresh":

            await self.handle_refresh(data)

            return

    async def handle_refresh(self, data):

        token = data.get("token")

        if not token:

            await self.close(code=4003)

            return

        try:
            user, role = await sync_to_async(authenticate_ws_token)(token)

        except Exception:

            await self.close(code=4003)

            return

        if (
            not user
            or role != "provider"
            or user.id != self.provider.id
        ):

            await self.close(code=4003)

            return

        self.scope["user"] = user

        await self.send_json({
            "type": "refresh_success",
        })

    def get_token_from_query(self):

        query = self.scope["query_string"].decode()

        for item in query.split("&"):

            if item.startswith("token="):

                return item.split("=", 1)[1]

        return None

    async def send_json(self, payload):

        await self.send(
            text_data=json.dumps(payload)
        )