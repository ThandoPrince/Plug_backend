import json
from channels.generic.websocket import AsyncWebsocketConsumer


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
    group_prefix = None  # override in child classes

    async def connect(self):
        email = self.scope["url_route"]["kwargs"].get("email", "")
        self.email = email.strip().lower()

        if not self.email or not self.group_prefix:
            await self.close()
            return

        self.group_name = f"{self.group_prefix}_{safe_group_value(self.email)}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        group_name = getattr(self, "group_name", None)
        if group_name:
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return

        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        message_type = data.get("type")

        if message_type == "ping":
            await self.send_json({
                "type": "pong"
            })

    async def send_json(self, payload: dict):
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