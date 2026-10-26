


from django.db import transaction

from api.bookings.events.event_base import EventBus
from api.bookings.events.order_events import ProviderDeclinedInvitationEvent, ProviderOrderCancelledEvent
from api.bookings.events.ws_events import notify_client_booking_cancelled, notify_provider_booking_invite, notify_provider_booking_removed, notify_provider_negotiation_update
from api.bookings.models import OrderService
from api.bookings.serializers import NegotiationRoundReadSerializer, OrderServiceReadSerializer

from api.bookings.services.celery_task import notify_invited_providers_order_removed, notify_invited_providers_order_removed2, process_order_created, send_client_round_notification_to_provider, send_order_accepted_notification, send_order_cancelled_notification, send_shipment_status_notification
from api.bookings.utils.handlers.visibility import is_visible_to_provider
from api.clientsDB.notifications.services.notification_builder import OrderNotificationBuilder
from api.clientsDB.notifications.services.notification_service import NotificationService





def handle_order_created(payload):
    order = payload["order"]

    if not is_visible_to_provider(order):
        return

    serializer = OrderServiceReadSerializer(order)

    for provider in order.invited_providers.all():
        notify_provider_booking_invite(
            provider.id,
            serializer.data,
        )

    process_order_created.delay(order.order_id)

def handle_order_updated(order):

    if not is_visible_to_provider(order):
        return

    serializer = OrderServiceReadSerializer(order)
    booking_payload = serializer.data

    for provider in order.invited_providers.all():
        notify_provider_booking_invite(
            provider_id=provider.id,
            payload=booking_payload,
        )

def handle_negotiation_created(payload):
    negotiation = payload["negotiation"]
    round_obj = payload["round"]

    provider_id = negotiation.provider_for_negotiation.provider.sp_profile.id
    live_payload = {
        "action": "new_round",
        "type": "negotiation_update",
        "order_id": negotiation.service_order.order_id,
        "negotiation_id": negotiation.negotiation_id,
        "round": NegotiationRoundReadSerializer(round_obj).data,
    }
    round_id = round_obj.pk

    def _after_commit():
        print(f"[negotiation_created] after_commit provider_id={provider_id} round_id={round_id}", flush=True)
        notify_provider_negotiation_update(provider_id=provider_id, payload=live_payload)
        send_client_round_notification_to_provider.delay(round_id)
        print("[negotiation_created] task queued", flush=True)

    transaction.on_commit(_after_commit)


def handle_provider_order_cancelled(payload):

    order = payload.get("order")
    shipment = payload.get("shipment")

    if not order or not shipment:
        return

    client = order.client

    if not client:
        return

    client_profile = client.client_profile

    if not client_profile:
        return

    # Broadcast websocket update so the booking disappears immediately
    handle_order_updated(order)

    NotificationService.notify_client(
        client=client_profile,
        notification_type="provider_order_cancelled",
        title="Booking Cancelled ❌",
        body="Your service provider has cancelled this booking.",
        payload=OrderNotificationBuilder.provider_order_cancelled(order),
    )

    notify_client_booking_cancelled(
        client_id=client_profile.id,
       
    )


def handle_order_cancelled(payload):
    order = payload.get("order")
    shipment = payload.get("shipment")

    if not order or not shipment:
        return

    handle_order_updated(order)  # unchanged, still synchronous

    order_id = order.pk

    def _dispatch():
        send_order_cancelled_notification.delay(order_id)
        notify_invited_providers_order_removed2.delay(order_id)

    transaction.on_commit(_dispatch)

def handle_order_accepted(payload):
    order = payload["order"]
    order_id = order.pk

    # Existing live-update logic. Keep it as is, it's cheap.
    handle_order_updated(order)

    # Worker must never run before the accept is committed.
    transaction.on_commit(
        lambda: send_order_accepted_notification.delay(order_id)
    )



