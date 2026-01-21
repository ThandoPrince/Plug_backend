from django.db import transaction
from api.bookings.services.session_creation_service import create_token_for_delivered_shipment
from api.bookings.services.shipment_fsm import SHIPMENT_STATE_MACHINE
from api.bookings.services.shipment_services import create_session_with_qr



class InvalidShipmentTransition(Exception):
    pass


@transaction.atomic
def transition_shipment(shipment, new_status):
    current = shipment.shipment_status

    allowed = SHIPMENT_STATE_MACHINE.get(current, [])

    if new_status not in allowed:
        raise InvalidShipmentTransition(
            f"Cannot change shipment from '{current}' to '{new_status}'"
        )

    shipment.shipment_status = new_status
    shipment.save(update_fields=["shipment_status"])

    # Side-effects
    if new_status == "delivered":
        create_token_for_delivered_shipment(shipment)

