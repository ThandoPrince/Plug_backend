from rest_framework_simplejwt.tokens import RefreshToken


def generate_client_tokens(client):
    refresh = RefreshToken()

    refresh["client_id"] = client.id
    refresh["email"] = client.email_address
    refresh["mobile_number"] = client.mobile_number
    refresh["user_type"] = "client"
    refresh["sv"] = client.session_version 

    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }