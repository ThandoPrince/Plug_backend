# bookings/services/geofencing.py

from django.conf import settings

from api.bookings.services.calculate_distance_meters import calculate_distance_meters



def is_inside_geofence(session, lat, lng):
    """
    Checks whether a given location is inside the session geofence
    """

    address = session.shipment.service_ordered.order.delivery_address

    center_lat = address.latitude
    center_lng = address.longitude

    distance = calculate_distance_meters(
        center_lat,
        center_lng,
        lat,
        lng
    )

    inside = distance <= settings.SESSION_GEOFENCE_RADIUS_METERS

    return inside, distance
