from django.utils import timezone
from datetime import timedelta
from api.bookings.models import SessionToken

def create_token_for_delivered_shipment(shipment):
    # Don't create multiple tokens for the same shipment
    if SessionToken.objects.filter(shipment=shipment, session__isnull=True).exists():
        return

    SessionToken.objects.create(
        shipment=shipment,
        token_expiry=timezone.now() + timedelta(minutes=15)
    )
