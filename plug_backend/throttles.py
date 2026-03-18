from rest_framework.throttling import UserRateThrottle, AnonRateThrottle


class AuthThrottle(AnonRateThrottle):
    scope = "auth"


class RegisterThrottle(AnonRateThrottle):
    scope = "register"


class PublicReadThrottle(AnonRateThrottle):
    scope = "public_read"


class UserReadThrottle(UserRateThrottle):
    scope = "user_read"


class HeavyReadThrottle(UserRateThrottle):
    scope = "heavy_read"


class LiveLocationWriteThrottle(UserRateThrottle):
    scope = "live_location_write"


class LiveLocationReadThrottle(UserRateThrottle):
    scope = "live_location_read"


class UploadThrottle(UserRateThrottle):
    scope = "upload"


class ProfileWriteThrottle(UserRateThrottle):
    scope = "profile_write"


class BookingLikeWriteThrottle(UserRateThrottle):
    scope = "booking_like_write"