"""Thin Paystack API client. All amounts are in the lowest currency unit (cents for ZAR)."""
import hashlib
import hmac
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.paystack.co"
CURRENCY = "ZAR"


class PaystackError(Exception):
    pass


def _headers():
    return {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def _request(method, path, **kwargs):
    try:
        resp = requests.request(
            method, f"{BASE_URL}{path}", headers=_headers(), timeout=15, **kwargs
        )
        body = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.exception("Paystack request failed: %s %s", method, path)
        raise PaystackError("Could not reach the payment provider.") from exc

    if resp.status_code >= 400 or not body.get("status"):
        logger.warning("Paystack error %s %s: %s", method, path, body)
        raise PaystackError(body.get("message", "Payment provider error."))
    return body["data"]


def initialize_transaction(*, email, amount_cents, reference, metadata=None, callback_url=None):
    """Returns dict with authorization_url, access_code, reference."""
    payload = {
        "email": email,
        "amount": amount_cents,
        "currency": CURRENCY,
        "reference": reference,
        "metadata": metadata or {},
    }
    if callback_url:
        payload["callback_url"] = callback_url
    return _request("POST", "/transaction/initialize", json=payload)


def verify_transaction(reference):
    return _request("GET", f"/transaction/verify/{reference}")


def verify_signature(raw_body: bytes, signature: str) -> bool:
    """Paystack signs the raw body with HMAC-SHA512 using your secret key."""
    if not signature:
        return False
    expected = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode(), raw_body, hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def create_transfer_recipient(*, name, account_number, bank_code):
    # Verify the recipient `type` for ZA bank accounts against Paystack's docs ("basa").
    return _request(
        "POST",
        "/transferrecipient",
        json={
            "type": "basa",
            "name": name,
            "account_number": account_number,
            "bank_code": bank_code,
            "currency": CURRENCY,
        },
    )


def initiate_transfer(*, amount_cents, recipient_code, reference, reason):
    return _request(
        "POST",
        "/transfer",
        json={
            "source": "balance",
            "amount": amount_cents,
            "recipient": recipient_code,
            "reference": reference,
            "reason": reason,
            "currency": CURRENCY,
        },
    )