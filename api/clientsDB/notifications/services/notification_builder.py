from django.utils import timezone


class OrderNotificationBuilder:

    @staticmethod
    def booking_invite(order):
        return {
            "event": "booking.invited",
            "entity_type": "order",
            "entity_id": order.order_id,
            "timestamp": timezone.now().isoformat(),
            "data": {
                "order_id": order.order_id,
                "status": order.status,
                "title": order.title or "New booking",
                "service_name": (
                    order.service_required.service_name
                    if order.service_required
                    else None
                ),
                "client_name": (
                    order.client.first_name
                    if order.client
                    else None
                ),
            }
        }

    @staticmethod
    def provider_booking_update(order):
        return {
            "event": "booking.updated",
            "entity_type": "order",
            "entity_id": order.order_id,
            "timestamp": timezone.now().isoformat(),
            "data": {
                "order_id": order.order_id,
                "status": order.status,
                "title": order.title,
                "service_name": (
                    order.service_required.service_name
                    if order.service_required
                    else None
                ),
            }
        }

    @staticmethod
    def client_booking_update(order):
        return {
            "event": "booking.status_changed",
            "entity_type": "order",
            "entity_id": order.order_id,
            "timestamp": timezone.now().isoformat(),
            "data": {
                "order_id": order.order_id,
                "status": order.status,
                "title": order.title,
                "service_name": (
                    order.service_required.service_name
                    if order.service_required
                    else None
                ),
                "provider_service_id": order.provider_for_service_id,
            }
        }

    @staticmethod
    def booking_cancelled(order):
        return {
            "event": "booking.cancelled",
            "entity_type": "order",
            "entity_id": order.order_id,
            "timestamp": timezone.now().isoformat(),
            "data": {
                "order_id": order.order_id,
                "status": order.status,
            }
        }
    


    @staticmethod
    def booking_invite(order):
        return {
            "entity_type": "order",
            "entity_id": order.order_id,
            "type": "new_booking_invite",
            "title": order.title or "New booking",
            "service_name": (
                order.service_required.service_name
                if order.service_required
                else None
            ),
            "client_name": (
                order.client.first_name
                if order.client
                else None
            ),
        }

    @staticmethod
    def order_accepted(order):
        return {
            "entity_type": "order",
            "entity_id": order.order_id,
            "type": "order_accepted",
            "status": order.status,
        }

    @staticmethod
    def provider_in_transit(order):
        return {
            "entity_type": "order",
            "entity_id": order.order_id,
            "type": "provider_in_transit",
            "status": order.status,
        }

    @staticmethod
    def provider_arrived(order):
        return {
            "entity_type": "order",
            "entity_id": order.order_id,
            "type": "provider_arrived",
            "status": order.status,
        }

    @staticmethod
    def order_cancelled(order):
        return {
            "entity_type": "order",
            "entity_id": order.order_id,
            "type": "order_cancelled",
            "status": order.status,
        }
    @staticmethod
    def order_rescheduled(order):
        return {
            "entity_type": "order",
            "entity_id": order.order_id,
            "type": "order_rescheduled",
            "status": order.status,
            "scheduled_date": (
                order.requested_date.isoformat()
                if order.requested_date
                else None
            ),
            "scheduled_time": (
                order.requested_date_time.isoformat()
                if order.requested_date_time
                else None
            ),
        }