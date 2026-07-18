import asyncio
import json
import logging
from urllib.parse import parse_qs

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from api.bookings.models import Shipment
from api.bookings.utils.ws_auth import authenticate_ws_token

logger = logging.getLogger(__name__)


class ShipmentRouteConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer that streams route/status updates for a shipment.

    Mirrors the guarantees the Flutter `ShipmentRouteSocketService` expects
    from the server side:
      - Responds to application-level `ping` frames with `pong` so the
        client's pong watchdog never fires on a healthy connection.
      - Runs its own idle watchdog so connections the client has abandoned
        (no ping received for a while) are cleaned up instead of leaking
        group membership forever.
      - Uses structured logging (no `print`) with consistent close codes:
          4001 - missing token
          4002 - malformed shipment id
          4003 - authentication / authorization failure
          4004 - shipment not found
          4500 - unexpected server error during setup
    """

    # How long we tolerate silence from the client before treating the
    # connection as dead. Should comfortably exceed the client's own
    # heartbeatInterval (20s) + pongTimeout (8s) to avoid racing it.
    CLIENT_IDLE_TIMEOUT = 45  # seconds
    IDLE_CHECK_INTERVAL = 15  # seconds

    async def connect(self):
        self._watchdog_task = None
        self._last_client_activity = None

        raw_shipment_id = self.scope["url_route"]["kwargs"]["shipment_id"]

        try:
            self.shipment_id = int(raw_shipment_id)
        except (TypeError, ValueError):
            logger.warning(
                "Shipment websocket rejected: invalid shipment_id=%r",
                raw_shipment_id,
            )
            await self.close(code=4002)
            return

        # -------------------------
        # Token
        # -------------------------
        token = self.get_token_from_query()

        if not token:
            logger.info(
                "Shipment websocket rejected: missing token. shipment_id=%s",
                self.shipment_id,
            )
            await self.close(code=4001)
            return

        # -------------------------
        # Authentication
        # -------------------------
        try:
            user, role = await sync_to_async(authenticate_ws_token)(token)
        except Exception:
            logger.exception(
                "Shipment websocket authentication failed. shipment_id=%s",
                self.shipment_id,
            )
            await self.close(code=4003)
            return

        if not user:
            logger.info(
                "Shipment websocket rejected: invalid token. shipment_id=%s",
                self.shipment_id,
            )
            await self.close(code=4003)
            return

        self.scope["user"] = user
        self.scope["role"] = role

        # -------------------------
        # Load shipment + authorize
        # -------------------------
        try:
            shipment = await self.get_shipment(self.shipment_id)

            if shipment is None:
                logger.info(
                    "Shipment websocket rejected: shipment not found. shipment_id=%s",
                    self.shipment_id,
                )
                await self.close(code=4004)
                return

            allowed = await self.check_access(user.id, role, shipment)

            if not allowed:
                logger.info(
                    "Shipment websocket rejected: user %s (role=%s) not authorized "
                    "for shipment_id=%s",
                    user.id,
                    role,
                    self.shipment_id,
                )
                await self.close(code=4003)
                return

        except Exception:
            logger.exception(
                "Shipment websocket initialization failed. shipment_id=%s",
                self.shipment_id,
            )
            await self.close(code=4500)
            return

        self.shipment = shipment
        self.group_name = f"shipment_route_{self.shipment_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)

        logger.info(
            "Shipment websocket connected. channel=%s group=%s user_id=%s role=%s",
            self.channel_name,
            self.group_name,
            user.id,
            role,
        )

        await self.accept()

        self._touch_activity()
        self._watchdog_task = asyncio.ensure_future(self._idle_watchdog())

    # --------------------------------------------------
    # Token
    # --------------------------------------------------

    def get_token_from_query(self):
        """Robustly extract `token` from the query string.

        Uses urllib's parse_qs instead of manual splitting so percent-encoded
        or repeated params are handled correctly.
        """
        query_string = self.scope["query_string"].decode()
        params = parse_qs(query_string)
        values = params.get("token")
        return values[0] if values else None

    # --------------------------------------------------
    # Shipment
    # --------------------------------------------------

    @sync_to_async
    def get_shipment(self, shipment_id):
        try:
            return (
                Shipment.objects.select_related(
                    "service_ordered__order",
                    "service_ordered__order__provider_for_service",
                    "service_ordered__order__client",
                ).get(pk=shipment_id)
            )
        except Shipment.DoesNotExist:
            return None

    # --------------------------------------------------
    # Authorization
    # --------------------------------------------------

    @sync_to_async
    def check_access(self, user_id, role, shipment):
        booking_item = shipment.service_ordered
        order = booking_item.order

        if role == "client":
            return order.client_id == user_id

        if role == "provider":
            return order.provider_for_service_id == user_id

        return False

    # --------------------------------------------------
    # Client -> Server messages (heartbeat, etc.)
    # --------------------------------------------------

    async def receive(self, text_data=None, bytes_data=None):
        """Handle inbound frames from the client.

        The Flutter client's heartbeat protocol requires the server to:
          - Reply `pong` to a client `ping` (this is what keeps the client's
            pong watchdog from firing and forcing a reconnect).
          - Tolerate a `pong` reply if the server ever initiates its own ping.
        Anything else is logged and otherwise ignored rather than raising,
        since a malformed frame from one client should never take the
        connection down or affect other consumers on the same group.
        """
        if text_data is None:
            return

        self._touch_activity()

        try:
            payload = json.loads(text_data)
        except (TypeError, ValueError):
            logger.debug(
                "Shipment websocket received non-JSON frame. channel=%s shipment_id=%s",
                self.channel_name,
                self.shipment_id,
            )
            return

        if not isinstance(payload, dict):
            return

        msg_type = payload.get("type")

        if msg_type == "ping":
            await self._safe_send({"type": "pong"})
            return

        if msg_type == "pong":
            # Reserved for future server-initiated pings; nothing to do yet.
            return

        logger.debug(
            "Shipment websocket received unrecognized message type=%r. shipment_id=%s",
            msg_type,
            self.shipment_id,
        )

    # --------------------------------------------------
    # Idle watchdog
    # --------------------------------------------------

    def _touch_activity(self):
        self._last_client_activity = asyncio.get_event_loop().time()

    async def _idle_watchdog(self):
        """Periodically checks that the client is still pinging us.

        If the client goes silent for longer than CLIENT_IDLE_TIMEOUT
        (well beyond its own heartbeat cadence), we proactively close the
        socket so the group membership and channel don't leak.
        """
        try:
            while True:
                await asyncio.sleep(self.IDLE_CHECK_INTERVAL)

                if self._last_client_activity is None:
                    continue

                idle_for = asyncio.get_event_loop().time() - self._last_client_activity

                if idle_for > self.CLIENT_IDLE_TIMEOUT:
                    logger.info(
                        "Shipment websocket idle timeout, closing. "
                        "channel=%s shipment_id=%s idle_for=%.1fs",
                        self.channel_name,
                        self.shipment_id,
                        idle_for,
                    )
                    await self.close(code=4008)
                    return
        except asyncio.CancelledError:
            pass

    # --------------------------------------------------
    # Outbound helpers
    # --------------------------------------------------

    async def _safe_send(self, payload):
        """Send JSON, swallowing errors from a socket that's mid-teardown."""
        try:
            await self.send(text_data=json.dumps(payload))
        except Exception:
            logger.debug(
                "Shipment websocket send failed (socket likely closing). "
                "channel=%s shipment_id=%s",
                self.channel_name,
                self.shipment_id,
            )

    # --------------------------------------------------
    # Group events (server -> client push)
    # --------------------------------------------------


    async def session_created(self, event):
        logger.info(
            "Session created dispatched. shipment_id=%s session_id=%s",
            event["shipment_id"],
            event["session_id"],
        )

        await self._safe_send(
            {
                "type": "session_created",
                "shipment_id": event["shipment_id"],
                "session_id": event["session_id"],
                "session_status": event["session_status"],
                "checkin_time": event["checkin_time"],
            }
        )


    async def session_completed(self, event):
        logger.info(
            "Session completed dispatched. shipment_id=%s session_id=%s",
            event["shipment_id"],
            event["session_id"],
        )

        await self._safe_send(
            {
                "type": "session_completed",
                "shipment_id": event["shipment_id"],
                "session_id": event["session_id"],
                "session_status": event["session_status"],
                "checkout_time": event["checkout_time"],
            }
        )


    async def shipment_route_updated(self, event):
        logger.info(
            "Shipment route update dispatched. shipment_id=%s", self.shipment_id
        )
        await self._safe_send(
            {"type": "shipment_route_updated", "data": event["data"]}
        )

    async def shipment_status_update(self, event):
        logger.info(
            "Shipment status update dispatched. shipment_id=%s status=%s",
            self.shipment_id,
            event.get("status"),
        )
        await self._safe_send(
            {
                "type": "shipment_status_update",
                "status": event["status"],
                "updated_at": event["updated_at"],
            }
        )

    async def geofence_ping_updated(self, event):
        try:
            logger.info("Geofence handler invoked")
            logger.info("Event = %s", event)

            await self._safe_send({
                "type": "geofence_ping_updated",
                "data": event["data"],
            })
        except Exception:
            logger.exception("geofence_ping_updated crashed")

    # --------------------------------------------------
    # Disconnect
    # --------------------------------------------------

    async def disconnect(self, close_code):
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()

        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            logger.info(
                "Shipment websocket disconnected. channel=%s group=%s code=%s",
                self.channel_name,
                self.group_name,
                close_code,
            )