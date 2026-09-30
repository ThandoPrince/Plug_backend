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

    if purpose == OTP_PASSWORD_RESET:
        subject = "Reset your Plug password"
  

        text_content = (
            f"Your Plug password reset code is: {otp}\n\n"
            "Enter this code in the Plug app to reset your password.\n\n"
            "This code expires in 5 minutes.\n\n"
            "If you did not request a password reset, "
            "you can safely ignore this email — your password "
            "will not be changed."
        )

        html_content = f"""
        <html>
            <body>
                <h2>Reset Your Plug Password</h2>

                <p>
                    Use the verification code below to
                    reset your password:
                </p>

                <h1>{otp}</h1>

                <p>
                    This code expires in <strong>5 minutes</strong>.
                </p>

                <p>
                    If you did not request a password reset,
                    you can safely ignore this email — your
                    password will not be changed.
                </p>
            </body>
        </html>
        """


    elif purpose == OTP_LOGIN:

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
OTP_PASSWORD_RESET = "password_reset"

OTP_PURPOSES = {
    OTP_LOGIN,
    OTP_EMAIL_VERIFICATION,
    OTP_PASSWORD_RESET,
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

@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def send_password_changed_email(self, email_address):
    subject = "Your Plug password was changed"

    text_content = (
        "Your Plug account password was just changed.\n\n"
        "If this was you, no further action is needed.\n\n"
        "If you did not make this change, reset your password immediately "
        "and contact support."
    )

    html_content = """
    <html>
        <body>
            <h2>Your Plug password was changed</h2>
            <p>Your account password was just changed.</p>
            <p>If this was you, no further action is needed.</p>
            <p><strong>If you did not make this change</strong>, reset your
            password immediately and contact support.</p>
        </body>
    </html>
    """

    email = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[email_address],
    )
    email.attach_alternative(html_content, "text/html")
    email.send(fail_silently=False)

    logger.info("Password changed notification sent.")


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def send_account_deleted_email(self, email_address):
    """
    Confirms account deletion to the ORIGINAL email address.

    Called via transaction.on_commit in delete_client_account, using
    `original_email` captured before the row was anonymized — by the time
    this task runs, client.email_address is already the
    deleted-{id}@deleted.invalid placeholder.
    """
    subject = "Your Plug account has been deleted"

    text_content = (
        "Your Plug account and associated data have been deleted, as you "
        "requested.\n\n"
        "If you did not request this, please contact support immediately — "
        "your account cannot be recovered once deletion is confirmed, but "
        "we can help investigate unauthorized access.\n\n"
        "You're welcome to create a new Plug account at any time."
    )

    html_content = """
    <html>
        <body>
            <h2>Your Plug account has been deleted</h2>
            <p>Your account and associated data have been deleted, as you requested.</p>
            <p><strong>If you did not request this</strong>, please contact support
            immediately. Your account cannot be recovered once deletion is confirmed,
            but we can help investigate unauthorized access.</p>
            <p>You're welcome to create a new Plug account at any time.</p>
        </body>
    </html>
    """

    email = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[email_address],
    )
    email.attach_alternative(html_content, "text/html")
    email.send(fail_silently=False)

    logger.info("Account deletion confirmation sent.")