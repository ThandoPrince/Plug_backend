import os

import requests
from django.conf import settings


class KYCService:

    @staticmethod
    def get_base_url():
        if settings.DEBUG:
            return "http://localhost:8001"
        return settings.AI_KYC_API_URL.rstrip("/")

    @staticmethod
    def verify_with_ai(
        customer_id,
        full_name,
        front_path,
        back_path=None,
        selfie_path=None,
    ):
        url = f"{KYCService.get_base_url()}/api/kyc/initiate"

        files = {}

        try:
            files["id_document"] = (
                os.path.basename(front_path),
                open(front_path, "rb"),
                "image/jpeg",
            )

            if selfie_path:
                files["liveness_video"] = (
                    os.path.basename(selfie_path),
                    open(selfie_path, "rb"),
                    "video/mp4",
                )

            data = {
                "customer_id": str(customer_id),
                "full_name": full_name,
            }

            headers = {
                "X-API-Key": settings.AI_API_KEY,
            }

            response = requests.post(
                url,
                headers=headers,
                files=files,
                data=data,
                timeout=120,
            )

            response.raise_for_status()

            try:
                return response.json()
            except ValueError:
                return {
                    "success": False,
                    "error": "AI service returned invalid JSON",
                    "status_code": response.status_code,
                    "body": response.text,
                }

        except requests.RequestException as e:
            return {
                "success": False,
                "error": str(e),
            }

        finally:
            for file_info in files.values():
                file_info[1].close()