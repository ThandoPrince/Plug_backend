import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer


logger = logging.getLogger(__name__)


def safe_group_value(value: str) -> str:
    return (
        value.strip()
        .lower()
        .replace("@", "_")
        .replace(".", "_")
        .replace("-", "_")
        .replace("+", "_")
        .replace(" ", "_")
    )


class BaseAppConsumer(AsyncWebsocketConsumer):
    group_prefix = None

    async def connect(self):
        user_id = self.scope["url_route"]["kwargs"].get("user_id")

        if user_id is None or self.group_prefix is None:
            await self.close(code=4000)
            return

        self.user_id = int(user_id)
        self.group_name = f"{self.group_prefix}_{self.user_id}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )

        await self.accept()

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
            logger.warning("Invalid websocket payload.")

            await self.send_json({
                "type": "error",
                "message": "Invalid message format."
            })
            return

        if data.get("type") == "ping":
            await self.send_json({
                "type": "pong"
            })

    async def send_json(self, payload):
        await self.send(text_data=json.dumps(payload))


class ProviderUpdatesConsumer(BaseAppConsumer):
    group_prefix = "provider"

    async def booking_update(self, event):
        await self.send_json({
            "type": "booking_update",
            "data": event["data"],
        })

    async def booking_invite(self, event):
        await self.send_json({
            "type": "booking_invite",
            "data": event["data"],
        })

    async def location_update(self, event):
        await self.send_json({
            "type": "location_update",
            "data": event["data"],
        })

    async def shipment_route_updated(self, event):
        await self.send_json({
            "type": "shipment_route_updated",
            "data": event["data"],
        })

    async def shipment_status_updated(self, event):
        await self.send_json({
            "type": "shipment_status_updated",
            "data": event["data"],
        })


class ClientOrderConsumer(BaseAppConsumer):
    group_prefix = "client"

    async def booking_update(self, event):
        await self.send_json({
            "type": "booking_update",
            "data": event["data"],
        })

    async def location_update(self, event):
        await self.send_json({
            "type": "location_update",
            "data": event["data"],
        })

    async def shipment_route_updated(self, event):
        await self.send_json({
            "type": "shipment_route_updated",
            "data": event["data"],
        })

    async def shipment_status_updated(self, event):
        await self.send_json({
            "type": "shipment_status_updated",
            "data": event["data"],
        })