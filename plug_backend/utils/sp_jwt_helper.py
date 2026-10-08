from rest_framework_simplejwt.tokens import RefreshToken


def generate_sp_tokens(sp_profile):
    refresh = RefreshToken()

    refresh["sp_id"] = sp_profile.id
    refresh["email"] = sp_profile.email_address
    refresh["mobile_number"] = sp_profile.mobile_number
    refresh["user_type"] = "service_provider"
    refresh["sv"] = sp_profile.session_version  # ADD

    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }