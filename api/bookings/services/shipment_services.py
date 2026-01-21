from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from api.bookings.models import Session, SessionToken


@transaction.atomic
def create_session_with_qr(shipment):
    # Lock shipment row to avoid race conditions
    shipment = shipment.__class__.objects.select_for_update().get(
        pk=shipment.pk
    )

    # ✅ Correct existence check for OneToOneField
    if Session.objects.filter(Shipment=shipment).exists():
        return shipment.sessions

    session = Session.objects.create(
        Shipment=shipment,
        checkin_location={}
    )

    SessionToken.objects.create(
        session=session,
        token_expiry=timezone.now() + timedelta(minutes=15)
    )

    return session
