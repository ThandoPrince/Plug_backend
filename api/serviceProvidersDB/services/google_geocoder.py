import requests
from django.conf import settings


class GoogleGeocoder:

    @staticmethod
    def reverse_geocode(latitude, longitude):

        url = (
            "https://maps.googleapis.com/maps/api/geocode/json"
            f"?latlng={latitude},{longitude}"
            f"&key={settings.GOOGLE_MAPS_API_KEY}"
        )

        response = requests.get(url, timeout=5)
        response.raise_for_status()

        result = response.json()

        suburb = None
        city = None
        province = None

        if result["results"]:
            components = result["results"][0]["address_components"]

            for component in components:

                types = component["types"]

                if "sublocality" in types or "sublocality_level_1" in types:
                    suburb = component["long_name"]

                elif "locality" in types:
                    city = component["long_name"]

                elif "administrative_area_level_1" in types:
                    province = component["long_name"]

        return suburb, city, province