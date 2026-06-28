from datetime import datetime, timezone




class NegotiationNotificationBuilder:

    @staticmethod
    def round_created(negotiation, round_obj):

        order = negotiation.service_order

        return {
            "entity_type": "negotiation",
            "entity_id": negotiation.negotiation_id,
            "action": "round_created",

            "negotiation": {
                "id": negotiation.negotiation_id,
                "status": negotiation.status,
                "round_count": negotiation.round_count,
            },

            "order": {
                "id": order.order_id,
                "title": order.title,
            },

            "round": {
                "id": round_obj.id,
                "sender_type": round_obj.sender_type,
                "offered_price": str(round_obj.offered_price),
                "message": round_obj.message,
            }
        }
    


def build_negotiation_event(event_type, negotiation_id, data=None):
    return {
        "type": event_type,
        "negotiation_id": negotiation_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data or {}
    }

