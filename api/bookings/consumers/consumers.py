from api.bookings.consumers.client_base_consumer import  ClientBaseAppConsumer
from api.bookings.consumers.provider_base_consumer import ProviderBaseConsumer


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





class ProviderUpdatesConsumer(ProviderBaseConsumer):
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


class ClientOrderConsumer(ClientBaseAppConsumer):
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