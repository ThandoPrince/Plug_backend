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

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}



SECRET_KEY = get_env("DJANGO_SECRET_KEY", required=True)
DEBUG = get_env("DJANGO_DEBUG", "False").lower() == "true"

ALLOWED_HOSTS = [
    host.strip()
    for host in get_env(
        "DJANGO_ALLOWED_HOSTS",
        "localhost,127.0.0.1,web-production-7dfca.up.railway.app,10.0.2.2"
    ).split(",")
    if host.strip()
]
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in get_env(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "http://127.0.0.1,http://localhost,https://web-production-7dfca.up.railway.app"
    ).split(",")
    if origin.strip()
]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in get_env(
        "DJANGO_CORS_ALLOWED_ORIGINS",
        "http://127.0.0.1:8000,http://localhost:8000,https://web-production-7dfca.up.railway.app"
    ).split(",")
    if origin.strip()
]

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
    "api.clientsDB",
    "api.serviceProvidersDB",
    "api.bookings",
    "api.posts",
    "api.audits",
]

MIDDLEWARE = [
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
        conn_max_age=600,
        ssl_require=False,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

HMS_APP_ID = get_env("HMS_APP_ID", "")
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

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
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
        "auth": "5/min",
        "register": "3/min",
        "public_read": "30/min",
        "user_read": "60/min",
        "heavy_read": "20/min",
        "live_location_write": "30/min",
        "live_location_read": "20/min",
        "upload": "10/min",
        "profile_write": "20/min",
        "booking_like_write": "15/min",
    }
}

REDIS_URL = get_env("REDIS_URL", "")  # optional, no crash

if DEBUG or not REDIS_URL:
    # Local or fallback (no Redis)
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
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

SESSION_GEOFENCE_RADIUS_METERS = int(get_env("SESSION_GEOFENCE_RADIUS_METERS", "45"))
SESSION_GEOFENCE_GRACE_SECONDS = int(get_env("SESSION_GEOFENCE_GRACE_SECONDS", "120"))
SESSION_GEOFENCE_PING_INTERVAL_SECONDS = int(get_env("SESSION_GEOFENCE_PING_INTERVAL_SECONDS", "20"))