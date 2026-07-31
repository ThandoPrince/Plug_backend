from math import radians, sin, cos, sqrt, atan2

from .google_geocoder import GoogleGeocoder


class LocationService:

    EARTH_RADIUS = 6371000  # meters

    @classmethod
    def distance_meters(cls, lat1, lon1, lat2, lon2):
        """
        Returns the distance between two coordinates in meters.
        """

        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)

        a = (
            sin(dlat / 2) ** 2
            + cos(radians(lat1))
            * cos(radians(lat2))
            * sin(dlon / 2) ** 2
        )

        return 2 * cls.EARTH_RADIUS * atan2(sqrt(a), sqrt(1 - a))

    @classmethod
    def has_moved(
        cls,
        old_lat,
        old_lon,
        new_lat,
        new_lon,
        minimum_distance=500,
    ):
        """
        Returns True if the provider has moved more than the
        configured distance.
        """

        return (
            cls.distance_meters(
                old_lat,
                old_lon,
                new_lat,
                new_lon,
            )
            >= minimum_distance
        )

    @classmethod
    def reverse_geocode(
        cls,
        latitude,
        longitude,
    ):
        """
        Returns suburb/city/province.
        """

        suburb, city, province = GoogleGeocoder.reverse_geocode(
            latitude,
            longitude,
        )

        return {
            "suburb": suburb,
            "city": city,
            "province": province,
        }