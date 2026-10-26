import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from firebase_admin import messaging

from api.clientsDB.models.models import DeviceToken


# =========================================================
# CONFIG
# =========================================================

HMS_APP_ID = settings.HMS_APP_ID
HMS_APP_SECRET = settings.HMS_APP_SECRET

_hms_cached_token = None
_hms_token_expiry = 0


ALLOWED_PROVIDERS = {"firebase", "huawei"}


# =========================================================
# ENTRY POINT
# =========================================================

def send_push_to_client(client, title, body, data=None):
    devices = list(
        DeviceToken.objects.filter(client=client).only(
            "id", "provider", "device_type", "fcm_token"
        )
    )



    firebase_tokens = []
    huawei_tokens = []
    device_map = {}

    for device in devices:
        token = device.fcm_token
        if not token:
            continue

        provider = _normalize_provider(device.provider)

        device_map[token] = device

        if provider == "firebase":
            firebase_tokens.append(token)

        elif provider == "huawei":
            huawei_tokens.append(token)

     

    with ThreadPoolExecutor(max_workers=2) as executor:
        if firebase_tokens:
            executor.submit(
                _send_firebase_batch,
                firebase_tokens,
                title,
                body,
                data,
                device_map,
            )

        if huawei_tokens:
            executor.submit(
                _send_huawei_batch,
                huawei_tokens,
                title,
                body,
                data,
            )


# =========================================================
# PROVIDER NORMALIZATION
# =========================================================

def _normalize_provider(provider: str) -> str:
    return (provider or "").strip().lower()


def _chunks(iterable, size):
    """Yield successive chunks of given size from iterable."""
    seq = list(iterable)
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


# =========================================================
# FIREBASE
# =========================================================

def _send_firebase_batch(tokens, title, body, data, device_map):
    firebase_data = _normalize_firebase_data(data)
    invalid_tokens = []

    # FCM caps batch sends at 500 messages
    for chunk in _chunks(tokens, 500):
        messages = [
            messaging.Message(
                token=token,
                notification=messaging.Notification(title=title, body=body),
                data=firebase_data,
                android=messaging.AndroidConfig(
                    priority="high",
                    notification=messaging.AndroidNotification(
                        sound="default", channel_id="default_channel",
                    ),
                ),
            )
            for token in chunk
        ]
        response = messaging.send_each(messages)  # single batch API call
        for token, result in zip(chunk, response.responses):
            if not result.success:
                error = str(result.exception).lower()
                if any(x in error for x in ["not registered", "unregistered", "invalid registration"]):
                    invalid_tokens.append(token)

    if invalid_tokens:
        DeviceToken.objects.filter(fcm_token__in=invalid_tokens).delete()


# =========================================================
# HUAWEI
# =========================================================

def _send_huawei_batch(tokens, title, body, data):
    try:
        access_token = _get_hms_access_token()
        if not access_token:
            print("[Huawei] Missing access token")
            return

        payload = {
            "validate_only": False,
            "message": {
                "token": tokens,
                "data": json.dumps(data or {}),
                "android": {
                    "bi_tag": "order_notification",
                    "notification": {
                        "title": title,
                        "body": body,
                        "click_action": {"type": 3},
                    },
                },
            },
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        response = requests.post(
            f"https://push-api.cloud.huawei.com/v1/{HMS_APP_ID}/messages:send",
            headers=headers,
            json=payload,
            timeout=10,
        )

        if response.status_code == 200:
            print("[Huawei Batch] SUCCESS")
        else:
            print("[Huawei Batch FAILED]", response.text)

    except Exception as e:
        print("[Huawei Batch ERROR]", str(e))


# =========================================================
# DATA NORMALIZATION
# =========================================================

def _normalize_firebase_data(data):
    if not data:
        return {}

    return {
        str(k): (
            json.dumps(v) if isinstance(v, (dict, list)) else str(v)
        )
        for k, v in data.items()
        if v is not None
    }


# =========================================================
# HUAWEI TOKEN CACHE
# =========================================================

def _get_hms_access_token():
    global _hms_cached_token, _hms_token_expiry

    if _hms_cached_token and time.time() < _hms_token_expiry:
        return _hms_cached_token

    try:
        response = requests.post(
            "https://oauth-login.cloud.huawei.com/oauth2/v3/token",
            data={
                "grant_type": "client_credentials",
                "client_id": HMS_APP_ID,
                "client_secret": HMS_APP_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )

        response.raise_for_status()
        data = response.json()

        _hms_cached_token = data.get("access_token", "")
        expires_in = int(data.get("expires_in", 0))
        _hms_token_expiry = time.time() + expires_in - 60

        return _hms_cached_token

    except Exception as e:
        print("[Huawei OAuth ERROR]", str(e))
        return ""