from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed
from api.serviceProvidersDB.models import SPProfile

class SPJWTAuthentication(JWTAuthentication):

    def authenticate(self, request):
        # 1. Safely extract the raw header using SimpleJWT native utilities
        header = self.get_header(request)
        if header is None:
            print("AUTH HEADER: None")
            return None  # Let DRF handle anonymous request routing natively

        try:
            # 2. Extract token string out of structural syntax rules (e.g., Bearer <token>)
            raw_token = self.get_raw_token(header)
            if raw_token is None:
                print("RAW TOKEN: Extraction evaluated to None")
                return None

            # print("RAW TOKEN:", raw_token)

            # 3. Assert signature integrity and checking expiration limits
            validated_token = self.get_validated_token(raw_token)
            # print("VALIDATED TOKEN:", validated_token)

            # 4. Resolve token custom payload claims down to the database record
            user = self.get_user(validated_token)
            # print("SP USER:", user)

            return (user, validated_token)

        except Exception as e:
            print("JWT ERROR:", str(e))
            # Critical: Raise DRF standard tracking exceptions to enforce clean 401 JSON API wrappers
            raise AuthenticationFailed(f"Authentication failed: {str(e)}")

    def get_user(self, validated_token):
        # Map target identity claim from payload dictionary keys
        sp_id = validated_token.get("sp_id")
        # print("SP ID:", sp_id)

        if not sp_id:
            raise AuthenticationFailed("Invalid token: Missing service provider claim identifier.")

        try:
            return SPProfile.objects.get(id=sp_id)
        except SPProfile.DoesNotExist:
            raise AuthenticationFailed("Service Provider profile instance not found.")