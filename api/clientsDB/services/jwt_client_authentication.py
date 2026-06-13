from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed
from api.clientsDB.models.models import ClientAuth

class ClientJWTAuthentication(JWTAuthentication):

    def authenticate(self, request):
        # 1. Safely extract raw header through SimpleJWT base utility
        header = self.get_header(request)
        if header is None:
            print("AUTH HEADER: None")
            return None  # Pass to DRF to handle anonymous or policy enforcement

        try:
            # 2. Extract raw token string, stripping authorization syntax (e.g., Bearer)
            raw_token = self.get_raw_token(header)
            if raw_token is None:
                print("RAW TOKEN: Extraction evaluated to None")
                return None

            print("RAW TOKEN:", raw_token)

            # 3. Verify cryptographic signature and token expiration status
            validated_token = self.get_validated_token(raw_token)
            print("VALIDATED TOKEN:", validated_token)

            # 4. Resolve the token's payload data to a database model record
            user = self.get_user(validated_token)
            print("USER:", user)

            return (user, validated_token)

        except Exception as e:
            print("JWT ERROR:", str(e))
            # Wrap standard exceptions to prevent server 500s and return clean 401s
            raise AuthenticationFailed(f"Authentication failed: {str(e)}")

    def get_user(self, validated_token):
        # Extract target claim key mapped to your client instances
        client_id = validated_token.get("client_id")
        print("CLIENT ID:", client_id)

        if not client_id:
            raise AuthenticationFailed("Invalid token: Missing client identifier claim.")

        try:
            return ClientAuth.objects.get(id=client_id)
        except ClientAuth.DoesNotExist:
            raise AuthenticationFailed("Client profile instance not found.")