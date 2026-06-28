from api.bookings.events.ws_events import notify_client_booking, notify_provider_booking_update
from api.clientsDB.notifications.services.client_push_notification_service import send_push_to_client
from api.clientsDB.notifications.services.notification_builder import OrderNotificationBuilder
from api.clientsDB.notifications.services.notification_service import NotificationService
from api.serviceProvidersDB.notifications.services.provider_push_notification_service import send_push_to_provider


class NotificationDispatcher:
    @staticmethod
    def dispatch_client(notification, event_type, client_email):
        notify_client_booking(
            client_email,
            {
                "event": event_type,
                "notification": notification
            }
        )

        send_push_to_client(
            client=notification["client"],
            title=notification["title"],
            body=notification["body"],
            data=notification.get("payload", {})
        )

    @staticmethod
    def dispatch_provider(notification, event_type, provider_email):
        notify_provider_booking_update(
            provider_email,
            {
                "event": event_type,
                "notification": notification
            }
        )

        send_push_to_provider(
            service_provider=notification["provider"],
            title=notification["title"],
            body=notification["body"],
            data=notification.get("payload", {})
        )

    @staticmethod
    def send_booking_invites(order):

        invited_profiles = order.invited_providers.all()
        if not invited_profiles.exists():
            return

        payload = OrderNotificationBuilder.booking_invite(order)

        for sp in invited_profiles:
            NotificationService.notify_provider(
                provider=sp,
                notification_type="booking_invite",
                title="New Booking Request 📩",
                body=payload["body"],
                payload=payload
            )