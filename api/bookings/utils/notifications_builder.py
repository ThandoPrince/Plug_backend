from datetime import datetime, timezone




class NotificationsBuilder:
    @staticmethod
    def order_rescheduled(order):

        shipment = (
            order.booking_items
            .first()
            .shipments
            .first()
        )

        return {
            "type": "order_rescheduled",
            "order_id": order.id,
            "shipment_id": shipment.shipment_id,
            "status": order.status,
            "scheduled_date": (
                shipment.shipment_schedule_date.isoformat()
                if shipment else None
            ),
            "scheduled_time": (
                shipment.shipment_schedule_time.strftime("%H:%M:%S")
                if shipment else None
            ),
        }