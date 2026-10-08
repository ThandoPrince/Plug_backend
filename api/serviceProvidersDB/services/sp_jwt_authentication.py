from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed
from api.serviceProvidersDB.models import SPProfile


class SPJWTAuthentication(JWTAuthentication):

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
            raise AuthenticationFailed("Invalid or expired token.")

        user = self.get_user(validated_token)  # raises AuthenticationFailed itself
        return (user, validated_token)

    def get_user(self, validated_token):
        # Verification tokens (e.g. purpose="password_reset") must never
        # work as session tokens.
        if validated_token.get("purpose"):
            raise AuthenticationFailed("Invalid token.")

        if validated_token.get("user_type") != "service_provider":
            raise AuthenticationFailed("Invalid token.")

        sp_id = validated_token.get("sp_id")
        if not sp_id:
            raise AuthenticationFailed("Invalid token.")

        try:
            sp = SPProfile.objects.get(id=sp_id)
        except SPProfile.DoesNotExist:
            raise AuthenticationFailed("Invalid token.")

        if not sp.is_active:
            raise AuthenticationFailed("Invalid token.")

        # Session version: a password change/reset bumps this and
        # invalidates every token issued before it.
        if validated_token.get("sv", 0) != sp.session_version:
            raise AuthenticationFailed("Session expired. Please log in again.")

        return sp