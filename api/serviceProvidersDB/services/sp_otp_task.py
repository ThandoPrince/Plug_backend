import logging
from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from api.clientsDB.services.otp_tasks import (
    OTP_EMAIL_VERIFICATION,
    OTP_LOGIN,
    OTP_PASSWORD_RESET,
)

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def send_sp_otp_email(self, email_address, otp, purpose):
    """
    Send a service provider OTP email.

    Security:
    - Never log the OTP.
    - Never include the OTP in task logs.
    - OTP should only exist for the lifetime of this task.
    """

    if purpose == OTP_LOGIN:
        subject = "Your Plug provider login verification code"
        text_content = (
            f"Your Plug provider login verification code is: {otp}\n\n"
            "This code expires in 5 minutes.\n\n"
            "If you did not attempt to log in to your "
            "Plug provider account, you can safely ignore this email."
        )
        html_content = f"""
        <html>
            <body>
                <h2>Plug Provider Login Verification</h2>
                <p>Use the verification code below to complete your login:</p>
                <h1>{otp}</h1>
                <p>This code expires in <strong>5 minutes</strong>.</p>
                <p>
                    If you did not attempt to log in to your
                    Plug provider account, you can safely ignore this email.
                </p>
            </body>
        </html>
        """

    elif purpose == OTP_EMAIL_VERIFICATION:
        subject = "Verify your Plug provider email address"
        text_content = (
            f"Your Plug provider email verification code is: {otp}\n\n"
            "Enter this code in the Plug app to verify "
            "your provider email address.\n\n"
            "This code expires in 5 minutes.\n\n"
            "If you did not create a Plug provider account, "
            "you can safely ignore this email."
        )
        html_content = f"""
        <html>
            <body>
                <h2>Verify Your Plug Provider Email</h2>
                <p>Use the verification code below to verify your email address:</p>
                <h1>{otp}</h1>
                <p>This code expires in <strong>5 minutes</strong>.</p>
                <p>
                    If you did not create a Plug provider account,
                    you can safely ignore this email.
                </p>
            </body>
        </html>
        """

    elif purpose == OTP_PASSWORD_RESET:
        subject = "Reset your Plug provider password"
        text_content = (
            f"Your Plug provider password reset code is: {otp}\n\n"
            "Enter this code in the Plug app to reset your password.\n\n"
            "This code expires in 5 minutes.\n\n"
            "If you did not request a password reset, "
            "you can safely ignore this email — your password "
            "will not be changed."
        )
        html_content = f"""
        <html>
            <body>
                <h2>Reset Your Plug Provider Password</h2>
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

    else:
        raise ValueError(f"Unsupported OTP purpose: {purpose}")

    email = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[email_address],
    )

    email.attach_alternative(html_content, "text/html")
    email.send(fail_silently=False)

    logger.info("Service provider OTP email sent successfully.")



@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def send_sp_password_changed_email(self, email_address):
    subject = "Your Plug provider password was changed"

    text_content = (
        "Your Plug provider account password was just changed.\n\n"
        "If this was you, no further action is needed.\n\n"
        "If you did not make this change, reset your password immediately "
        "and contact support."
    )

    html_content = """
    <html>
        <body>
            <h2>Your Plug Provider Password Was Changed</h2>
            <p>Your provider account password was just changed.</p>
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

    logger.info("Service provider password changed notification sent.")


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def send_sp_account_deleted_email(self, email_address):
    subject = "Your Plug provider account has been deleted"

    text_content = (
        "Your Plug provider account and associated data have been deleted.\n\n"
        "If you did not request this, contact support immediately."
    )

    html_content = """
    <html>
        <body>
            <h2>Your Plug Provider Account Has Been Deleted</h2>
            <p>Your account and associated data have been deleted, as requested.</p>
            <p><strong>If you did not request this</strong>, contact support immediately.</p>
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