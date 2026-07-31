from decimal import Decimal
import json

from asgiref.sync import sync_to_async
from django.utils import timezone

from api.bookings.consumers.provider_base_consumer import ProviderBaseConsumer
from api.bookings.events.event_base import EventBus
from api.bookings.events.order_events import ProviderLocationUpdatedEvent
from api.serviceProvidersDB.models import SPLiveLocation, SPLocationHistory, ServiceProvider
from api.serviceProvidersDB.services.location_servicelocation_service import LocationService


class ProviderMainConsumer(ProviderBaseConsumer):

    async def booking_invite(self, event):
        
        await self.send_json({
            "type": "booking_invite",
            "data": event["data"],
        })

    async def booking_update(self, event):
        await self.send_json({
            "type": "booking_update",
            "data": event["data"],
        })

    async def negotiation_update(self, event):
        await self.send_json({
            "type": "negotiation_update",
            "data": event["data"],
        })

    async def notification(self, event):
        await self.send_json({
            "type": "notification",
            "data": event["data"],
        })

    async def booking_removed(self, event):
        await self.send_json({
        "type": "booking_removed",
        "data": event["data"],
    })

    async def receive(self, text_data=None, bytes_data=None):
        
        
        await super().receive(text_data, bytes_data)

        if not text_data:
            return

        data = json.loads(text_data)

        if data.get("type") == "location_update":
            await self.handle_location_update(data)

    async def handle_location_update(self, data):
        latitude = data.get("latitude")
        longitude = data.get("longitude")
        provider = await self.get_service_provider()

        if latitude is None or longitude is None:
            return

        provider = await self.update_provider_location(
            provider,
            latitude,
            longitude,
        )

        EventBus.emit(
            ProviderLocationUpdatedEvent({
                "provider": provider,
                "latitude": latitude,
                "longitude": longitude,
                "timestamp": timezone.now().isoformat(),
            })
        )

    @sync_to_async
    def get_service_provider(self):
        return ServiceProvider.objects.get(
            sp_profile=self.provider

        )
    

    @sync_to_async
    def update_provider_location(
        self,
        provider,
        latitude,
        longitude,
    ):

        lat = Decimal(str(latitude))
        lon = Decimal(str(longitude))

        live_location, created = SPLiveLocation.objects.get_or_create(
            provider=provider,
            defaults={
                "latitude": lat,
                "longitude": lon,
            },
        )

        should_reverse_geocode = False

        if created:
            should_reverse_geocode = True

        else:

            if (
                not live_location.suburb
                or not live_location.city
                or not live_location.province
            ):
                should_reverse_geocode = True

            elif LocationService.has_moved(
                float(live_location.latitude),
                float(live_location.longitude),
                float(lat),
                float(lon),
                minimum_distance=500,
            ):
                should_reverse_geocode = True

        live_location.latitude = lat
        live_location.longitude = lon

        if should_reverse_geocode:

            location = LocationService.reverse_geocode(
                float(lat),
                float(lon),
            )

            live_location.suburb = location["suburb"]
            live_location.city = location["city"]
            live_location.province = location["province"]

        live_location.save()

        SPLocationHistory.objects.create(
            provider=provider,
            latitude=lat,
            longitude=lon,
        )

        return live_location