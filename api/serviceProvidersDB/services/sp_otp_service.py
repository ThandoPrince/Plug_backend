from datetime import timedelta
from rest_framework_simplejwt.tokens import AccessToken


def generate_sp_login_token(sp, otp_request):
    """
    Short-lived token scoped only to completing login OTP verification
    for this specific challenge. Not a session/access token.
    """
    token = AccessToken()
    token["sp_id"] = sp.id
    token["purpose"] = "login"
    token["request_id"] = str(otp_request.request_id)
    token.set_exp(lifetime=timedelta(minutes=15))
    return str(token)


def generate_sp_email_verification_token(sp, otp_request):
    """
    Short-lived token scoped only to completing email verification
    for this specific OTP challenge. Not a session/access token.
    """
    token = AccessToken()
    token["sp_id"] = sp.id
    token["purpose"] = "email_verification"
    token["request_id"] = str(otp_request.request_id)
    token.set_exp(lifetime=timedelta(minutes=15))
    return str(token)