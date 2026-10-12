from celery import shared_task
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.utils import timezone



from api.bookings.events.ws_events import notify_provider_booking_invite
from api.bookings.models import NegotiationRound, OrderService
from api.bookings.serializers import OrderServiceReadSerializer

from api.bookings.utils.negoctiation_even_builder import NegotiationNotificationBuilder
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


# api/bookings/tasks.py
@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
    ignore_result=True,
)
def send_client_round_notification_to_provider(self, round_id):
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
        return

    negotiation = round_obj.negotiation
    provider_service = negotiation.provider_for_negotiation
    if provider_service is None:
        return

    provider = provider_service.provider.sp_profile

    NotificationService.notify_provider(
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
        dedupe_key=f"order_accepted:{order_id}",
    )