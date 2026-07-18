from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from datetime import datetime


def push_route_update(shipment_id, route):
    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        f"shipment_route_{shipment_id}",
        {
            "type": "route_update",
            "distance_meters": route.distance_meters,
            "duration_seconds": route.duration_seconds,
            "geometry": route.geometry,
        }
    )


def push_location_update(shipment_id, lat, lng, bearing=0):
    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        f"shipment_route_{shipment_id}",
        {
            "type": "location_update",
            "lat": lat,
            "lng": lng,
            "bearing": bearing,
        }
    )


def push_eta_update(shipment_id, distance_meters, duration_seconds):
    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        f"shipment_route_{shipment_id}",
        {
            "type": "eta_update",
            "distance_meters": distance_meters,
            "duration_seconds": duration_seconds,
        }
    )


def push_shipment_status_update(shipment_id, status):
    channel_layer = get_channel_layer()

    print("================================")
    print("Sending shipment status update")
    print("Group:", f"shipment_route_{shipment_id}")
    print("Status:", status)
    print("================================")

    async_to_sync(channel_layer.group_send)(
        f"shipment_route_{shipment_id}",
        {
            "type": "shipment_status_update",
            "status": status,
            "updated_at": datetime.utcnow().isoformat(),
        },
    )

def push_session_created(shipment_id, session):
    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        f"shipment_route_{shipment_id}",
        {
            "type": "session_created",
            "shipment_id": shipment_id,
            "session_id": session.session_id,
            "session_status": session.session_status,
            "checkin_time": session.checkin_time.isoformat(),
        }
    )

def push_session_completed(session):
    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        f"shipment_route_{session.shipment.shipment_id}",
        {
            "type": "session_completed",
            "shipment_id": session.shipment.shipment_id,
            "session_id": session.session_id,
            "session_status": session.session_status,
            "checkout_time": (
                session.checkout_time.isoformat()
                if session.checkout_time
                else None
            ),
        },
    )

    