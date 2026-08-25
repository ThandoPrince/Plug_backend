from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError


class EmailVerificationTokenAuthentication(BaseAuthentication):
    """
    Accepts ONLY tokens minted by generate_email_verification_token.
    Deliberately separate from ClientJWTAuthentication — this can
    never be used as a login/session credential.
    """

    def authenticate(self, request):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None  # no credentials supplied

        raw_token = auth_header[len("Bearer "):].strip()

        try:
            validated_token = AccessToken(raw_token)
        except TokenError:
            raise AuthenticationFailed("Invalid or expired verification code.")

        if validated_token.get("purpose") != "email_verification":
            raise AuthenticationFailed("Invalid or expired verification code.")

        return (validated_token, validated_token)