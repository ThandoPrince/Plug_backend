from api.serviceProvidersDB.models import SPProfile


class ProviderLocationService:

    @staticmethod
    def update_location(provider, latitude, longitude):
        provider.latitude = latitude
        provider.longitude = longitude

        provider.save(
            update_fields=[
                "latitude",
                "longitude",
            ]
        )

        return provider