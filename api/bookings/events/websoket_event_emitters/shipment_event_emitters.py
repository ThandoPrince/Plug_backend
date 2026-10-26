from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from datetime import datetime
import logging
from decimal import Decimal
 
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
 
logger = logging.getLogger(__name__)


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



def _safe_group_send(group_name, message):
    """These run inside transaction.on_commit() after the money/session change has already
    been saved. If the channel layer (Redis) is down, we must log and carry on. Raising here
    would turn a successful webhook into a 500 and make Paystack retry for no reason."""
    try:
        async_to_sync(get_channel_layer().group_send)(group_name, message)
    except Exception:
        logger.exception("Websocket push failed. group=%s type=%s", group_name, message.get("type"))
 
 
def push_session_started(shipment_id, session):
    """Payment cleared (or client switched to cash): the session is now live."""
    _safe_group_send(
        f"shipment_route_{shipment_id}",
        {
            "type": "session_started",
            "shipment_id": shipment_id,
            "session_id": session.session_id,
            "session_status": session.session_status,
        },
    )
 
 
def push_payment_update(shipment_id, payment):
    """Payment changed state (succeeded / failed / switched).
 
    SECURITY: this group contains BOTH the client and the provider, so never put checkout
    details (access_code, authorization_url, reference) in here. Those come only from the
    client-only /initiate/ endpoint."""
    _safe_group_send(
        f"shipment_route_{shipment_id}",
        {
            "type": "payment_updated",
            "shipment_id": shipment_id,
            "payment_id": payment.payment_id,
            "method": payment.method,
            "status": payment.status,
            "failure_reason": payment.failure_reason,
            "amount": str(Decimal(payment.amount_cents) / 100),
        },
    )
 