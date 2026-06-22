from django.db import transaction


class OrderStatusService:

    @staticmethod
    @transaction.atomic
    def set_status(order, new_status):
        from api.bookings.models import Shipment
        from api.bookings.services.shipment_transition_function import transition_shipment

        if order.status == new_status:
            return order

        allowed_transitions = {
            "pending": ["accepted", "declined", "canceled"],
            "accepted": ["in_delivery","canceled"],
            "in_delivery": ["awaiting_confirmation","canceled"],
            "awaiting_confirmation": ["in_session","canceled"],
            "in_session": ["awaiting_rating", "completed"],
            "awaiting_rating": ["completed"],
        }

        if order.status in allowed_transitions:
            if new_status not in allowed_transitions[order.status]:
                raise Exception(
                    f"Invalid transition {order.status} → {new_status}"
                )

        order.status = new_status
        order.save(update_fields=["status"])

        # 🔥 SIDE EFFECTS (ORDER → SHIPMENT)
        shipments = Shipment.objects.select_related(
            "service_ordered__order"
        ).filter(service_ordered__order=order)

        # ✅ Order entered session → Shipment enters session
        if new_status == "in_session":
            for shipment in shipments:
                if shipment.shipment_status != "in_session":
                    transition_shipment(shipment, "in_session")

        # ✅ Order completed → Shipment completed
        if new_status == "completed":
            for shipment in shipments:
                if shipment.shipment_status != "completed":
                    transition_shipment(shipment, "completed")

        if new_status == "canceled":
            # 1. Clear the M2M relationships table entries for this order
            order.invited_providers.clear()

        return order
