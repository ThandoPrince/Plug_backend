from pathlib import Path
import os
from dotenv import load_dotenv
import dj_database_url
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")





def get_env(name: str, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value

SECRET_KEY = get_env("DJANGO_SECRET_KEY", required=True)
DEBUG = get_env("DJANGO_DEBUG", "False").lower() == "true"

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}


EMAIL_BACKEND = "anymail.backends.resend.EmailBackend"
ANYMAIL = {
    "RESEND_API_KEY": get_env("RESEND_API_KEY", required=not DEBUG),
}

EMAIL_HOST = get_env("EMAIL_HOST", required=not DEBUG)
EMAIL_PORT = int(get_env("EMAIL_PORT", "587"))
EMAIL_USE_TLS = get_env("EMAIL_USE_TLS", "True").lower() == "true"
EMAIL_USE_SSL = get_env("EMAIL_USE_SSL", "False").lower() == "true"
EMAIL_HOST_USER = get_env("EMAIL_HOST_USER", required=not DEBUG)
EMAIL_HOST_PASSWORD = get_env("EMAIL_HOST_PASSWORD", required=not DEBUG)
DEFAULT_FROM_EMAIL = get_env("DEFAULT_FROM_EMAIL", "support@plugprovider.co.za")
CLOUDFLARE_ORIGIN_SECRET = get_env("CLOUDFLARE_ORIGIN_SECRET", required=not DEBUG)

EMAIL_TIMEOUT = 10


AI_API_KEY = get_env("AI_API_KEY")
AI_KYC_API_URL = get_env("AI_KYC_API_URL")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

ALLOWED_HOSTS = [
    host.strip()
    for host in get_env(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1,api.plugprovider.co.za,api.plugprovider.co.za,www.api.plugprovider.co.za"
    ).split(",")
    if host.strip()
]
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in get_env(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "http://127.0.0.1,http://localhost,https://api.plugprovider.co.za,https://www.api.plugprovider.co.za"
    ).split(",")
    if origin.strip()
]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = []

INSTALLED_APPS = [
    "daphne",
    "channels",
    "corsheaders",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "rest_framework",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework.authtoken",
    "anymail",
    "api.clientsDB",
    "api.serviceProvidersDB",
    "api.bookings",
    "api.posts",
    "api.audits",
    "csp",
]

MIDDLEWARE = [
    "csp.middleware.CSPMiddleware",
    "plug_backend.utils.middleware.middleware.CloudflareOnlyMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "plug_backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


ASGI_APPLICATION = "plug_backend.asgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default=(
            f"postgresql://{get_env('DB_USER', 'postgres')}:"
            f"{get_env('DB_PASSWORD', '')}@"
            f"{get_env('DB_HOST', '127.0.0.1')}:"
            f"{get_env('DB_PORT', '5432')}/"
            f"{get_env('DB_NAME', 'plug_db')}"
        ),
        conn_max_age=0,
        ssl_require=not DEBUG,
    )
}



AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

HMS_APP_ID = get_env("HMS_APP_ID", "")
OTP_HASH_SECRET = get_env("OTP_HASH_SECRET", required=True)
HMS_APP_SECRET = get_env("HMS_APP_SECRET", "")
PROVIDER_HMS_APP_ID = get_env("PROVIDER_HMS_APP_ID", "")
PROVIDER_HMS_APP_SECRET = get_env("PROVIDER_HMS_APP_SECRET", "")
FIREBASE_KEY_PATH = get_env(
    "FIREBASE_KEY_PATH",
    str(BASE_DIR / "config" / "firebase-adminsdk.json")
)

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Johannesburg"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [
    BASE_DIR / "plug_backend" / "static",
]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "30/min",
        "user": "100/min",
        "account_delete": "3/day",
        "auth": "5/min",
        "client_otp": "3/minute",
        "client_registration": "3/minute",
        "register": "3/min",
        "public_read": "30/min",
        "user_read": "60/min",
        "heavy_read": "20/min",
        "live_location_write": "30/min",
        "live_location_read": "20/min",
        "upload": "10/min",
        "profile_write": "20/min",
        "booking_like_write": "15/min",
        "account_delete": "3/day",
    },
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "EXCEPTION_HANDLER": "plug_backend.exceptions.custom_exception_handler",

}

REDIS_URL = get_env("REDIS_URL", "") 

if DEBUG or not REDIS_URL:
    # Local or fallback (no Redis)
    CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
        },
    },
}
else:
    # Production with Redis
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [REDIS_URL],
            },
        }
    }

SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_CONTENT_TYPE_NOSNIFF = True

SESSION_GEOFENCE_RADIUS_METERS = int(get_env("SESSION_GEOFENCE_RADIUS_METERS", "45"))
SESSION_GEOFENCE_GRACE_SECONDS = int(get_env("SESSION_GEOFENCE_GRACE_SECONDS", "120"))
SESSION_GEOFENCE_PING_INTERVAL_SECONDS = int(get_env("SESSION_GEOFENCE_PING_INTERVAL_SECONDS", "20"))


# CELERY_BROKER_URL = "redis://redis:6379/0"
CELERY_BROKER_URL = get_env("REDIS_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = get_env("REDIS_URL", "redis://127.0.0.1:6379/0")

CELERY_ACCEPT_CONTENT = ["json"]

CELERY_TASK_SERIALIZER = "json"
CELERY_TASK_IGNORE_RESULT = True          # you almost certainly never call .get()
CELERY_BROKER_POOL_LIMIT = 2
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

CELERY_RESULT_SERIALIZER = "json"

CELERY_TIMEZONE = "Africa/Johannesburg"


CELERY_BEAT_SCHEDULE = {
    "auto-reschedule-orders": {
        "task": "bookings.tasks.auto_reschedule_orders",
        "schedule": 60.0,
    },
    "expire-overdue-orders": {
        "task": "bookings.tasks.expire_overdue_orders",
        "schedule": 300.0,   # every 5 minutes is plenty for a 1-day window
    },
}


# ============================================================================
# Content Security Policy (CSP)
# ============================================================================

CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ("'self'",),

        "script-src": (
            "'self'",
        ),

        "style-src": (
            "'self'",
            "'unsafe-inline'",
        ),

        "img-src": (
            "'self'",
            "data:",
            "https:",
        ),

        "font-src": (
            "'self'",
            "https:",
        ),

        "connect-src": (
            "'self'",
            "https://fcm.googleapis.com",
            "https://firebaseinstallations.googleapis.com",
            "https://firebase.googleapis.com",
        ),

        "object-src": ("'none'",),
        "base-uri": ("'self'",),
        "frame-ancestors": ("'none'",),
        "form-action": ("'self'",),
    }
}