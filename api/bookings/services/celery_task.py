from celery import shared_task
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone



from api.bookings.events.event_base import EventBus
from api.bookings.events.order_events import ShipmentNoShowEvent
from api.bookings.events.ws_events import notify_provider_booking_invite, notify_provider_booking_removed
from api.bookings.models import NO_SHOW_STATUSES, NegotiationRound, OrderService, Session, Shipment
from api.bookings.serializers import OrderServiceReadSerializer

from api.bookings.utils.negoctiation_even_builder import NegotiationNotificationBuilder
from api.bookings.views import ORDER_IN_SESSION
from api.clientsDB.notifications.services.notification_builder import OrderNotificationBuilder
from api.clientsDB.notifications.services.notification_service import NotificationService

import logging

logger = logging.getLogger(__name__)

@shared_task
def process_order_created(order_id):
    order = (
        OrderService.objects
        .select_related("client", "service_required")
        .prefetch_related("invited_providers")
        .get(pk=order_id)
    )

    notification_payload = OrderNotificationBuilder.booking_invite(order)

    for provider in order.invited_providers.all():
        NotificationService.notify_provider(
            provider=provider,
            notification_type="booking_invite",
            title="New Booking Request 📩",
            body=f"{notification_payload['client_name']} created a booking.",
            payload=notification_payload,
            websocket_invite=True,
        )



BATCH_SIZE = 200
UPDATE_FIELDS = ["requested_date", "requested_date_time", "reschedule_count", "status"]


@shared_task
def auto_reschedule_orders():
    cutoff = timezone.localtime(timezone.now() + timedelta(minutes=10))
    due = (
        Q(requested_date__lt=cutoff.date())
        | Q(requested_date=cutoff.date(), requested_date_time__lt=cutoff.time())
    )

    total = 0
    while True:
        with transaction.atomic():
            orders = list(
                OrderService.objects
                .select_for_update(skip_locked=True)
                .filter(
                    due,
                    status__in=OrderService.RESCHEDULABLE_STATUSES,
                    requested_date__isnull=False,
                    requested_date_time__isnull=False,
                )
                # finished orders: already overdue and capped, nothing left to do
                .exclude(status="overdue", reschedule_count__gte=OrderService.MAX_AUTO_RESCHEDULES)
                [:BATCH_SIZE]
            )
            if not orders:
                break

            for order in orders:
                if order.apply_auto_reschedule():
                    order.save(update_fields=UPDATE_FIELDS)  # save() writes history
                    total += 1
    return total

@shared_task
def expire_overdue_orders():
    now = timezone.now()

    # Orders that were already overdue before overdue_at existed: start their clock now
    OrderService.objects.filter(status="overdue", overdue_at__isnull=True).update(overdue_at=now)

    cutoff = now - OrderService.OVERDUE_EXPIRY
    total = 0
    while True:
        with transaction.atomic():
            orders = list(
                OrderService.objects
                .select_for_update(skip_locked=True)
                .filter(status="overdue", overdue_at__lte=cutoff)[:BATCH_SIZE]
            )
            if not orders:
                break
            for order in orders:
                order.status = "expired"
                order.save(update_fields=["status"])  # save() logs history
                total += 1
    return total


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    ignore_result=True,
    # queue="notifications",  # optional, same worker can consume it
)
def send_negotiation_round_notification(self, round_id):
    round_obj = (
        NegotiationRound.objects
        .select_related("negotiation__service_order__client__client_profile")
        .filter(pk=round_id)
        .first()
    )
    if round_obj is None:
        return  # deleted since it was queued; nothing to do

    negotiation = round_obj.negotiation
    order = negotiation.service_order
    client_auth = getattr(order.client, "client_profile", None)
    if not client_auth:
        return

    NotificationService.notify_client(
        client=client_auth,
        notification_type="negotiation_round_created",
        title="New Price Offer 💰",
        body=f"A provider offered R{round_obj.offered_price} for your request.",
        payload=NegotiationNotificationBuilder.round_created(negotiation, round_obj),
    )


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    ignore_result=True,
)
def send_client_round_notification_to_provider(self, round_id):
    print(f"[round_notify] START round_id={round_id} attempt={self.request.retries}", flush=True)

    round_obj = (
        NegotiationRound.objects
        .select_related(
            "negotiation__service_order",
            "negotiation__provider_for_negotiation__provider__sp_profile",
        )
        .filter(pk=round_id)
        .first()
    )
    if round_obj is None:
        print(f"[round_notify] EXIT: round {round_id} not found", flush=True)
        return

    negotiation = round_obj.negotiation
    provider_service = negotiation.provider_for_negotiation
    if provider_service is None:
        print(
            f"[round_notify] EXIT: negotiation {negotiation.negotiation_id} "
            f"has no provider_for_negotiation",
            flush=True,
        )
        return

    provider = provider_service.provider.sp_profile
    print(
        f"[round_notify] notifying provider_id={provider.id} "
        f"order_id={negotiation.service_order.order_id} "
        f"negotiation_id={negotiation.negotiation_id}",
        flush=True,
    )

    notification = NotificationService.notify_provider(
        provider=provider,
        notification_type="negotiation_created",
        title="New Negotiation Message 💬",
        body="The client sent you a new offer.",
        payload={
            "type": "negotiation_update",
            "action": "new_round",
            "order_id": negotiation.service_order.order_id,
            "negotiation_id": negotiation.negotiation_id,
        },
        websocket_invite=False,
    )
    print(f"[round_notify] DONE notification_id={notification.id}", flush=True)

    
    
