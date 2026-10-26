import logging
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

# Adjust these imports to your app layout.
from api.bookings.events.websoket_event_emitters.shipment_event_emitters import push_payment_update, push_session_created, push_session_started
from api.bookings.models import Payment, PaymentEvent, Payout, Session, Shipment


from . import paystack


logger = logging.getLogger(__name__)

PAYOUT_DELAY = timedelta(hours=5)
PAYMENT_TIMEOUT = timedelta(minutes=10)
PLATFORM_FEE_BPS = getattr(settings, "PLATFORM_FEE_BPS", 1000)  # 1000 = 10%. Confirm your commission.

# Prints only appear while DEBUG is on (or if you set PAYMENTS_DEBUG = True in settings).
PAYMENTS_DEBUG = getattr(settings, "PAYMENTS_DEBUG", settings.DEBUG)


def _dbg(msg):
    """Debug print. Never pass secrets here: no API keys, signatures or Paystack access codes."""
    if PAYMENTS_DEBUG:
        print(f"[PAY] {msg}", flush=True)


class PaymentError(Exception):
    """Business-rule failure. `code` maps to an HTTP status in the views."""

    def __init__(self, message, code=400):
        super().__init__(message)
        self.message = message
        self.code = code


# ---------- helpers ----------

def to_cents(amount: Decimal) -> int:
    return int((Decimal(amount) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def resolve_amount_cents(order) -> int:
    amount = order.final_price or order.proposal_price or order.base_price
    cents = None
    if amount and amount > 0:
        cents = to_cents(amount)
    _dbg(
        f"resolve_amount order={order.order_id} final={order.final_price} "
        f"proposal={order.proposal_price} base={order.base_price} -> cents={cents}"
    )
    if cents is None:
        raise PaymentError("This booking has no valid price yet.", 422)
    return cents


def _is_order_client(user, order) -> bool:
   
    result = order.client.client_profile.id == user.pk
    _dbg(
        f"is_order_client user_pk={user.pk} user_type={type(user).__name__} "
        f"order={order.order_id} order.client_id={order.client_id} "
        f"client_profile_id={order.client.client_profile_id} -> {result}"
    )
    return result


def _fee_cents(amount_cents: int) -> int:
    return amount_cents * PLATFORM_FEE_BPS // 10_000


# ---------- 1. method selection ----------

def _select_payment_method_inner(*, user, shipment_id: int, method: str) -> Payment:
    _dbg(f"select_method START shipment={shipment_id} method={method} user_pk={user.pk}")

    try:
        shipment = Shipment.objects.select_for_update().get(pk=shipment_id)
    except Shipment.DoesNotExist:
        _dbg(f"select_method shipment {shipment_id} NOT FOUND")
        raise PaymentError("Booking not found.", 404)

    order = shipment.service_ordered.order
    if not _is_order_client(user, order):
        _dbg("select_method DENIED: user is not the client on this order")
        raise PaymentError("You do not have permission for this booking.", 403)

    amount_cents = resolve_amount_cents(order)

    payment = (
        Payment.objects.select_for_update()
        .filter(shipment=shipment)
        .exclude(status__in=[Payment.Status.FAILED, Payment.Status.REFUNDED])
        .first()
    )
    _dbg(
        "select_method existing payment: "
        + (f"id={payment.pk} method={payment.method} status={payment.status}" if payment else "none")
    )

    if payment and payment.status in (Payment.Status.SUCCEEDED, Payment.Status.CASH_CONFIRMED):
        _dbg("select_method REFUSED: already paid")
        raise PaymentError("This booking has already been paid.", 409)

    # Once the session has started, the payment type is locked. Choosing the
    # same method again is still fine.
    session = Session.objects.select_for_update().filter(shipment=shipment).first()
    _dbg(f"select_method session: {session.session_status if session else 'none'}")
    if session and session.session_status != "awaiting_payment":
        if not (payment and payment.method == method):
            _dbg("select_method REFUSED: session already started, method change not allowed")
            raise PaymentError(
                "The payment type can't be changed once the session has started.", 409
            )

    new_status = (
        Payment.Status.CASH_PENDING if method == Payment.Method.CASH else Payment.Status.PENDING
    )

    if payment:
        if payment.method == method:
            _dbg("select_method branch: same method chosen again, no change")
            if method == Payment.Method.CARD and not payment.vendor_reference:
                payment.amount_cents = amount_cents  # refresh snapshot, nothing charged yet
                payment.platform_fee_cents = _fee_cents(amount_cents)
                payment.save(update_fields=["amount_cents", "platform_fee_cents"])
            return payment

        # Switching method. If a Paystack transaction was already opened, retire this row.
        if payment.vendor_reference:
            _dbg(f"select_method branch: switching, retiring payment {payment.pk} (Paystack already opened)")
            payment.status = Payment.Status.FAILED
            payment.failure_reason = f"switched_to_{method}"
            payment.save(update_fields=["status", "failure_reason"])
            payment = None
        else:
            _dbg(f"select_method branch: switching {payment.method} -> {method} in place")
            payment.method = method
            payment.status = new_status
            payment.amount_cents = amount_cents
            payment.platform_fee_cents = _fee_cents(amount_cents)
            payment.save(update_fields=["method", "status", "amount_cents", "platform_fee_cents"])
            return payment

    created = Payment.objects.create(
        order=order,
        shipment=shipment,
        method=method,
        status=new_status,
        amount_cents=amount_cents,
        platform_fee_cents=_fee_cents(amount_cents),
        vendor="paystack" if method == Payment.Method.CARD else "",
    )
    _dbg(f"select_method branch: CREATED payment {created.pk} method={method} status={new_status} cents={amount_cents}")
    return created


@transaction.atomic
def select_payment_method(*, user, shipment_id: int, method: str) -> Payment:
    payment = _select_payment_method_inner(
        user=user, shipment_id=shipment_id, method=method
    )

    # Client switched to cash while the provider was already waiting: start the session.
    if method == Payment.Method.CASH:
        session = (
            Session.objects.select_for_update()
            .filter(shipment_id=shipment_id, session_status="awaiting_payment")
            .first()
        )
        if session:
            _dbg(f"select_method: cash chosen while provider waiting -> session {session.pk} to in_session")
            session.session_status = "in_session"
            session.save(update_fields=["session_status"])
            transaction.on_commit(lambda: push_session_created(shipment_id, session))

    _dbg(f"select_method DONE payment={payment.pk} method={payment.method} status={payment.status}")
    return payment



def refresh_cash_snapshot(payment):
    """Cash price can be renegotiated until the job ends, so keep the saved figures in step
    with the order's current price. Only touches unconfirmed cash payments."""
    if payment.method != Payment.Method.CASH or payment.status != Payment.Status.CASH_PENDING:
        return payment
    try:
        cents = resolve_amount_cents(payment.order)
    except PaymentError:
        return payment
    fee = _fee_cents(cents)
    if (cents, fee) != (payment.amount_cents, payment.platform_fee_cents):
        Payment.objects.filter(pk=payment.pk, status=Payment.Status.CASH_PENDING).update(
            amount_cents=cents, platform_fee_cents=fee
        )
        payment.amount_cents, payment.platform_fee_cents = cents, fee
    return payment
 
 
@transaction.atomic
def confirm_cash_received(*, user, shipment_id: int) -> Payment:
    """Provider confirms the client handed over the cash."""
    _dbg(f"confirm_cash START shipment={shipment_id} user_pk={user.pk}")
 
    payment = (
        Payment.objects.select_for_update()
        .filter(shipment_id=shipment_id)
        .exclude(status__in=[Payment.Status.FAILED, Payment.Status.REFUNDED])
        .order_by("-created_at")
        .first()
    )
    if payment is None or payment.order.provider_for_service.provider.sp_profile != user:
        raise PaymentError("No payment for this booking.", 404)
 
    if payment.method != Payment.Method.CASH:
        raise PaymentError("This booking was not paid in cash.", 409)
 
    if payment.status == Payment.Status.CASH_CONFIRMED:
        _dbg("confirm_cash: already confirmed, nothing to do")
        return payment
    if payment.status != Payment.Status.CASH_PENDING:
        raise PaymentError(f"Payment is {payment.status}.", 409)
 
    session = Session.objects.filter(shipment_id=shipment_id).first()
    if session is None or session.session_status == "awaiting_payment":
        raise PaymentError("The session has not started yet.", 409)
 
    payment.amount_cents = resolve_amount_cents(payment.order)
    payment.platform_fee_cents = _fee_cents(payment.amount_cents)
    payment.status = Payment.Status.CASH_CONFIRMED
    payment.paid_at = timezone.now()
    payment.save(update_fields=["amount_cents", "platform_fee_cents", "status", "paid_at"])
    _dbg(f"confirm_cash DONE payment={payment.pk} cents={payment.amount_cents} fee={payment.platform_fee_cents}")
 
    transaction.on_commit(lambda: push_payment_update(payment.shipment_id, payment))
    return payment

# ---------- 2. card initiation (client, after provider scans) ----------

@transaction.atomic
def initiate_card_payment(*, user, payment_id: int) -> Payment:
    _dbg(f"initiate START payment={payment_id} user_pk={user.pk}")

    try:
        payment = Payment.objects.select_for_update().get(pk=payment_id)
    except Payment.DoesNotExist:
        _dbg("initiate payment NOT FOUND")
        raise PaymentError("Payment not found.", 404)

    order = payment.order
    if not _is_order_client(user, order):
        _dbg("initiate DENIED: not the client")
        raise PaymentError("You do not have permission for this payment.", 403)
    if payment.method != Payment.Method.CARD:
        _dbg(f"initiate REFUSED: method is {payment.method}")
        raise PaymentError("This payment is not a card payment.", 409)
    if payment.status != Payment.Status.PENDING:
        _dbg(f"initiate REFUSED: status is {payment.status}")
        raise PaymentError(f"Payment is {payment.status}.", 409)

    session = Session.objects.filter(shipment=payment.shipment).first()
    _dbg(f"initiate session: {session.session_status if session else 'none'}")
    if not session or session.session_status != "awaiting_payment":
        raise PaymentError("The provider has not checked in yet.", 409)

    # Already opened: return the stored checkout details (Paystack rejects duplicate references).
    if payment.vendor_reference and payment.vendor_access_code:
        _dbg(f"initiate: already opened, returning stored checkout ref={payment.vendor_reference}")
        return payment

    # Re-snapshot in case the price was renegotiated before any charge existed.
    payment.amount_cents = resolve_amount_cents(order)
    payment.platform_fee_cents = _fee_cents(payment.amount_cents)

    reference = f"pay-{payment.idempotency_key}"
    _dbg(f"initiate: calling Paystack ref={reference} cents={payment.amount_cents} email_set={bool(user.email_address)}")
    try:
        data = paystack.initialize_transaction(
            email=user.email_address,
            amount_cents=payment.amount_cents,
            reference=reference,
            metadata={
                "payment_id": payment.pk,
                "shipment_id": payment.shipment_id,
                "order_id": order.order_id,
            },
        )
    except paystack.PaystackError as exc:
        _dbg(f"initiate: Paystack ERROR: {exc}")
        raise PaymentError(str(exc), 502)

    payment.vendor = "paystack"
    payment.vendor_reference = data["reference"]
    payment.vendor_access_code = data["access_code"]
    payment.vendor_checkout_url = data["authorization_url"]
    payment.save()
    _dbg(f"initiate DONE ref={payment.vendor_reference} (access code and URL saved, not printed)")
    return payment


# ---------- 3. success / failure (webhook + reconciliation) ----------

def apply_charge_success(payment: Payment, *, paid_amount_cents: int, currency: str):
    """Call inside transaction.atomic with `payment` locked via select_for_update."""
    _dbg(
        f"charge_success payment={payment.pk} status={payment.status} "
        f"expected={payment.amount_cents} paid={paid_amount_cents} currency={currency}"
    )
    if payment.status == Payment.Status.SUCCEEDED:
        _dbg("charge_success: already succeeded, ignoring")
        return

    if paid_amount_cents != payment.amount_cents or currency != paystack.CURRENCY:
        logger.error(
            "Payment %s amount/currency mismatch: expected %s %s, got %s %s",
            payment.pk, payment.amount_cents, paystack.CURRENCY, paid_amount_cents, currency,
        )
        _dbg("charge_success: MISMATCH, marking payment failed")
        payment.status = Payment.Status.FAILED
        payment.failure_reason = "amount_mismatch"
        payment.save(update_fields=["status", "failure_reason"])
        return

    payment.status = Payment.Status.SUCCEEDED
    payment.paid_at = timezone.now()
    payment.save(update_fields=["status", "paid_at"])

    session = Session.objects.select_for_update().filter(shipment=payment.shipment).first()
    _dbg(f"charge_success: session is {session.session_status if session else 'none'}")
    if session and session.session_status == "awaiting_payment":
        session.session_status = "in_session"
        session.save(update_fields=["session_status"])
        _dbg(f"charge_success: session {session.pk} -> in_session")
        transaction.on_commit(
            lambda: push_session_created(payment.shipment_id, session)
        )
    transaction.on_commit(lambda: push_payment_update(payment.shipment_id, payment))


def apply_charge_failure(payment: Payment, reason: str):
    _dbg(f"charge_failure payment={payment.pk} status={payment.status} reason={reason}")
    if payment.status != Payment.Status.PENDING:
        return
    payment.status = Payment.Status.FAILED
    payment.failure_reason = reason[:255]
    payment.save(update_fields=["status", "failure_reason"])
    transaction.on_commit(lambda: push_payment_update(payment.shipment_id, payment))

@transaction.atomic
def verify_card_payment(*, user, payment_id: int) -> Payment:
    """Client asks us to check with Paystack whether this payment went through.
    Same success logic as the webhook, so whichever arrives first wins and the other is a no-op."""
    _dbg(f"verify START payment={payment_id} user_pk={user.pk}")

    try:
        payment = Payment.objects.select_for_update().get(pk=payment_id)
    except Payment.DoesNotExist:
        raise PaymentError("Payment not found.", 404)

    if not _is_order_client(user, payment.order):
        raise PaymentError("You do not have permission for this payment.", 403)
    if payment.method != Payment.Method.CARD:
        raise PaymentError("This payment is not a card payment.", 409)

    # Already settled, or checkout was never opened: nothing to ask Paystack.
    if payment.status != Payment.Status.PENDING or not payment.vendor_reference:
        _dbg(f"verify: nothing to do (status={payment.status}, ref_set={bool(payment.vendor_reference)})")
        return payment

    try:
        data = paystack.verify_transaction(payment.vendor_reference)
    except paystack.PaystackError as exc:
        _dbg(f"verify: Paystack ERROR: {exc}")
        raise PaymentError(str(exc), 502)

    pstatus = data.get("status")
    _dbg(
        f"verify: Paystack says status={pstatus} amount={data.get('amount')} "
        f"currency={data.get('currency')} ref_matches={data.get('reference') == payment.vendor_reference}"
    )

    if data.get("reference") != payment.vendor_reference:
        raise PaymentError("Payment reference mismatch.", 409)

    if pstatus == "success":
        apply_charge_success(
            payment,
            paid_amount_cents=data.get("amount", 0),
            currency=data.get("currency", ""),
        )
    elif pstatus in ("failed", "reversed"):
        apply_charge_failure(payment, data.get("gateway_response") or pstatus)
    # "abandoned" / "ongoing" / "pending": the client hasn't finished paying yet, leave it pending.

    return payment


def handle_webhook_event(payload: dict):
    event = payload.get("event", "")
    data = payload.get("data", {})
    ref = data.get("reference", "")
    event_id = f"{event}:{data.get('id') or ref}"
    _dbg(f"webhook event={event} ref={ref} event_id={event_id}")

    with transaction.atomic():
        _, created = PaymentEvent.objects.get_or_create(
            vendor_event_id=event_id, defaults={"payload": payload}
        )
        if not created:
            _dbg("webhook: duplicate delivery, ignored")
            return  # duplicate delivery

        if event == "charge.success":
            payment = (
                Payment.objects.select_for_update().filter(vendor_reference=ref).first()
            )
            if not payment:
                logger.warning("charge.success for unknown reference %s", ref)
                _dbg(f"webhook: NO payment with vendor_reference={ref}")
                return
            apply_charge_success(
                payment,
                paid_amount_cents=data.get("amount", 0),
                currency=data.get("currency", ""),
            )

        elif event in ("transfer.success", "transfer.failed", "transfer.reversed"):
            payout = Payout.objects.select_for_update().filter(vendor_reference=ref).first()
            if not payout:
                _dbg(f"webhook: NO payout with vendor_reference={ref}")
                return
            payout.status = (
                Payout.Status.PAID if event == "transfer.success" else Payout.Status.FAILED
            )
            payout.save(update_fields=["status"])
            _dbg(f"webhook: payout {payout.pk} -> {payout.status}")
        else:
            _dbg(f"webhook: event type {event} not handled (fine)")


# ---------- 4. payouts ----------

def schedule_payout(payment: Payment, completed_at=None) -> Payout | None:
    """Call when a session is completed. Card payments only; cash has nothing to release."""
    if payment.method != Payment.Method.CARD or payment.status != Payment.Status.SUCCEEDED:
        _dbg(f"schedule_payout: skipped payment={payment.pk} method={payment.method} status={payment.status}")
        return None
    completed_at = completed_at or timezone.now()
    provider = payment.order.provider_for_service.provider
    payout, created = Payout.objects.get_or_create(
        payment=payment,
        defaults={
            "provider": provider,
            "amount_cents": payment.amount_cents - payment.platform_fee_cents,
            "release_at": completed_at + PAYOUT_DELAY,
        },
    )
    _dbg(f"schedule_payout: payout={payout.pk} created={created} release_at={payout.release_at}")
    return payout


def release_payout(payout_id: int):
    with transaction.atomic():
        payout = Payout.objects.select_for_update(skip_locked=True).filter(
            pk=payout_id, status=Payout.Status.SCHEDULED
        ).first()
        if not payout:
            return
        recipient = getattr(payout.provider, "paystack_recipient_code", "")  # TODO: bank onboarding
        if not recipient:
            payout.status = Payout.Status.ON_HOLD
            payout.save(update_fields=["status"])
            logger.warning("Payout %s on hold: provider has no recipient code", payout.pk)
            _dbg(f"release_payout {payout.pk}: ON HOLD, no recipient code")
            return
        payout.status = Payout.Status.PROCESSING
        payout.vendor_reference = f"payout-{payout.pk}"
        payout.save(update_fields=["status", "vendor_reference"])

    try:
        paystack.initiate_transfer(
            amount_cents=payout.amount_cents,
            recipient_code=recipient,
            reference=payout.vendor_reference,
            reason=f"Payout for booking {payout.payment.shipment_id}",
        )
        _dbg(f"release_payout {payout.pk}: transfer started")
    except paystack.PaystackError:
        Payout.objects.filter(pk=payout.pk).update(status=Payout.Status.FAILED)
        logger.exception("Payout %s transfer failed", payout.pk)
        _dbg(f"release_payout {payout.pk}: transfer FAILED")