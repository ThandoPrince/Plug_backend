import requests

from django.conf import settings


class AIAddressVerificationClient:

    @classmethod
    def get_base_url(cls):
        if settings.DEBUG:
            return "http://localhost:8001"

        return settings.AI_KYC_API_URL.rstrip("/")

    @classmethod
    def verify_address(
        cls,
        customer_id,
        client,
        id_number,
        id_document,
        liveness_video,
        proof_of_residence,
    ):
        id_document.seek(0)
        liveness_video.seek(0)
        proof_of_residence.seek(0)

        files = {
            "id_document": (
                id_document.name,
                id_document,
                id_document.content_type,
            ),
            "liveness_video": (
                liveness_video.name,
                liveness_video,
                liveness_video.content_type,
            ),
            "proof_of_address": (
                proof_of_residence.name,
                proof_of_residence,
                proof_of_residence.content_type,
            ),
        }

        full_name = " ".join(
            part
            for part in [
                client.first_name,
                client.last_name,
            ]
            if part
        ).strip()

        data = {
            "customer_id": str(customer_id),
            "full_name": full_name,
            "id_number": id_number,
        }

        headers = {
            "X-API-Key": settings.AI_API_KEY,
        }

        response = requests.post(
            f"{cls.get_base_url()}/api/address/verify",
            headers=headers,
            data=data,
            files=files,
            timeout=180,
        )

        response.raise_for_status()

        return response.json()