from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone

import logging

from api.clientsDB.models.models import ClientOTP
from api.clientsDB.services.otp_service import generate_otp, hash_otp

logger = logging.getLogger(__name__)


OTP_LOGIN = "login"
OTP_EMAIL_VERIFICATION = "email_verification"


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def send_client_otp_email(
    self,
    email_address,
    otp,
    purpose,
):
    """
    Send a client OTP email.

    Security:
    - Never log the OTP.
    - Never include the OTP in task logs.
    - OTP should only exist for the lifetime of this task.
    """

    if purpose == OTP_LOGIN:

        subject = "Your Plug login verification code"

        text_content = (
            f"Your Plug login verification code is: {otp}\n\n"
            "This code expires in 5 minutes.\n\n"
            "If you did not attempt to log in to your "
            "Plug account, you can safely ignore this email."
        )

        html_content = f"""
        <html>
            <body>
                <h2>Plug Login Verification</h2>

                <p>
                    Use the verification code below to
                    complete your login:
                </p>

                <h1>{otp}</h1>

                <p>
                    This code expires in <strong>5 minutes</strong>.
                </p>

                <p>
                    If you did not attempt to log in to your
                    Plug account, you can safely ignore this email.
                </p>
            </body>
        </html>
        """

    elif purpose == OTP_EMAIL_VERIFICATION:

        subject = "Verify your Plug email address"

        text_content = (
            f"Your Plug email verification code is: {otp}\n\n"
            "Enter this code in the Plug app to verify "
            "your email address.\n\n"
            "This code expires in 5 minutes.\n\n"
            "If you did not create a Plug account, "
            "you can safely ignore this email."
        )

        html_content = f"""
        <html>
            <body>
                <h2>Verify Your Plug Email</h2>

                <p>
                    Use the verification code below to
                    verify your email address:
                </p>

                <h1>{otp}</h1>

                <p>
                    This code expires in <strong>5 minutes</strong>.
                </p>

                <p>
                    If you did not create a Plug account,
                    you can safely ignore this email.
                </p>
            </body>
        </html>
        """

    else:

        raise ValueError(
            "Unsupported OTP purpose."
        )

    email = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[email_address],
    )

    email.attach_alternative(
        html_content,
        "text/html",
    )

    email.send(
        fail_silently=False
    )

    logger.info(
        "Client OTP email sent successfully."
    )



class OTPCooldownError(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(
            f"OTP requested too recently, "
            f"retry after {retry_after}s"
        )
OTP_LOGIN = "login"
OTP_EMAIL_VERIFICATION = "email_verification"

OTP_PURPOSES = {
    OTP_LOGIN,
    OTP_EMAIL_VERIFICATION,
}

@transaction.atomic
def create_client_otp(
    client,
    purpose,
    min_resend_interval_seconds=60,
):
    if purpose not in OTP_PURPOSES:
        raise ValueError(
            "Unsupported OTP purpose."
        )

    now = timezone.now()

    recent = (
        ClientOTP.objects
        .filter(
            client=client,
            purpose=purpose,
        )
        .order_by("-created_at")
        .first()
    )

    if recent:

        elapsed = (
            now - recent.created_at
        ).total_seconds()

        if elapsed < min_resend_interval_seconds:

            retry_after = (
                min_resend_interval_seconds
                - int(elapsed)
            )

            raise OTPCooldownError(
                retry_after=retry_after
            )

    # Invalidate previous active OTPs
    # for this exact purpose.
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
            now + timedelta(minutes=5)
        ),
        attempts=0,
        max_attempts=5,
    )

    return otp_request, otp