import requests

from django.conf import settings


class AIKYCClient:
    @classmethod
    def get_base_url(cls):
        if settings.DEBUG:
            return "http://localhost:8001"
        return settings.AI_KYC_API_URL.rstrip("/")

    @classmethod
    def verify_affidavit(
        cls,
        provider,
        provider_service,
        uploaded_file,
    ):
        uploaded_file.seek(0)

        files = {
            "affidavit": (
                uploaded_file.name,
                uploaded_file,
                uploaded_file.content_type,
            )
        }

        data = {
            "provider_id": str(provider.pk),
            "full_name": provider.full_name,
            "id_number": provider.id_number,
            "service_name": provider_service.service.service_name,
        }

        headers = {
            "X-API-Key": settings.AI_API_KEY,
        }

        response = requests.post(
            f"{cls.get_base_url()}/api/affidavit/verify",
            headers=headers,
            data=data,
            files=files,
            timeout=180,
        )

        response.raise_for_status()

        return response.json()