import json
import time
import requests
from django.conf import settings
from firebase_admin import messaging

from api.serviceProvidersDB.models import DeviceToken
from api.serviceProvidersDB.notifications.services import provider_settings

  # adjust import to your real provider app path

# Huawei credentials
HMS_APP_ID = provider_settings.HMS_APP_ID
HMS_APP_SECRET = provider_settings.HMS_APP_SECRET

# Token cache
_hms_cached_token = None
_hms_token_expiry = 0


def send_push_to_provider(service_provider, title, body, data=None):
    """
    Sends push notifications to all registered devices of a service provider.
    Supports Firebase and Huawei Push Kit.
    """
    devices = list(
        DeviceToken.objects.filter(service_provider=service_provider).only(
            "id", "provider", "fcm_token"
        )
    )

    if not devices:
        print(f"[Push] No registered devices for provider {service_provider}")
        return

    firebase_tokens = []
    huawei_tokens = []
    device_map = {}

    for device in devices:
        token = device.fcm_token
        if not token:
            continue
        device_map[token] = device
        provider = (device.provider or "").strip().lower()
        if provider == "firebase":
            firebase_tokens.append(token)
        elif provider == "huawei":
            huawei_tokens.append(token)
        else:
            print(f"[Push] Unknown provider: {provider}")

    print(f"[Push] Firebase: {len(firebase_tokens)} | Huawei: {len(huawei_tokens)}")

    if firebase_tokens:
        _send_firebase_batch(firebase_tokens, title, body, data, device_map)

    if huawei_tokens:
        _send_huawei_batch(huawei_tokens, title, body, data)


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _send_firebase_batch(tokens, title, body, data, device_map):
    """
    Send to Firebase in batches of up to 500 tokens per API call.
    """
    firebase_data = _normalize_firebase_data(data)
    invalid_tokens = []

    for chunk in _chunks(tokens, 500):
        messages = [
            messaging.Message(
                token=token,
                notification=messaging.Notification(title=title, body=body),
                data=firebase_data,
                android=messaging.AndroidConfig(
                    priority="high",
                    notification=messaging.AndroidNotification(
                        sound="default",
                        channel_id="default_channel",
                    ),
                ),
            )
            for token in chunk
        ]

        try:
            response = messaging.send_each(messages)
        except Exception as e:
            print(f"[Firebase Batch ERROR] {e}")
            continue

        for token, result in zip(chunk, response.responses):
                    if result.success:
                        continue
                    error = str(result.exception).lower()
                    print(f"[Firebase ERROR] {token}: {error}")
                    if any(x in error for x in [
                        "not registered",
                        "unregistered",
                        "invalid registration",
                        "requested entity was not found",
                    ]):
                        invalid_tokens.append(token)

        print(f"[Firebase Batch] {response.success_count} succeeded, {response.failure_count} failed")

    if invalid_tokens:
        print(f"[Firebase] Removing {len(invalid_tokens)} invalid token(s)")
        DeviceToken.objects.filter(fcm_token__in=invalid_tokens).delete()


def _send_huawei_batch(tokens, title, body, data):
    """
    Send to Huawei in batches of up to 500 tokens per API call
    (HMS caps the token array at 500 per request).
    """
    access_token = _get_hms_access_token()
    if not access_token:
        print("[Huawei Batch ERROR] No access token")
        return

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    for chunk in _chunks(tokens, 500):
        payload = {
            "validate_only": False,
            "message": {
                "token": chunk,
                "data": json.dumps(data or {}),
                "android": {
                    "bi_tag": "provider_notification",
                    "notification": {
                        "title": title,
                        "body": body,
                        "click_action": {"type": 3},
                    },
                },
            },
        }

        try:
            response = requests.post(
                f"https://push-api.cloud.huawei.com/v1/{HMS_APP_ID}/messages:send",
                headers=headers,
                json=payload,
                timeout=10,
            )
        except Exception as e:
            print(f"[Huawei Batch ERROR] {e}")
            continue

        if response.status_code == 200:
            print(f"[Huawei Batch] SUCCESS ({len(chunk)} tokens)")
        else:
            print(f"[Huawei Batch FAILED] {response.text}")
            # Huawei doesn't cleanly tell you which token in the batch was
            # invalid without inspecting per-token results in the response
            # body — worth checking their multi-token response format if
            # you want per-token cleanup here.


def _send_firebase_push(device, push_token, title, body, data=None):
    """
    Send notification using Firebase Cloud Messaging.
    """
    try:
        firebase_data = _normalize_firebase_data(data)

        message = messaging.Message(
            token=push_token,
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=firebase_data,
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    sound="default",
                    channel_id="default_channel",
                ),
            ),
        )

        response = messaging.send(message)

        print("[Firebase Push SUCCESS]")
        print(f"[Firebase Response] {response}")

    except Exception as e:
        print("[Firebase Push ERROR]")
        print(str(e))

        error_text = str(e).lower()
        if (
            "registration-token-not-registered" in error_text
            or "unregistered" in error_text
            or "invalid registration token" in error_text
        ):
            print(f"[Firebase] Removing invalid token for provider device id={device.id}")
            device.delete()





def _normalize_firebase_data(data):
    """
    Firebase data payload values must be strings.
    """
    if not data:
        return {}

    normalized = {}
    for key, value in data.items():
        if value is None:
            continue

        if isinstance(value, (dict, list)):
            normalized[str(key)] = json.dumps(value)
        else:
            normalized[str(key)] = str(value)

    return normalized


def _get_hms_access_token():
    """
    Fetch Huawei OAuth token and cache it.
    """
    global _hms_cached_token, _hms_token_expiry

    if _hms_cached_token and time.time() < _hms_token_expiry:
        print("[Huawei OAuth] Using cached token")
        return _hms_cached_token

    try:
        print("\n[Huawei OAuth] Requesting new token...")

        response = requests.post(
            "https://oauth-login.cloud.huawei.com/oauth2/v3/token",
            data={
                "grant_type": "client_credentials",
                "client_id": HMS_APP_ID,
                "client_secret": HMS_APP_SECRET
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded"
            },
            timeout=10
        )

        print("[Huawei OAuth Response Status]")
        print(response.status_code)

        print("[Huawei OAuth Response Body]")
        print(response.text)

        response.raise_for_status()

        token_data = response.json()

        _hms_cached_token = token_data.get("access_token", "")
        expires_in = int(token_data.get("expires_in", 0))
        _hms_token_expiry = time.time() + expires_in - 60

        print("[Huawei OAuth] Token stored in cache")

        return _hms_cached_token

    except Exception as e:
        print("[Huawei OAuth ERROR]")
        print(str(e))
        return ""