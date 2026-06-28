# api/common/ws_auth.py
from rest_framework_simplejwt.authentication import JWTAuthentication
from api.clientsDB.models.models import ClientAuth
from api.serviceProvidersDB.models import SPProfile
from rest_framework_simplejwt.exceptions import TokenError


jwt_auth = JWTAuthentication()


def authenticate_ws_token(token: str):
    """
    Shared WebSocket JWT authentication (client + provider)
    """

    try:
        validated_token = jwt_auth.get_validated_token(token)
    except TokenError:
        return None, None

    client_id = validated_token.get("client_id")
    sp_id = validated_token.get("sp_id")

    if client_id:
        return ClientAuth.objects.get(id=client_id), "client"

    if sp_id:
        return SPProfile.objects.get(id=sp_id), "provider"

    return None, None