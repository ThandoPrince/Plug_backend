from datetime import timedelta

from django.db import transaction
from django.utils import timezone


from api.clientsDB.services.otp_service import (
    generate_otp,
    hash_otp,


)
from api.clientsDB.services.otp_tasks import OTP_PURPOSES, OTPCooldownError
from api.serviceProvidersDB.models import SPOTP


@transaction.atomic
def create_sp_otp(
    service_provider,
    purpose,
    min_resend_interval_seconds=60,
):
    if purpose not in OTP_PURPOSES:
        raise ValueError("Unsupported OTP purpose.")

    now = timezone.now()

    recent = (
        SPOTP.objects
        .filter(
            service_provider=service_provider,
            purpose=purpose,
        )
        .order_by("-created_at")
        .first()
    )

    if recent:
        elapsed = (now - recent.created_at).total_seconds()

        if elapsed < min_resend_interval_seconds:
            retry_after = min_resend_interval_seconds - int(elapsed)
            raise OTPCooldownError(retry_after=retry_after)

    # Invalidate previous active OTPs for this exact purpose.
    SPOTP.objects.filter(
        service_provider=service_provider,
        purpose=purpose,
        is_verified=False,
        is_used=False,
    ).update(is_used=True)

    otp = generate_otp()

    otp_request = SPOTP.objects.create(
        service_provider=service_provider,
        purpose=purpose,
        otp_hash=hash_otp(otp),
        expires_at=now + timedelta(minutes=5),
        attempts=0,
        max_attempts=5,
    )

    return otp_request, otp