


from api.bookings.utils.negoctiation_even_builder import NegotiationNotificationBuilder
from api.clientsDB.notifications.services.notification_service import NotificationService


def handle_negotiation_round_created(payload):

    negotiation = payload["negotiation"]
    round_obj = payload["round"]

    order = negotiation.service_order

    client_auth = getattr(
        order.client,
        "client_profile",
        None
    )

    if not client_auth:
        return

    notification_payload = (
        NegotiationNotificationBuilder.round_created(
            negotiation,
            round_obj
        )
    )

    NotificationService.notify_client(
        client=client_auth,
        notification_type="negotiation_round_created",
        title="New Price Offer 💰",
        body=f"A provider offered R{round_obj.offered_price} for your request.",
        payload=notification_payload,
    )