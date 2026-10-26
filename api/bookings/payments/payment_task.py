import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from api.bookings.models import Payment, Payout

from . import paystack, services


logger = logging.getLogger(__name__)


@shared_task
def reconcile_pending_card_payments():
    """Webhooks get lost. Ask Paystack about initiated-but-unresolved payments. Run every ~2 min."""
    now = timezone.now()
    candidates = Payment.objects.filter(
        method=Payment.Method.CARD,
        status=Payment.Status.PENDING,
        vendor_reference__gt="",
        created_at__lte=now - timedelta(minutes=2),
    ).values_list("pk", "vendor_reference", "created_at")

    for pk, reference, created_at in candidates:
        try:
            data = paystack.verify_transaction(reference)
        except paystack.PaystackError:
            continue

        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(pk=pk)
            if payment.status != Payment.Status.PENDING:
                continue

            if data.get("status") == "success":
                services.apply_charge_success(
                    payment,
                    paid_amount_cents=data.get("amount", 0),
                    currency=data.get("currency", ""),
                )
            elif data.get("status") in ("failed", "reversed"):
                services.apply_charge_failure(payment, data.get("gateway_response", "failed"))
            elif now - created_at > services.PAYMENT_TIMEOUT:
                services.apply_charge_failure(payment, "timed_out")


@shared_task
def release_due_payouts():
    """Run every ~5 min. Sends payouts whose 5-hour dispute window has passed."""
    due_ids = list(
        Payout.objects.filter(
            status=Payout.Status.SCHEDULED, release_at__lte=timezone.now()
        ).values_list("pk", flat=True)[:100]
    )
    for payout_id in due_ids:
        services.release_payout(payout_id)