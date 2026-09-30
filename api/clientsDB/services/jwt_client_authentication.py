from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed
from api.clientsDB.models.models import ClientAuth


class ClientJWTAuthentication(JWTAuthentication):

    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            return None

        raw_token = self.get_raw_token(header)
        if raw_token is None:
            return None

        try:
            validated_token = self.get_validated_token(raw_token)
        except Exception:
            # Don't echo internal error text back to the caller
            raise AuthenticationFailed("Invalid or expired token.")

        user = self.get_user(validated_token)  # raises AuthenticationFailed itself
        return (user, validated_token)

    def get_user(self, validated_token):
        # Verification tokens (e.g. purpose="password_reset") must never
        # work as session tokens.
        if validated_token.get("purpose"):
            raise AuthenticationFailed("Invalid token.")

        if validated_token.get("user_type") != "client":
            raise AuthenticationFailed("Invalid token.")

        client_id = validated_token.get("client_id")
        if not client_id:
            raise AuthenticationFailed("Invalid token.")

        try:
            client = ClientAuth.objects.get(id=client_id)
        except ClientAuth.DoesNotExist:
            raise AuthenticationFailed("Invalid token.")

        # Session version: a password change/reset bumps this and
        # invalidates every token issued before it.
        if validated_token.get("sv", 0) != client.session_version:
            raise AuthenticationFailed("Session expired. Please log in again.")

        return client