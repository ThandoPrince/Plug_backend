import os

from google_crc32c import value
import requests


class KYCService:

    @staticmethod
    def verify_with_ai(
        customer_id,
        full_name,
        front_path,
        back_path=None,
        selfie_path=None,
    ):
        url = "http://localhost:8001/api/kyc/initiate"

        files = {}

        try:
            files["id_document"] = (
    os.path.basename(front_path),
    open(front_path, "rb"),
    "image/jpeg"
)

            if selfie_path:
                files["liveness_video"] = (
        os.path.basename(selfie_path),
        open(selfie_path, "rb"),
        "video/mp4"
    )

            data = {
                "customer_id": str(customer_id),
                "full_name": full_name,
            }

            response = requests.post(
                url,
                files=files,
                data=data,
                timeout=120,
            )

            print("========== AI RESPONSE ==========")
            print("Status:", response.status_code)
            print("Headers:", response.headers.get("content-type"))
            print("Body:")
            print(response.text)
            print("=================================")

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
            for value in files.values():
                value[1].close()