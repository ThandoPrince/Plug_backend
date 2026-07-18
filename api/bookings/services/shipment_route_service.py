


from api.bookings.serializers import ShipmentRouteWriteSerializer


class ShipmentRouteService:

    @staticmethod
    def create(shipment, data):
        """
        Creates a shipment route after validating the payload.
        """

        payload = data.copy()
        payload["shipment_id"] = shipment.shipment_id

        serializer = ShipmentRouteWriteSerializer(data=payload)
        serializer.is_valid(raise_exception=True)

        return serializer.save()