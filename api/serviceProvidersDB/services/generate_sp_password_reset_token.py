from datetime import timedelta
from rest_framework_simplejwt.tokens import AccessToken


def generate_sp_password_reset_token(sp, otp_request):
    """
    Short-lived token scoped only to completing a password reset
    for this specific OTP challenge. Not a login/access token.
    """
    token = AccessToken()
    token["sp_id"] = sp.id
    token["purpose"] = "password_reset"
    token["request_id"] = str(otp_request.request_id)
    token.set_exp(lifetime=timedelta(minutes=15))
    return str(token)