# api/common/ws_auth.py
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken

from api.clientsDB.models.models import ClientAuth
from api.serviceProvidersDB.models import SPProfile

jwt_auth = JWTAuthentication()


def authenticate_ws_token(token: str):
    """
    Shared WebSocket JWT authentication (client + provider).
    Returns (user, role) or (None, None). Never raises for bad tokens.
    """
    try:
        validated_token = jwt_auth.get_validated_token(token)
    except (TokenError, InvalidToken):
        return None, None

    # Verification tokens (e.g. purpose="password_reset") are not sessions
    if validated_token.get("purpose"):
        return None, None

    client_id = validated_token.get("client_id")
    sp_id = validated_token.get("sp_id")

    if client_id:
        if validated_token.get("user_type") != "client":
            return None, None

        client = ClientAuth.objects.filter(id=client_id).first()
        if client is None:
            return None, None

        if not client.is_active:
            return None, None

        # Revoked by a password change/reset
        if validated_token.get("sv", 0) != client.session_version:
            return None, None

        return client, "client"

    if sp_id:
        if validated_token.get("user_type") != "service_provider":
            return None, None

        provider = SPProfile.objects.filter(id=sp_id).first()
        if provider is None:
            return None, None

        if not provider.is_active:
            return None, None

        # Revoked by a password change/reset
        if validated_token.get("sv", 0) != provider.session_version:
            return None, None

        return provider, "provider"

    return None, None