@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    ignore_result=True,
)
def send_order_accepted_notification(self, order_id):
    order = (
        OrderService.objects
        .select_related("client__client_profile")
        .filter(pk=order_id)
        .first()
    )
    if order is None:
        return

    client = getattr(order.client, "client_profile", None)
    if client is None:
        return

    NotificationService.notify_client(
        client=client,
        notification_type="order_accepted",
        title="Order Accepted 🛠️",
        body="Your booking has been accepted.",
        payload=OrderNotificationBuilder.order_accepted(order),
        
    )


# api/bookings/tasks.py
SHIPMENT_NOTIFICATIONS = {
    "provider_arrived": {
        "title": "Provider Arrived 📍",
        "body": "Your provider has arrived.",
        "builder": OrderNotificationBuilder.provider_arrived,
    },
    "provider_in_transit": {
        "title": "Provider On The Way 🚗",
        "body": "Your provider is on the way.",
        "builder": OrderNotificationBuilder.provider_in_transit,
    },
    "provider_no_show": {
        "title": "Provider Didn't Show Up ❌",
        "body": "Your provider didn't arrive, so this booking was cancelled.",
        "builder": OrderNotificationBuilder.provider_no_show,
    },
}





NO_SHOW_GRACE = timedelta(minutes=60)



@shared_task
def cancel_no_show_shipments():
    cutoff = timezone.localtime() - NO_SHOW_GRACE
    due = (
        Q(shipment_schedule_date__lt=cutoff.date())
        | Q(shipment_schedule_date=cutoff.date(),
            shipment_schedule_time__lt=cutoff.time())
    )

    total = 0
    while True:
        changed = 0
        with transaction.atomic():
            shipments = list(
                Shipment.objects
                .select_for_update(skip_locked=True, of=("self",))
                .select_related("service_ordered__order")
                .annotate(status_lc=Lower("shipment_status"))  # "Pending" is stored capitalised
                .filter(due, status_lc__in=NO_SHOW_STATUSES)
                .exclude(service_ordered__order__status=ORDER_IN_SESSION)
                [:BATCH_SIZE]
            )
            if not shipments:
                break

            for shipment in shipments:
                if shipment.mark_no_show():
                    changed += 1

        total += changed
        if changed == 0:   # nothing progressed, avoid looping forever
            break
    return total


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    ignore_result=True,
)
def send_shipment_status_notification(self, order_id, shipment_id, event_type):
    config = SHIPMENT_NOTIFICATIONS.get(event_type)
    if config is None:
        logger.error("Unknown shipment notification type: %s", event_type)
        return

    order = (
        OrderService.objects
        .select_related("client__client_profile")
        .filter(pk=order_id)
        .first()
    )
    if order is None:
        return

    client = getattr(order.client, "client_profile", None)
    if client is None:
        return

    NotificationService.notify_client(
        client=client,
        notification_type=event_type,
        title=config["title"],
        body=config["body"],
        payload=config["builder"](order),
       
    )

    # api/bookings/tasks.py
@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    ignore_result=True,
)
def send_provider_declined_notification(
    self, order_id, provider_id, order_cancelled, remaining_providers
):
    order = (
        OrderService.objects
        .select_related("client__client_profile")
        .filter(pk=order_id)
        .first()
    )
    if order is None:
        return

    client = getattr(order.client, "client_profile", None)
    if client is None:
        return

    if order_cancelled:
        notification_type = "booking_cancelled"
        title = "Booking Cancelled ❌"
        body = (
            "All invited providers have declined your booking. "
            "Your booking has been cancelled."
        )
        base_payload = OrderNotificationBuilder.booking_cancelled(order)
    else:
        notification_type = "provider_declined"
        title = "Provider Declined"
        body = (
            "One of the invited providers declined your booking. "
            "We're still waiting for responses from the remaining providers."
        )
        base_payload = OrderNotificationBuilder.order_updated(order)

    NotificationService.notify_client(
        client=client,
        notification_type=notification_type,
        title=title,
        body=body,
        payload={
            **base_payload,
            "provider_id": provider_id,
            "remaining_providers": remaining_providers,
        },
    )



@shared_task
def auto_complete_expired_sessions():
    cutoff = timezone.now() - Session.MAX_SESSION_DURATION
    expired = Session.objects.select_related(
        "shipment__service_ordered__order"
    ).filter(
        session_status="in_session",
        checkin_time__lte=cutoff,
    )

    completed_count = 0
    for session in expired.iterator():
        if session.auto_complete():
            completed_count += 1

    return completed_count  


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    ignore_result=True,
)
def send_order_cancelled_notification(self, order_id):
    order = (
        OrderService.objects
        .select_related("provider_for_service__provider__sp_profile")
        .filter(pk=order_id)
        .first()
    )
    if order is None or order.provider_for_service is None:
        return

    sp_profile = getattr(order.provider_for_service.provider, "sp_profile", None)
    if sp_profile is None:
        return

    NotificationService.notify_provider(
        provider=sp_profile,
        notification_type="order_cancelled",
        title="Booking Cancelled ❌",
        body="The client has cancelled the booking.",
        payload=OrderNotificationBuilder.order_cancelled(order),
    )


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    ignore_result=True,
)
def notify_invited_providers_order_removed(self, order_id):
    order = OrderService.objects.filter(pk=order_id).first()
    if order is None:
        return

    for provider_id in order.invited_providers.values_list("id", flat=True):
        notify_provider_booking_removed(
            provider_id=provider_id,
            order_id=order.order_id,
        )



@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    ignore_result=True,
)
def notify_invited_providers_order_removed2(self, order_id):
    order = (
        OrderService.objects
        .select_related("provider_for_service__provider__sp_profile")
        .filter(pk=order_id)
        .first()
    )
    if order is None or order.provider_for_service is None:
        return

    provider = order.provider_for_service.provider
    if provider is None:
        return

    notify_provider_booking_removed(
        provider_id=provider.id,
        order_id=order.order_id,
    )