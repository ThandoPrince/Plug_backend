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
    tokens = DeviceToken.objects.filter(service_provider=service_provider)

    if not tokens.exists():
        print(f"[Push] No registered devices for provider {service_provider}")
        return

    print(f"[Push] Sending notification to {tokens.count()} provider device(s)")

    for device in tokens:
        provider = (device.provider or "").strip().lower()
        device_type = (device.device_type or "").strip().lower()
        push_token = device.fcm_token

        print("\n----------------------------------")
        print(f"[Push] Provider: {provider}")
        print(f"[Push] Device Type: {device_type}")
        print(f"[Push] Token: {push_token}")

        if not push_token:
            print("[Push] Token missing")
            continue

        if provider == "firebase":
            _send_firebase_push(
                device=device,
                push_token=push_token,
                title=title,
                body=body,
                data=data,
            )

        elif provider == "huawei":
            _send_huawei_push(
                device=device,
                push_token=push_token,
                title=title,
                body=body,
                data=data,
            )

        else:
            print(f"[Push] Unknown provider: {provider}")


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


def _send_huawei_push(device, push_token, title, body, data=None):
    """
    Send notification using Huawei Push Kit.
    """
    try:
        access_token = _get_hms_access_token()

        if not access_token:
            print("[Huawei Push ERROR] No access token")
            return

        payload = {
            "validate_only": False,
            "message": {
                "token": [push_token],
                "data": json.dumps(data or {}),
                "android": {
                    "bi_tag": "provider_notification",
                    "notification": {
                        "title": title,
                        "body": body,
                        "click_action": {
                            "type": 3
                        }
                    }
                }
            }
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        print("\n[Huawei Request]")
        print(json.dumps(payload, indent=2))

        response = requests.post(
            f"https://push-api.cloud.huawei.com/v1/{HMS_APP_ID}/messages:send",
            headers=headers,
            json=payload,
            timeout=10
        )

        print("\n[Huawei Response Status]")
        print(response.status_code)

        print("\n[Huawei Response Body]")
        print(response.text)

        if response.status_code == 200:
            print("[Huawei Push SUCCESS]")
        else:
            print("[Huawei Push FAILED]")

            # Optional cleanup for invalid Huawei tokens
            response_text = response.text.lower()
            if "invalid token" in response_text or "token invalid" in response_text:
                print(f"[Huawei] Removing invalid token for provider device id={device.id}")
                device.delete()

    except Exception as e:
        print("[Huawei Push ERROR]")
        print(str(e))


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