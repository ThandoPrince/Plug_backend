import logging

from api.bookings.models import (
    ClientNotification,
    SPNotification
)

from api.bookings.events.ws_events import (
    notify_client_booking,
    notify_provider_booking_update,
    notify_provider_booking_invite,
)

from api.clientsDB.notifications.services.client_push_notification_service import (
    send_push_to_client
)

from api.serviceProvidersDB.notifications.services.provider_push_notification_service import (
    send_push_to_provider
)

logger = logging.getLogger(__name__)


class NotificationService:

    @staticmethod
    def notify_client(
        client,
        notification_type,
        title,
        body,
        payload=None,
    ):
        payload = payload or {}

        notification = ClientNotification.objects.create(
            client=client,
            notification_type=notification_type,
            title=title,
            body=body,
            payload=payload,
        )

        try:
            notify_client_booking(
                client.id,
                {
                    "event": "notification",
                    "notification": {
                        "id": notification.id,
                        "title": title,
                        "body": body,
                        "type": notification_type,
                        "payload": payload,
                    }
                }
            )
        except Exception:
            logger.exception("Client websocket failed")

        try:
            send_push_to_client(
                client=client,
                title=title,
                body=body,
                data=payload,
            )
        except Exception:
            logger.exception("Client push failed")

        return notification

    @staticmethod
    def notify_provider(
        provider,
        notification_type,
        title,
        body,
        payload=None,
        websocket_invite=False,
    ):
        payload = payload or {}

        notification = SPNotification.objects.create(
            provider=provider,
            notification_type=notification_type,
            title=title,
            body=body,
            payload=payload,
        )

        try:

            if websocket_invite:
                notify_provider_booking_invite(
                    provider.id,
                    payload
                )
            else:
                notify_provider_booking_update(
                    provider.id,
                    {
                        "event": "notification",
                        "notification": {
                            "id": notification.id,
                            "title": title,
                            "body": body,
                            "type": notification_type,
                            "payload": payload,
                        }
                    }
                )

        except Exception:
            logger.exception("Provider websocket failed")

        try:
            send_push_to_provider(
                service_provider=provider,
                title=title,
                body=body,
                data=payload,
            )
        except Exception:
            logger.exception("Provider push failed")

        return notification