from datetime import timedelta
from rest_framework_simplejwt.tokens import AccessToken


def generate_password_reset_token(client, otp_request):
    token = AccessToken()
    token.set_exp(lifetime=timedelta(minutes=10))
    token["purpose"] = "password_reset"
    token["client_id"] = client.id
    token["request_id"] = str(otp_request.request_id)
    return str(token)