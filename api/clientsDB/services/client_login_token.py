from datetime import timedelta
from rest_framework_simplejwt.tokens import AccessToken


def generate_email_login_tokenn(client, otp_request):
    """
    Short-lived token scoped only to completing email verification
    for this specific OTP challenge. Not a login/access token.
    """
    token = AccessToken()
    token["client_id"] = client.id
    token["purpose"] = "login"
    token["request_id"] = str(otp_request.request_id)
    token.set_exp(lifetime=timedelta(minutes=6))
    return str(token)