def handle_final_price_updated(payload):
    order = payload.get("order")
    final_price = payload.get("final_price")

    if not order:
        return

    provider_for_service = order.provider_for_service.provider.sp_profile

    if not provider_for_service:
        return
    
    NotificationService.notify_provider(
            provider=provider_for_service,
            notification_type="order_final_price_updated",
            title="Booking Price Updated 💰",
            body=f"The client updated the booking price to {final_price}.",
            payload={
                "order_id": order.order_id,
                "final_price": final_price,
            },
            websocket_invite=False,
        )


def handle_provider_arrived(payload):
    order_id = payload["order_id"]
    shipment_id = payload["shipment_id"]
    transaction.on_commit(
        lambda: send_shipment_status_notification.delay(
            order_id, shipment_id, "provider_arrived"
        )
    )


def handle_provider_in_transit(payload):
    order_id = payload["order_id"]
    shipment_id = payload["shipment_id"]
    transaction.on_commit(
        lambda: send_shipment_status_notification.delay(
            order_id, shipment_id, "provider_in_transit"
        )
    )

def handle_order_rescheduled(payload):

    order = payload.get("order")
    shipment = payload.get("shipment")

    if not order or not shipment:
        return

    # Resolve the provider's SPProfile
    provider_service = shipment.service_ordered.order.provider_for_service

    if not provider_service:
        return

    service_provider = provider_service.provider

    if not service_provider:
        return

    sp_profile = service_provider.sp_profile

    if not sp_profile:
        return

    NotificationService.notify_provider(
        provider=sp_profile,
        notification_type="order_rescheduled",
        title="Booking Rescheduled 📅",
        body="The client has rescheduled the booking.",
        payload=OrderNotificationBuilder.order_rescheduled(order),
    )
    for provider in order.invited_providers.all():
        notify_provider_booking_removed(
            provider_id=provider.id,
            order_id=order.order_id,
        )

def handle_provider_declined_invitation(payload):
    order = payload["order"]
    provider = payload["provider"]
    order_cancelled = payload["order_cancelled"]

    client = getattr(order.client, "client_profile", None)

    if not client:
        return

    remaining_providers = order.invited_providers.count()

    if order_cancelled:
        NotificationService.notify_client(
            client=client,
            notification_type="booking_cancelled",
            title="Booking Cancelled ❌",
            body=(
                "All invited providers have declined your booking. "
                "Your booking has been cancelled."
            ),
            payload={
                **OrderNotificationBuilder.booking_cancelled(order),
                "provider_id": provider.id,
                "remaining_providers": remaining_providers,
            },
        )
    else:
        NotificationService.notify_client(
            client=client,
            notification_type="provider_declined",
            title="Provider Declined",
            body=(
                "One of the invited providers declined your booking. "
                "We're still waiting for responses from the remaining providers."
            ),
            payload={
                **OrderNotificationBuilder.order_updated(order),
                "provider_id": provider.id,
                "remaining_providers": remaining_providers,
            },
        )



def handle_provider_no_show(payload):
    transaction.on_commit(
        lambda: send_shipment_status_notification.delay(
            payload["order_id"], payload["shipment_id"], "provider_no_show"
        )
    )

EventBus.register("shipment.no_show", handle_provider_no_show)

EventBus.register(
    "order.created",
    handle_order_created
)

EventBus.register(
    "order.rescheduled",
    handle_order_rescheduled
)

EventBus.register(
    "order.cancelled",
    handle_order_cancelled
)

EventBus.register(
    "order.final_price_updated",
    handle_final_price_updated
)
EventBus.register(
    "provider.declined_invitation",
    handle_provider_declined_invitation
)

EventBus.register(
    "negotiation.created",
    handle_negotiation_created,
)

EventBus.register(
    ProviderOrderCancelledEvent,
    handle_provider_order_cancelled,
)

EventBus.register(
    "order.accepted",
    handle_order_accepted
)

EventBus.register(
    "order.in_transit",
    handle_provider_in_transit
)

EventBus.register(
    "order.arrived",
    handle_provider_arrived
)