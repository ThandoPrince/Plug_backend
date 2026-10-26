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

        logger.debug(
            "[notify_client] START client_id=%s type=%s title=%r payload=%s",
            client.id, notification_type, title, payload,
        )

        notification = ClientNotification.objects.create(
            client=client,
            notification_type=notification_type,
            title=title,
            body=body,
            payload=payload,
        )
        logger.debug(
            "[notify_client] DB notification created id=%s client_id=%s",
            notification.id, client.id,
        )

        try:
            logger.debug("[notify_client] sending websocket to client_id=%s", client.id)
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
            logger.debug("[notify_client] websocket sent client_id=%s", client.id)
        except Exception:
            logger.exception("Client websocket failed (client_id=%s)", client.id)

        try:
            logger.debug("[notify_client] sending push to client_id=%s", client.id)
            send_push_to_client(
                client=client,
                title=title,
                body=body,
                data=payload,
            )
            logger.debug("[notify_client] push sent client_id=%s", client.id)
        except Exception:
            logger.exception("Client push failed (client_id=%s)", client.id)

        logger.debug(
            "[notify_client] DONE notification_id=%s client_id=%s",
            notification.id, client.id,
        )
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

        logger.debug(
            "[notify_provider] START provider_id=%s type=%s title=%r "
            "websocket_invite=%s payload=%s",
            provider.id, notification_type, title, websocket_invite, payload,
        )

        notification = SPNotification.objects.create(
            provider=provider,
            notification_type=notification_type,
            title=title,
            body=body,
            payload=payload,
        )
        logger.debug(
            "[notify_provider] DB notification created id=%s provider_id=%s",
            notification.id, provider.id,
        )

        try:

            if websocket_invite:
                logger.debug(
                    "[notify_provider] sending websocket INVITE to provider_id=%s",
                    provider.id,
                )
                notify_provider_booking_invite(
                    provider.id,
                    payload
                )
            else:
                logger.debug(
                    "[notify_provider] sending websocket UPDATE to provider_id=%s",
                    provider.id,
                )
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
            logger.debug("[notify_provider] websocket sent provider_id=%s", provider.id)

        except Exception:
            logger.exception("Provider websocket failed (provider_id=%s)", provider.id)

        try:
            logger.debug("[notify_provider] sending push to provider_id=%s", provider.id)
            send_push_to_provider(
                service_provider=provider,
                title=title,
                body=body,
                data=payload,
            )
            logger.debug("[notify_provider] push sent provider_id=%s", provider.id)
        except Exception:
            logger.exception("Provider push failed (provider_id=%s)", provider.id)

        logger.debug(
            "[notify_provider] DONE notification_id=%s provider_id=%s",
            notification.id, provider.id,
        )
        return notification