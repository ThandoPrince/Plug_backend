import firebase_admin
from firebase_admin import credentials
from django.conf import settings


def initialize_firebase():
    firebase_key_path = settings.FIREBASE_KEY_PATH
    cred = credentials.Certificate(firebase_key_path)

    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
        print("[Firebase] Admin SDK initialized")
    else:
        print("[Firebase] Admin SDK already initialized")