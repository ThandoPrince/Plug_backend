import requests


class AIKYCClient:
    BASE_URL = "http://localhost:8001"

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

        response = requests.post(
            f"{cls.BASE_URL}/api/affidavit/verify",
            data=data,
            files=files,
            timeout=180,
        )

        response.raise_for_status()

        return response.json()