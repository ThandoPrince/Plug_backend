# api/common/websockets/provider_publisher.py

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


logger = logging.getLogger(__name__)


class ProviderPublisher:
    """
    Publishes websocket events to authenticated providers.
    """

    @staticmethod
    def publish(
        provider_id: int,
        event_type: str,
        data: dict,
    ) -> bool:
        """
        Sends an event to a provider's websocket group.

        Returns:
            bool: True if the event was queued successfully.
        """

        try:
            channel_layer = get_channel_layer()

            async_to_sync(channel_layer.group_send)(
                f"provider_{provider_id}",
                {
                    "type": event_type,
                    "data": data,
                },
            )

            return True

        except Exception:
            logger.exception(
                "Failed to publish '%s' to provider %s.",
                event_type,
                provider_id,
            )
            return False