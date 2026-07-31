from math import radians, sin, cos, sqrt, atan2

EARTH_RADIUS = 6371000


def distance_meters(lat1, lon1, lat2, lon2):

    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(dlon / 2) ** 2
    )

    return 2 * EARTH_RADIUS * atan2(sqrt(a), sqrt(1 - a))