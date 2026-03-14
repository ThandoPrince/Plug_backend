import json
import logging
import os

import firebase_admin
from firebase_admin import credentials
from django.conf import settings

logger = logging.getLogger(__name__)


def initialize_firebase():
    if firebase_admin._apps:
        logger.info("[Firebase] Admin SDK already initialized")
        return

    firebase_json = os.getenv("FIREBASE_CREDENTIALS_JSON", "").strip()
    firebase_key_path = getattr(settings, "FIREBASE_KEY_PATH", None)

    try:
        if firebase_json:
            cred_dict = json.loads(firebase_json)
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            logger.info("[Firebase] Admin SDK initialized from FIREBASE_CREDENTIALS_JSON")
            return

        if firebase_key_path and os.path.exists(firebase_key_path):
            cred = credentials.Certificate(firebase_key_path)
            firebase_admin.initialize_app(cred)
            logger.info("[Firebase] Admin SDK initialized from file path")
            return

        logger.warning(
            "[Firebase] No valid Firebase credentials found. "
            "Set FIREBASE_CREDENTIALS_JSON or provide a valid FIREBASE_KEY_PATH."
        )

    except Exception as e:
        logger.exception("[Firebase] Failed to initialize Firebase: %s", e)
