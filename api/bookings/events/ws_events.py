from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def _send_group_event(group_name: str, event_type: str, payload: dict) -> None:
    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": event_type,
            "data": payload,
        },
    )

def notify_provider_booking_removed(provider_id: int, order_id: int) -> None:
    _send_group_event(
        group_name=f"provider_{provider_id}",
        event_type="booking_removed",
        payload={
            "order_id": order_id,
        },
    )


def notify_provider_booking_invite(provider_id: int, payload: dict) -> None:
    _send_group_event(
        group_name=f"provider_{provider_id}",
        event_type="booking_invite",
        payload=payload,
    )

def notify_provider_negotiation_update(provider_id, payload):
    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        f"provider_{provider_id}",
        {
            "type": "negotiation_update",
            "data": payload,
        },
    )

def notify_client_location(order_id: str, payload: dict) -> None:
    _send_group_event(
        group_name=f"order_{order_id}",
        event_type="provider_location_updated",
        payload=payload,
    )


def notify_provider_booking_update(provider_id: int, payload: dict) -> None:
    _send_group_event(
        group_name=f"provider_{provider_id}",
        event_type="booking_update",
        payload=payload,
    )


def notify_client_booking(client_id: int, payload: dict) -> None:
    _send_group_event(
        group_name=f"client_{client_id}",
        event_type="booking_update",
        payload=payload,
    )


def notify_client_location(client_id: int, payload: dict) -> None:
    _send_group_event(
        group_name=f"client_{client_id}",
        event_type="location_update",
        payload=payload,
    )