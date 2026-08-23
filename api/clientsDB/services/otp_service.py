import hashlib
import secrets

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from api.clientsDB.models import ClientOTP
import hmac
import hashlib
from django.conf import settings

def generate_otp():
    return str(
        secrets.randbelow(900000) + 100000
    )


def hash_otp(otp: str) -> str:
    return hmac.new(
        key=settings.OTP_HASH_SECRET.encode("utf-8"),
        msg=otp.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


@transaction.atomic
def create_client_otp(client, purpose):

    # Invalidate previous active OTPs
    # for the same purpose.
    ClientOTP.objects.filter(
        client=client,
        purpose=purpose,
        is_verified=False,
        is_used=False,
    ).update(
        is_used=True
    )

    otp = generate_otp()

    otp_request = ClientOTP.objects.create(
        client=client,
        purpose=purpose,
        otp_hash=hash_otp(otp),
        expires_at=(
            timezone.now()
            + timedelta(minutes=5)
        ),
        attempts=0,
        max_attempts=5,
    )

    return otp_request, otp