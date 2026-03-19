from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def safe_group(value: str) -> str:
    return (
        value.strip()
        .lower()
        .replace("@", "_")
        .replace(".", "_")
        .replace("-", "_")
        .replace("+", "_")
        .replace(" ", "_")
    )


def _send_group_event(group_name: str, event_type: str, payload: dict) -> None:
    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": event_type,
            "data": payload,
        },
    )


def notify_provider_booking_invite(email: str, payload: dict) -> None:
    _send_group_event(
        group_name=f"provider_{safe_group(email)}",
        event_type="booking_invite",
        payload=payload,
    )


def notify_provider_booking_update(email: str, payload: dict) -> None:
    _send_group_event(
        group_name=f"provider_{safe_group(email)}",
        event_type="booking_update",
        payload=payload,
    )


def notify_client_booking(email: str, payload: dict) -> None:
    _send_group_event(
        group_name=f"client_{safe_group(email)}",
        event_type="booking_update",
        payload=payload,
    )


def notify_client_location(email: str, payload: dict) -> None:
    _send_group_event(
        group_name=f"client_{safe_group(email)}",
        event_type="location_update",
        payload=payload,
    )