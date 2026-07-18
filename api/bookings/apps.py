from django.apps import AppConfig




class BookingsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "api.bookings"

    def ready(self):
        # Existing signals
        import api.bookings.services.create_nego_signal
        import api.bookings.services.rating_creation_signal
        import api.bookings.services.calculate_ratings_signal

        # Event handlers
        from api.bookings.events.event_base import EventBus
        from api.bookings.utils.handlers.order_handlers import (
            handle_order_created,
        )
        from api.bookings.utils.handlers.negotiation_handlers import handle_negotiation_round_created

        EventBus.register(
            "order.created",
            handle_order_created
        )
        
        EventBus.register(
        "negotiation.round_created",
        handle_negotiation_round_created
    )