from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from psycopg import logger
from django.conf import settings

from api.clientsDB.services.otp_tasks import OTP_EMAIL_VERIFICATION, OTP_LOGIN


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

    else:
        raise ValueError("Unsupported OTP purpose.")

    email = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[email_address],
    )

    email.attach_alternative(html_content, "text/html")
    email.send(fail_silently=False)

    logger.info("Service provider OTP email sent successfully.")