from datetime import datetime, timedelta
from django.utils import timezone
from rest_framework.exceptions import ValidationError


def validate_booking_time(requested_date, requested_time):
    now = timezone.now()

    if not requested_date or not requested_time:
        return

    requested_datetime = datetime.combine(requested_date, requested_time)
    requested_datetime = timezone.make_aware(requested_datetime)

    min_allowed = now + timedelta(hours=1)

    if requested_datetime < min_allowed:
        raise ValidationError(
            "Booking must be scheduled at least 1 hour from now."
        )