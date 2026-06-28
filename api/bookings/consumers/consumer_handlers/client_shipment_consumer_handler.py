import json


async def route_update(self, event):
    await self.send(text_data=json.dumps({
        "type": "route.update",
        "distance_meters": event.get("distance_meters"),
        "duration_seconds": event.get("duration_seconds"),
        "geometry": event.get("geometry"),
    }))

async def location_update(self, event):
    await self.send(text_data=json.dumps({
        "type": "location.update",
        "lat": event["lat"],
        "lng": event["lng"],
        "bearing": event.get("bearing", 0),
    }))

async def eta_update(self, event):
    await self.send(text_data=json.dumps({
        "type": "eta.update",
        "distance_meters": event["distance_meters"],
        "duration_seconds": event["duration_seconds"],
    }))

async def shipment_status_update(self, event):
    await self.send(text_data=json.dumps({
        "type": "shipment.status.update",
        "shipment_id": self.shipment_id,
        "status": event["status"],
        "updated_at": event.get("updated_at")
        
    }))

async def session_created(self, event):
    await self.send(text_data=json.dumps({
        "type": "session_created",
        "shipment_id": event["shipment_id"],
        "session_id": event["session_id"],
        "session_status": event["session_status"],
        "checkin_time": event["checkin_time"],
    }))


async def session_completed(self, event):
    await self.send(text_data=json.dumps({
        "type": "session_completed",
        "shipment_id": event["shipment_id"],
        "session_id": event["session_id"],
        "session_status": event["session_status"],
        "checkout_time": event["checkout_time"],
    }))