from datetime import timedelta
from decimal import Decimal
import json
import logging
from django.core.exceptions import ObjectDoesNotExist
from types import SimpleNamespace
from django.http import Http404
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from django.conf import settings
from django.utils import timezone
from django.shortcuts import get_object_or_404
from psycopg import logger
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.db.models import Q, Avg, Exists, OuterRef
from api.bookings.events.event_base import EventBus
from api.bookings.events.negotiation_events import NegotiationRoundCreatedEvent
from api.bookings.events.order_events import NegotiationCreatedEvent, OrderAcceptedEvent, OrderCancelledEvent, OrderCreatedEvent, OrderRescheduledEvent, ProviderDeclinedInvitationEvent, ProviderOrderCancelledEvent
from api.bookings.events.websoket_event_emitters.shipment_event_emitters import push_session_completed, push_session_created, push_shipment_status_update
from api.bookings.events.ws_events import notify_client_booking, notify_client_negotiation_round, notify_client_negotiation_status_changed, notify_client_shipment_status, notify_provider_booking_update
from api.bookings.services.calculate_distance_meters import calculate_distance_meters
from api.bookings.services.order_status_service import OrderStatusService
from api.bookings.services.shipment_transition_function import InvalidShipmentTransition, transition_shipment
from api.bookings.utils.negoctiation_even_builder import build_negotiation_event
from api.clientsDB.models.models import ClientDetails
from api.clientsDB.notifications.services.notification_service import NotificationService
from api.clientsDB.services.jwt_client_authentication import ClientJWTAuthentication
from api.serviceProvidersDB.models import ProviderService, ServiceProvider
from api.serviceProvidersDB.services.sp_jwt_authentication import SPJWTAuthentication
from plug_backend.helpers.auth_helpers import get_client_details, get_sp_profile
from plug_backend.throttles import BookingLikeWriteThrottle, HeavyReadThrottle, ProfileWriteThrottle, UserReadThrottle
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import BookingItem, NegotiationRound, OrderService, Negotiation, Rating, Session, SessionLocationPing, SessionToken, Shipment, ShipmentHistory, ShipmentRoute
from .serializers import (
    ROUNDS_PAGE_SIZE,
    CancelOrderSerializer,
    ClientRatingReadSerializer,
    ClientRatingSerializer,
    ConfirmCheckinResponseSerializer,
    ConfirmCheckinSerializer,
    NegotiationRoundWriteSerializer,
    OrderFinalPricePatchSerializer,
    OrderServicePatchSerializer,
    OrderServiceReadSerializer,
    OrderServiceWriteSerializer,
    NegotiationReadSerializer,
    NegotiationWriteSerializer,
    NegotiationClientCounterSerializer,
    BookingItemReadSerializer,
    NegotiationRoundReadSerializer,
    PagedNegotiationReadSerializer,
    ProviderNegotiationReadSerializer,
    RatingReadSerializer,
    RatingWriteSerializer,
    RemoveInvitedProviderSerializer,
    SessionLocationPingReadSerializer,
    SessionLocationPingWriteSerializer,
    SessionReadSerializer,
    SessionStatusUpdateSerializer,
    SessionTokenReadSerializer,
    ShipmentReadSerializer,
    ShipmentRouteReadSerializer,
    ShipmentRouteWriteSerializer,
    SubmitRatingSerializer,
)
from rest_framework.permissions import IsAuthenticated


# ---------------- OrderService ----------------

@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
def order_service_list(request):
    """List all orders"""
    orders = OrderService.objects.all()
    serializer = OrderServiceReadSerializer(orders, many=True)
    return Response(serializer.data)


@api_view(['POST'])
@throttle_classes([BookingLikeWriteThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def order_service_create(request):
    # 1. Convert QueryDict to a standard Python dict to avoid QueryDict list nesting bugs
    data = request.data.dict()

    # 2. Extract and parse the JSON string of provider IDs securely
    raw_invited = request.data.get("invited_providers")
    if raw_invited:
        try:
            data["invited_providers"] = json.loads(raw_invited)
        except (json.JSONDecodeError, TypeError):
            data["invited_providers"] = []
    else:
        data["invited_providers"] = []

    # 3. Re-attach uploaded files
    if request.FILES:
        data["service_pictures"] = request.FILES.getlist("service_pictures")

    serializer = OrderServiceWriteSerializer(
        data=data,
        context={"request": request},
    )

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )

    with transaction.atomic():
        order = serializer.save()

        transaction.on_commit(
    lambda: EventBus.emit(
        OrderCreatedEvent({
            "order": order,
        })
    )
)
    return Response(
        OrderServiceReadSerializer(order).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def client_ratings(request, client_id):
    ratings = (
        Rating.objects
        .filter(
            session__shipment__service_ordered__order__client__client_profile_id=client_id,
            score__isnull=False,
        )
        .order_by("-created_at")
    )

    serializer = ClientRatingSerializer(
        ratings[:3],  # Only the latest 3 reviews
        many=True,
        context={"request": request},
    )

    return Response({
        "average_rating": ratings.aggregate(
            average=Avg("score")
        )["average"] or 0,
        "total_reviews": ratings.count(),
        "ratings": serializer.data,
    })
    

@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def order_service_detail(request, pk):
    """Retrieve a specific order belonging to the authenticated client."""

    client = get_client_details(request)

    order = get_object_or_404(
        OrderService,
        pk=pk,
        client=client,
    )

    serializer = OrderServiceReadSerializer(order)
    return Response(serializer.data)

    
    
@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def provider_order_service_detail(request, pk):
    """Retrieve a specific order belonging to the authenticated provider."""

    provider = get_sp_profile(request)

    order = get_object_or_404(
        OrderService.objects.filter(
            
            Q(invited_providers=provider)
        ).distinct(),
        pk=pk,
    )

    serializer = OrderServiceReadSerializer(order)
    return Response(serializer.data)

  

 


# ---------------- Negotiation ----------------

@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def negotiation_list(request):
    """List negotiations belonging to the authenticated provider."""

    provider = get_sp_profile(request)

    negotiations = (
        Negotiation.objects
        .filter(provider_for_negotiation__provider=provider)
        .distinct()
    )

    serializer = NegotiationReadSerializer(
        negotiations,
        many=True,
    )

    return Response(serializer.data)


@api_view(['GET'])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([HeavyReadThrottle])
def negotiation_detail(request, pk):
    """Rounds are paginated: optional ?before=<round pk>&limit=<n>."""
    try:
        try:
            before = request.query_params.get("before")
            before = int(before) if before else None
            limit = min(int(request.query_params.get("limit", ROUNDS_PAGE_SIZE)), 50)
            if limit < 1:
                raise ValueError
        except ValueError:
            return Response({"detail": "Invalid parameters."},
                            status=status.HTTP_400_BAD_REQUEST)

        client = get_client_details(request)

        # 🔒 RLS enforcement via order relationship
        negotiation = get_object_or_404(
            Negotiation.objects.select_related("service_order"),
            pk=pk,
            service_order__client=client,
        )

        ctx = {"before": before, "limit": limit, "has_more": False}
        data = PagedNegotiationReadSerializer(negotiation, context=ctx).data
        # data must be evaluated before reading ctx["has_more"]

        response = Response(data)
        response["X-Has-More-Rounds"] = "true" if ctx["has_more"] else "false"
        return response

    except Http404:
        # get_object_or_404 raises Http404, which neither except below
        # caught, so a missing negotiation returned a 500.
        raise

    except Negotiation.DoesNotExist:
        return Response({"detail": "Negotiation not found or access denied."},
                        status=status.HTTP_404_NOT_FOUND)

    except Exception:
        logger.exception("Error fetching negotiation detail")
        return Response({"detail": "Unexpected server error."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    
        
    
@api_view(["PATCH"])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def reject_negotiation(request, negotiation_id):

    try:
        negotiation = Negotiation.objects.select_related(
            "service_order",
            "service_order__client",
            "service_order__client__client_profile",
            "provider_for_negotiation",
            "provider_for_negotiation__provider",
            "provider_for_negotiation__provider__sp_profile",
        ).get(
            negotiation_id=negotiation_id
        )

    except Negotiation.DoesNotExist:
        return Response(
            {
                "success": False,
                "message": "Negotiation not found."
            },
            status=status.HTTP_404_NOT_FOUND
        )

    # RLS / Ownership Check
    if (
        not negotiation.service_order
        or not negotiation.service_order.client
        or negotiation.service_order.client.client_profile != request.user
    ):
        return Response(
            {
                "success": False,
                "message": "You do not have permission to access this negotiation."
            },
            status=status.HTTP_403_FORBIDDEN
        )
    if negotiation.status not in ["pending", "in-negotiation"]:
        return Response(
        {
            "success": False,
            "message": (
                f"This negotiation cannot be rejected because "
                f"its current status is '{negotiation.status}'."
            )
        },
        status=status.HTTP_400_BAD_REQUEST
    )

    try:
        with transaction.atomic():

            order = negotiation.service_order

            # Prevent rejecting the final available provider
            invited_provider_count = order.invited_providers.count()

            if invited_provider_count <= 1:
                return Response(
                    {
                        "success": False,
                        "action": "cancel_booking",
                        "message": (
                            "This is the last available service provider "
                            "for this request. Please cancel the booking "
                            "instead of rejecting the negotiation."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            provider_service = negotiation.provider_for_negotiation

            if (
                provider_service
                and provider_service.provider
                and provider_service.provider.sp_profile
            ):
                order.invited_providers.remove(
                    provider_service.provider.sp_profile
                )

            negotiation.status = "rejected"
            negotiation.last_responder = "client"
            negotiation.save()

            logger.info(
                "Negotiation %s rejected by client %s",
                negotiation.negotiation_id,
                request.user.id
            )

            return Response(
                {
                    "success": True,
                    "message": "Negotiation rejected successfully.",
                    "negotiation_id": negotiation.negotiation_id,
                    "remaining_invited_providers": order.invited_providers.count()
                },
                status=status.HTTP_200_OK
            )

    except Exception:
        logger.exception(
            "Reject negotiation failed. negotiation_id=%s user=%s",
            negotiation_id,
            request.user.id
        )

        return Response(
            {
                "success": False,
                "message": "Unable to process request at this time."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
@api_view(['POST'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def provider_accept_negotiation(request, negotiation_id):
    """
    Accept a negotiation for the authenticated provider only.
    """

    try:
        profile = get_sp_profile(request)
        provider = ServiceProvider.objects.get(sp_profile=profile)

        negotiation = get_object_or_404(
            Negotiation.objects.select_related(
                "service_order",
                "provider_for_negotiation__provider__sp_profile",
            ),
            pk=negotiation_id,
            provider_for_negotiation__provider=provider,
        )

        order = negotiation.service_order

        if order.status == "accepted":
            return Response(
                {"detail": "This order has already been accepted."},
                status=status.HTTP_200_OK,
            )

        provider_service = negotiation.provider_for_negotiation

        if provider_service is None:
            return Response(
                {"detail": "No provider assigned to this negotiation."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        final_price = (
            negotiation.provider_response_price
            or negotiation.proposed_price
        )

        if final_price is None:
            return Response(
                {"detail": "No valid negotiation price is available."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if order.proposal_price is not None:
            min_allowed = (
                order.proposal_price * MIN_OFFER_RATIO
            ).quantize(Decimal("0.01"))

            if final_price < min_allowed:
                return Response(
                    {
                        "error": (
                           
                            f"proposed price. Minimum allowed is R{min_allowed}."
                        ),
                        "minimum_allowed": str(min_allowed),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        with transaction.atomic():

            negotiation.provider_response_price = (
                negotiation.provider_response_price
                or negotiation.proposed_price
            )

            negotiation.status = "accepted"
            negotiation.last_responder = "provider"
            negotiation.save()

            order.final_price = negotiation.provider_response_price
            order.provider_for_service = provider_service
            order.is_negotiated = True
            order.status = "accepted"
            order.save()

            order.invited_providers.clear()

            order_id = order.order_id
            provider_profile_id = provider.sp_profile.id
            client_profile_id = order.client.client_profile.id

            def _after_commit():
                steps = (
                    lambda: EventBus.emit(OrderAcceptedEvent({
                        "order": order,
                        "negotiation": negotiation,
                        "provider_service": provider_service,
                    })),
                    lambda: notify_provider_booking_update(
                        provider_id=provider_profile_id,
                        payload=OrderServiceReadSerializer(order).data,
                    ),
                    lambda: _send_status_changed(negotiation, order),
                    lambda: notify_client_booking(
                        client_id=client_profile_id,
                        payload=OrderServiceReadSerializer(order).data,
                    ),
                )
                for step in steps:
                    try:
                        step()
                    except Exception:
                        logger.exception(
                            "Post-accept step failed. order_id=%s", order_id
                        )

            transaction.on_commit(_after_commit)

        return Response(
            {
                "detail": "Negotiation accepted successfully.",
                "order_id": order.order_id,
                "final_price": order.final_price,
                "provider_id": provider.sp_profile.id,
            },
            status=status.HTTP_200_OK,
        )

    except ObjectDoesNotExist as e:
        logger.warning(
            "Provider lookup failed for user_id=%s: %s",
            request.user.id,
            str(e),
        )
        return Response(
            {"error": str(e)},
            status=status.HTTP_404_NOT_FOUND,
        )

    except Exception:
        logger.exception(
            "Unexpected error accepting negotiation for user_id=%s",
            request.user.id,
        )
        return Response(
            {"error": "An unexpected error occurred while accepting the negotiation."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

##websocket heper

def _send_status_changed(negotiation, order):
    channel_layer = get_channel_layer()

    status_payload = {
        "negotiation_id": negotiation.negotiation_id,
        "status": negotiation.status,
        "final_price": str(order.final_price),
        "order_id": order.order_id,
    }

    async_to_sync(channel_layer.group_send)(
        f"negotiation_{negotiation.negotiation_id}",
        build_negotiation_event(
            "negotiation_status_changed",
            negotiation.negotiation_id,
            status_payload,
        ),
    )

    async_to_sync(channel_layer.group_send)(
        f"client_{order.client.client_profile.id}",
        {
            "type": "negotiation_status_changed",
            "data": status_payload,
        },
    )



# ---------------- Additional endpoints ----------------

@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@permission_classes([IsAuthenticated])
@authentication_classes([ClientJWTAuthentication])
def negotiations_by_order(request, order_id):

    try:
        client = get_client_details(request)

        # 🔒 RLS: ensure order belongs to this client
        order = get_object_or_404(
            OrderService,
            pk=order_id,
            client=client   # or client_fk depending on schema
        )

        allowed_statuses = ['pending', 'in-negotiation','rescheduled']

        if order.status not in allowed_statuses:
            return Response(
                {
                    "detail": "Negotiations are not available for this order status.",
                    "status": order.status
                },
                status=status.HTTP_403_FORBIDDEN
            )

        negotiations = Negotiation.objects.filter(
            service_order=order
        ).order_by('-created_at')

        serializer = NegotiationReadSerializer(
            negotiations,
            many=True
        )

        return Response(serializer.data)

    except OrderService.DoesNotExist:
        return Response(
            {
                "detail": "Order not found or access denied."
            },
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
        logger.exception("Error fetching negotiations by order")

        return Response(
            {
                "detail": "Unexpected server error."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([HeavyReadThrottle])
def negotiations_by_order_and_provider(request, order_id):
    """
    Get negotiations for a specific order belonging to the authenticated provider.
    Rounds are paginated: optional ?before=<round pk>&limit=<n>.
    """
    try:
        try:
            before = request.query_params.get("before")
            before = int(before) if before else None
            limit = min(
                int(request.query_params.get("limit", ROUNDS_PAGE_SIZE)),
                50,
            )
            if limit < 1:
                raise ValueError
        except ValueError:
            return Response(
                {"error": "Invalid parameters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile = get_sp_profile(request)
        provider = ServiceProvider.objects.get(sp_profile=profile)

        order = get_object_or_404(OrderService, pk=order_id)

        negotiations = list(
            Negotiation.objects
            .filter(
                service_order=order,
                provider_for_negotiation__provider=provider,
            )
            .select_related("provider_for_negotiation")
            .order_by("-created_at")
        )

        ctx = {"before": before, "limit": limit, "has_more": {}}
        data = ProviderNegotiationReadSerializer(
            negotiations, many=True, context=ctx
        ).data  # evaluate before reading ctx["has_more"]

        # The chat uses the first negotiation, so the header describes it.
        first = negotiations[0] if negotiations else None
        has_more = bool(first and ctx["has_more"].get(first.pk))

        response = Response(data, status=status.HTTP_200_OK)
        response["X-Has-More-Rounds"] = "true" if has_more else "false"
        return response

    except Http404:
        # get_object_or_404 raises Http404, which is not an ObjectDoesNotExist,
        # so without this it fell into the catch-all and returned a 500.
        raise

    except ObjectDoesNotExist as e:
        logger.warning(
            "Negotiation lookup failed for user_id=%s: %s",
            request.user.id,
            str(e),
        )
        return Response(
            {"error": str(e)},
            status=status.HTTP_404_NOT_FOUND,
        )

    except Exception:
        logger.exception(
            "Unexpected error retrieving negotiations for user_id=%s",
            request.user.id,
        )
        return Response(
            {"error": "An unexpected error occurred while retrieving negotiations."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class BookingsPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 20 


@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def bookings_by_invited_provider(request, id):

    # RLS: the URL id is never used for authorization. The provider can
    # only ever read their own invited bookings.
    if str(request.user.id) != str(id):
        return Response(
            {"detail": "You do not have permission to view these bookings."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        orders = (
            OrderService.objects
            .filter(
                invited_providers=request.user,   # from the token, not the URL
                status__in=[
                    'pending',
                    'in_progress',
                    'in-negotiation',
                    'rescheduled',
                ],
            )
            .distinct()
            .select_related("client", "service_required")
            .order_by('-date_and_time_created', '-pk')
        )

        paginator = BookingsPagination()
        page = paginator.paginate_queryset(orders, request)

        serializer = OrderServiceReadSerializer(page, many=True)

        return paginator.get_paginated_response(serializer.data)

    except Exception:
        logger.exception(
            "Unexpected error retrieving invited-provider bookings. "
            "provider_id=%s",
            request.user.id,
        )

        return Response(
            {
                "detail": "Unable to retrieve bookings at this time. Please try again later."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    

@api_view(["PATCH"])
@throttle_classes([BookingLikeWriteThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def update_order_service(request, order_id):

    # RLS
    client = get_object_or_404(
        ClientDetails,
        client_profile=request.user
    )

    order = get_object_or_404(
        OrderService,
        order_id=order_id,
        client=client,
    )

    serializer = OrderServicePatchSerializer(
        order,
        data=request.data,
        partial=True,
        context={"request": request},
    )

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )

    updated_order = serializer.save()

    return Response(
        {
            "success": True,
            "message": "Order updated successfully.",
            "data": OrderServiceReadSerializer(
                updated_order
            ).data,
        },
        status=status.HTTP_200_OK,
    )

@api_view(["POST"])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def cancel_order(request):
    

    serializer = CancelOrderSerializer(data=request.data)
    if not serializer.is_valid():
        print(f"[Diagnostic] Serializer validation failed: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    order_id = serializer.validated_data["order_id"]

    try:
        order = OrderService.objects.get(
            order_id=order_id,
            client__client_profile=request.user
        )
    except OrderService.DoesNotExist:
        print(f"[Diagnostic] Order {order_id} not found for User {request.user}")
        return Response(
            {"success": False, "message": "Order not found or permission denied."},
            status=status.HTTP_404_NOT_FOUND
        )

    try:
        OrderStatusService.set_status(order, "canceled")
        return Response(
            {"success": True, "message": "Order cancelled successfully."},
            status=status.HTTP_200_OK
        )
    except Exception as engine_error:
        
       
        return Response(
            {"success": False, "error_details": str(engine_error)},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    
@api_view(['GET'])
@permission_classes([IsAuthenticated])
@authentication_classes([ClientJWTAuthentication])
@throttle_classes([HeavyReadThrottle])
def pending_orders_by_client_id(request, client_id):

    try:
        client = get_client_details(request)

        # 🔒 STRICT RLS CHECK (safe, not id comparison hack)
        if client.client_profile.id != client_id:
            return Response(
                {
                    "detail": "You do not have permission to access records for this profile."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        negotiation_subquery = Negotiation.objects.filter(
            service_order=OuterRef('pk')
        )

        orders = OrderService.objects.filter(
            client=client,
            status__in=['pending', 'in-negotiation','rescheduled','overdue']
        ).annotate(
            in_negotiation=Exists(negotiation_subquery)
        ).order_by('-date_and_time_created')

        serializer = OrderServiceReadSerializer(orders, many=True)
        data = serializer.data

        # safe post-processing (kept as-is to preserve frontend contract)
        for i, order in enumerate(orders):
            data[i]['in_negotiation'] = order.in_negotiation

        return Response(data, status=status.HTTP_200_OK)

    except Exception:
        logger.exception("Error fetching pending orders by client")

        return Response(
            {
                "detail": "Unexpected server error."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    



@api_view(['POST'])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([HeavyReadThrottle])
def remove_from_invited_providers(request, order_id):
    """
    Allows the authenticated provider to remove themselves
    from an order's invited providers list.

    If no invited providers remain, the order is automatically cancelled.
    """

    order = get_object_or_404(OrderService, pk=order_id)

    serializer = RemoveInvitedProviderSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    provider = request.user

    if not order.invited_providers.filter(pk=provider.pk).exists():
        return Response(
            {
                "error": "You are not an invited provider for this order."
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    with transaction.atomic():
        # Remove the provider
        order.invited_providers.remove(provider)
        order_cancelled = False

        # Cancel the order if nobody is left to invite
        if not order.invited_providers.exists():
            order.status = "cancelled"
            order.save(update_fields=["status"])
            order_cancelled = True


        payload = OrderServiceReadSerializer(order).data

        transaction.on_commit(
            lambda: notify_provider_booking_update(
                provider_id=provider.id,
                payload=payload,
            )
        )
        EventBus.emit(
        ProviderDeclinedInvitationEvent({
            "order": order,
            "provider": provider,
            "order_cancelled": order_cancelled,
        })
    )

    return Response(
        {
            "message": "You have successfully removed yourself from this booking invitation.",
            "order_status": order.status,
        },
        status=status.HTTP_200_OK,
    )
MIN_OFFER_RATIO = Decimal("0.60") 

@api_view(['POST'])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([HeavyReadThrottle])
def provider_start_round(request, negotiation_id):
    """
    Allows a provider to start or respond to a negotiation round.
    Delegates order and negotiation status updates to signals.
    """
    negotiation = get_object_or_404(Negotiation, pk=negotiation_id)
    order = negotiation.service_order

    if negotiation.provider_for_negotiation.provider.sp_profile.id != request.user.id:
        return Response(
            {"detail": "You do not have permission to modify this order."},
            status=status.HTTP_403_FORBIDDEN
        )

    # Prevent negotiation if order or negotiation is already finalized
    if order.status in ['accepted', 'cancelled'] or negotiation.status in ['accepted', 'cancelled']:
        return Response(
            {"error": f"Negotiation cannot continue. This order is {order.status} and negotiation is {negotiation.status}."},
            status=status.HTTP_400_BAD_REQUEST
        )

    serializer = NegotiationRoundWriteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    offered_price = serializer.validated_data['offered_price']
    message = serializer.validated_data.get('message', '')

    if order.proposal_price is not None:
        min_allowed = (order.proposal_price * MIN_OFFER_RATIO).quantize(Decimal("0.01"))

        if offered_price < min_allowed:
            return Response(
                {
                    "error": (         
                        f"proposed price. Minimum allowed is R{min_allowed}."
                    ),
                    "minimum_allowed": str(min_allowed),
                },
                status=status.HTTP_400_BAD_REQUEST
            )

    with transaction.atomic():
        if negotiation.round_count >= negotiation.max_rounds:
            return Response(
                {"error": "Maximum negotiation rounds reached."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_round = NegotiationRound.objects.create(
            negotiation=negotiation,
            sender_type="provider",
            offered_price=offered_price,
            message=message,
        )

        provider_profile_id = negotiation.provider_for_negotiation.provider.sp_profile.id
        client_profile_id = order.client.client_profile.id
        round_data = NegotiationRoundReadSerializer(new_round).data
        round_payload = {
            "negotiation_id": negotiation.negotiation_id,
            "round": round_data,
        }

        def _after_commit():
            layer = get_channel_layer()
            async_to_sync(layer.group_send)(
                f"negotiation_{negotiation.negotiation_id}",
                build_negotiation_event(
                    "negotiation_round_created",
                    negotiation.negotiation_id,
                    round_payload,
                ),
            )
            async_to_sync(layer.group_send)(
                f"client_{client_profile_id}",
                {"type": "negotiation_round_created", "data": round_payload},
            )
            notify_provider_booking_update(
                provider_id=provider_profile_id,
                payload=OrderServiceReadSerializer(order).data,
            )

        transaction.on_commit(_after_commit)

        # Handler schedules the Celery push via on_commit as well.
        EventBus.emit(
            NegotiationRoundCreatedEvent({
                "negotiation": negotiation,
                "round": new_round,
                "sender_type": "provider",
            })
        )
        channel_layer = get_channel_layer()

        round_payload = {
            "negotiation_id": negotiation.negotiation_id,
            "round": NegotiationRoundReadSerializer(new_round).data,
        }

        # Sheet-open listeners: NegotiationConsumer forwards the raw event
        # as-is, so it needs the full envelope (type/negotiation_id/timestamp/data).
        async_to_sync(channel_layer.group_send)(
            f"negotiation_{negotiation.negotiation_id}",
            build_negotiation_event(
                "negotiation_round_created",
                negotiation.negotiation_id,
                round_payload,
            ),
        )

        # Client's personal feed: ClientOrderConsumer only forwards
        # event["data"], so send the same round_payload as "data" directly.
        async_to_sync(channel_layer.group_send)(
            f"client_{order.client.client_profile.id}",
            {
                "type": "negotiation_round_created",
                "data": round_payload,
            },
        )
        notify_client_negotiation_round(
            client_id=order.client.client_profile.id,
            payload=build_negotiation_event(
                "negotiation_round_created",
                negotiation.negotiation_id,
                NegotiationRoundReadSerializer(new_round).data
            )["data"],
        )
    

        # Let signals handle:
        # - negotiation.round_count
        # - negotiation.status
        # - order.status / final_price / provider assignment

    read_serializer = NegotiationRoundReadSerializer(new_round)
    return Response(read_serializer.data, status=status.HTTP_201_CREATED)



from django.core.cache import cache

PRICE_PATCH_COOLDOWN_SECONDS = 300  # 5 minutes


@api_view(['PATCH'])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([HeavyReadThrottle])
def patch_order_final_price(request, order_id):
    order = OrderService.objects.filter(order_id=order_id).first()

    if not order:
        return Response(
            {"detail": "Order not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    # ---------------- RLS CHECK (OWNER ONLY) ----------------
    if order.client_id != request.user.id:
        return Response(
            {"detail": "You do not have permission to modify this order."},
            status=status.HTTP_403_FORBIDDEN
        )

    # ---------------- RATE LIMIT (5 MIN PER ORDER) ----------------
    cooldown_key = f"order_final_price_patch:{order_id}"
    last_patched = cache.get(cooldown_key)

    if last_patched is not None:
        retry_after = (
            PRICE_PATCH_COOLDOWN_SECONDS
            - (timezone.now() - last_patched).total_seconds()
        )

        if retry_after > 0:
            return Response(
                {
                    "detail": "You can only update the price once every 5 minutes.",
                    "retry_after_seconds": int(retry_after),
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS
            )

    serializer = OrderFinalPricePatchSerializer(
        order,
        data=request.data,
        partial=True
    )

    if not serializer.is_valid():
        return Response(
            {"detail": "Invalid request."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # ---------------- FINAL PRICE FLOOR ----------------
    new_final_price = serializer.validated_data.get("final_price")

    if new_final_price is not None and order.final_price is not None:
        min_allowed = (
            order.final_price * Decimal("0.33")
        ).quantize(Decimal("0.01"))

        if new_final_price < min_allowed:
            return Response(
                {
                    "error": (
                       
                        f"Minimum allowed is R{min_allowed}."
                    ),
                    "minimum_allowed": str(min_allowed),
                },
                status=status.HTTP_400_BAD_REQUEST
            )

    serializer.save()

    # Only set the cooldown on a successful patch
    cache.set(
        cooldown_key,
        timezone.now(),
        timeout=PRICE_PATCH_COOLDOWN_SECONDS
    )

    EventBus.emit(
        SimpleNamespace(
            name="order.final_price_updated",
            payload={
                "order": order,
                "final_price": serializer.data.get("final_price"),
            }
        )
    )

    return Response(
        {
            "message": "Final price updated successfully.",
            "order_id": order.order_id,
            "final_price": serializer.data.get("final_price"),
        },
        status=status.HTTP_200_OK
    )
    

@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
def negotiation_rounds_by_negotiation(request, negotiation_id):
    """
    Get all rounds for a specific negotiation by its ID.
    """
    negotiation = get_object_or_404(Negotiation, pk=negotiation_id)
    
    # Fetch all rounds related to this negotiation
    rounds = NegotiationRound.objects.filter(negotiation=negotiation).order_by('created_at')
    
    serializer = NegotiationRoundReadSerializer(rounds, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)



@api_view(['POST'])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([HeavyReadThrottle])
def client_start_round(request, negotiation_id):
    try:
        client = get_client_details(request)

        negotiation = get_object_or_404(
            Negotiation.objects.select_related("service_order"),
            pk=negotiation_id,
            service_order__client=client,
        )
        order = negotiation.service_order

        if order.status in ['accepted', 'cancelled'] or negotiation.status in ['accepted', 'cancelled']:
            return Response(
                {"detail": "Negotiation cannot continue in current state."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = NegotiationRoundWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        offered_price = serializer.validated_data['offered_price']
        message = serializer.validated_data.get('message', '')

        if order.proposal_price is not None:
            min_allowed = (order.proposal_price * MIN_OFFER_RATIO).quantize(Decimal("0.01"))
            if offered_price < min_allowed:
                return Response(
                    {
                        "error": f"Offered price is too low. Minimum allowed is R{min_allowed}.",
                        "minimum_allowed": str(min_allowed),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        with transaction.atomic():
            # Lock so concurrent sends can't both slip past the round limit.
            locked = Negotiation.objects.select_for_update().get(pk=negotiation.pk)

            if locked.round_count >= locked.max_rounds:
                return Response(
                    {"detail": "Maximum negotiation rounds reached."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            new_round = NegotiationRound.objects.create(
                negotiation=locked,
                sender_type="client",
                offered_price=offered_price,
                message=message,
            )

            EventBus.emit(
                NegotiationCreatedEvent({
                    "negotiation": locked,
                    "round": new_round,
                })
            )

        return Response(
            NegotiationRoundReadSerializer(new_round).data,
            status=status.HTTP_201_CREATED,
        )

    except Http404:
        return Response(
            {"detail": "Negotiation not found or access denied."},
            status=status.HTTP_404_NOT_FOUND,
        )
    except ValidationError:
        raise  # let DRF return the field errors as 400
    except Exception:
        logger.exception("Client counter offer failed")
        return Response(
            {"detail": "Unexpected server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    
    
@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def accepted_orders_by_provider(request):

    try:
        # 🔒 RLS: authenticated provider only
        provider = ServiceProvider.objects.select_related(
            "sp_profile"
        ).get(
            sp_profile=request.user
        )

        orders = (
            OrderService.objects
            .filter(
                provider_for_service__provider=provider,
                status="accepted"
            )
            .order_by("-date_and_time_created")
        )

        serializer = OrderServiceReadSerializer(
            orders,
            many=True
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )

    except ServiceProvider.DoesNotExist:
        return Response(
            {"error": "Service provider not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
        logger.exception("Error fetching accepted orders")

        return Response(
            {"error": "Unexpected server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_shipment_by_id(request, shipment_id):
    """
    Returns a single shipment by shipment_id.
    """

    try:
        shipment = Shipment.objects.get(shipment_id=shipment_id)
    except Shipment.DoesNotExist:
        return Response(
            {"error": "Shipment not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    serializer = ShipmentReadSerializer(shipment)
    return Response(serializer.data, status=status.HTTP_200_OK)



from rest_framework.exceptions import APIException
from rest_framework.pagination import PageNumberPagination


class ShipmentsPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 30


ACTIVE_SHIPMENT_STATUSES = ["Pending", "in_transit", "arrived", "delivered", "in_session"]
FILTERABLE_STATUSES = {"pending", "in_transit", "arrived", "in_session", "delivered"}


@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_shipments_by_provider(request):
    """
    Returns a page of active shipments for the authenticated provider.
    Optional query params: page, page_size, status.
    """
    try:
        profile = get_sp_profile(request)
        provider = ServiceProvider.objects.get(sp_profile=profile)

        shipments = (
            Shipment.objects
            .filter(
                # Same result as the chained provider_services -> orders ->
                # booking_items subqueries, as one join.
                service_ordered__order__provider_for_service__provider=provider,
                shipment_status__in=ACTIVE_SHIPMENT_STATUSES,
            )
            # Extend to everything ShipmentReadSerializer touches.
            .select_related("service_ordered__order")
            .order_by("-created_at", "-pk")  # stable order for paging
        )

        raw_status = request.query_params.get("status", "")
        requested = {s.strip().lower() for s in raw_status.split(",") if s.strip()}
        valid_statuses = requested & FILTERABLE_STATUSES

        if valid_statuses:
            # iexact because "Pending" is stored capitalised, the rest lowercase.
            status_q = Q()
            for s in valid_statuses:
                status_q |= Q(shipment_status__iexact=s)
            shipments = shipments.filter(status_q)

        paginator = ShipmentsPagination()
        page = paginator.paginate_queryset(shipments, request)
        serializer = ShipmentReadSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    except APIException:
        # Let DRF handle its own errors. Without this, the catch-all below
        # turns "invalid page" (404) into a 500.
        raise

    except ObjectDoesNotExist as e:
        logger.warning("Provider lookup failed for user_id=%s: %s", request.user.id, str(e))
        return Response({"error": str(e)}, status=status.HTTP_404_NOT_FOUND)

    except Exception:
        logger.exception("Unexpected error while retrieving shipments for user_id=%s", request.user.id)
        return Response(
            {"error": "An unexpected error occurred while retrieving shipments."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    
    

@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_shipments_by_client(request, client_id):

    try:
        # 1️⃣ Get client (ownership-safe lookup)
        client_orders = OrderService.objects.filter(
            client_id=client_id
        )

        if not client_orders.exists():
            return Response(
                {
                    "success": True,
                    "data": []
                },
                status=status.HTTP_200_OK
            )

        # 2️⃣ Booking items
        booking_items = BookingItem.objects.filter(
            order__in=client_orders
        )

        # 3️⃣ Shipments
        shipments = Shipment.objects.filter(
            service_ordered__in=booking_items,
            shipment_status__in=[
                "Pending",
                "in_transit",
                "arrived",
                "delivered",
                "in_session",
                "rescheduled"
            ]
        ).order_by('-shipment_schedule_date', '-shipment_schedule_time')

        serializer = ShipmentReadSerializer(shipments, many=True)

        return Response(
            {
                "success": True,
                "data": serializer.data
            },
            status=status.HTTP_200_OK
        )

    except Exception:
        logger.error("Unexpected error in get_shipments_by_client", exc_info=True)

        return Response(
            {
                "success": False,
                "message": "Unexpected server error."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    


@api_view(["POST"])
@throttle_classes([BookingLikeWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def change_shipment_status(request, shipment_id):
    shipment = get_object_or_404(Shipment, pk=shipment_id)

    new_status = request.data.get("status")
    provider = request.user

    shipment = get_object_or_404(
        Shipment.objects.select_related(
            "service_ordered__order__provider_for_service",
            "service_ordered__order__client__client_profile",
        ),
        shipment_id=shipment_id,
        service_ordered__order__provider_for_service__provider__sp_profile=provider,
    )

    if not new_status:
        return Response(
            {"error": "Status is required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    if shipment.shipment_status == new_status:
        return Response(
            {"detail": f"Shipment already '{new_status}'"},
            status=status.HTTP_200_OK
        )

    try:
        transition_shipment(shipment, new_status)
    except InvalidShipmentTransition as e:
        return Response({"error": str(e)}, status=400)

    order = shipment.service_ordered.order

    notify_client_shipment_status(
        client_id=order.client.client_profile.id,
        payload={
            "shipment_id": shipment.shipment_id,
            "order_id": order.order_id,
            "status": shipment.shipment_status,
        },
    )

    return Response(
        ShipmentReadSerializer(shipment).data,
        status=status.HTTP_200_OK
    )



@api_view(["GET"])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([HeavyReadThrottle])
def client_shipment_routes_view(request, shipment_id):
    """
    GET  -> List routes for a shipment
    POST -> Create a new route for a shipment
    """

    client = request.user

    shipment = get_object_or_404(
        Shipment.objects.select_related(
            "service_ordered__order__provider_for_service"
        ),
        shipment_id=shipment_id,
        service_ordered__order__client__client_profile=client,
    )

    # --------------------
    # GET
    # --------------------
    if request.method == "GET":
        routes = ShipmentRoute.objects.filter(
            shipment=shipment
        ).order_by("-created_at")

        serializer = ShipmentRouteReadSerializer(routes, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)



    return Response(
        serializer.errors,
        status=status.HTTP_400_BAD_REQUEST,
    )




@api_view(["GET", "POST"])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([HeavyReadThrottle])
def shipment_routes_view(request, shipment_id):
    """
    GET  -> List routes for a shipment
    POST -> Create a new route for a shipment
    """

    provider = request.user

    shipment = get_object_or_404(
        Shipment.objects.select_related(
            "service_ordered__order__provider_for_service"
        ),
        shipment_id=shipment_id,
        service_ordered__order__provider_for_service__provider__sp_profile=provider,
    )

    # --------------------
    # GET
    # --------------------
    if request.method == "GET":
        routes = ShipmentRoute.objects.filter(
            shipment=shipment
        ).order_by("-created_at")

        serializer = ShipmentRouteReadSerializer(routes, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    # --------------------
    # POST
    # --------------------
    data = request.data.copy()
    data["shipment_id"] = shipment.shipment_id

    serializer = ShipmentRouteWriteSerializer(data=data)

    if serializer.is_valid():
        route = serializer.save()

        return Response(
            ShipmentRouteReadSerializer(route).data,
            status=status.HTTP_201_CREATED,
        )

    return Response(
        serializer.errors,
        status=status.HTTP_400_BAD_REQUEST,
    )


    
@api_view(["POST"])
@throttle_classes([BookingLikeWriteThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def confirm_shipment(request, shipment_id):

    try:
        # 🔒 RLS: only the owner of the order may confirm the shipment
        shipment = Shipment.objects.select_related(
            "service_ordered__order__client"
        ).get(
            shipment_id=shipment_id,
            service_ordered__order__client__client_profile=request.user
        )

        if shipment.shipment_confirmation:
            return Response(
                {"detail": "Shipment already confirmed"},
                status=status.HTTP_400_BAD_REQUEST
            )

        shipment.shipment_confirmation = True
        shipment.save(update_fields=["shipment_confirmation"])
        push_shipment_status_update(shipment.shipment_id, "arrived")

        if shipment.shipment_status == "arrived":
            transition_shipment(shipment, "delivered")

        serializer = ShipmentReadSerializer(shipment)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )

    except Shipment.DoesNotExist:
        return Response(
            {"detail": "Shipment not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
        logger.exception("Error confirming shipment")

        return Response(
            {"detail": "Unable to confirm shipment at this time."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    


@api_view(["GET"])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([HeavyReadThrottle])
def get_checkin_token(request, shipment_id):
    """
    Client requests a QR code token for a delivered shipment.
    Auto-refresh token if expired.
    """

    try:
        # 🔒 RLS: Shipment must belong to the authenticated client
        shipment = Shipment.objects.select_related(
            "service_ordered__order__client"
        ).get(
            pk=shipment_id,
            service_ordered__order__client__client_profile=request.user
        )

        if shipment.shipment_status != "delivered":
            return Response(
                {"detail": "Shipment not delivered yet"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get latest unused token
        token = (
            SessionToken.objects
            .filter(
                shipment=shipment,
                session__isnull=True
            )
            .order_by("-created_at")
            .first()
        )

        # Create a new token if missing or expired
        if not token or not token.is_valid():
            token = SessionToken.objects.create(
                shipment=shipment,
                token_expiry=timezone.now() + timedelta(minutes=15)
            )

        serializer = SessionTokenReadSerializer(token)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )

    except Shipment.DoesNotExist:
        return Response(
            {"detail": "Shipment not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
        logger.exception("Error retrieving check-in token")

        return Response(
            {
                "detail": "Unable to retrieve check-in token."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )




@api_view(["POST"])
@throttle_classes([BookingLikeWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def confirm_checkin(request):

    try:
        serializer = ConfirmCheckinSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

       
        if "expired_token" in serializer.validated_data:
            old_token = serializer.validated_data["expired_token"]

            # 🔒 RLS
            if old_token.shipment.service_provider.sp_profile != request.user:
                return Response(
                    {"detail": "You do not have permission to use this token."},
                    status=status.HTTP_403_FORBIDDEN
                )

            new_token = SessionToken.create_new(
                shipment=old_token.shipment,
                session=old_token.session
            )

            return Response(
                {
                    "detail": "Token expired.",
                    "new_token": str(new_token.checkin_token),
                    "expires_at": new_token.token_expiry,
                },
                status=status.HTTP_409_CONFLICT
            )

        # ✅ Valid token
        token = serializer.validated_data["token_instance"]
        shipment = token.shipment

        # 🔒 RLS
        if shipment.service_ordered.order.provider_for_service.provider.sp_profile != request.user:
            return Response(
                {
                    "detail": "You do not have permission to check in for this shipment."
                },
                status=status.HTTP_403_FORBIDDEN
            )

        checkin_location = serializer.validated_data["checkin_location"]

        session, created = Session.objects.get_or_create(
            shipment=shipment,
            defaults={
                "checkin_location": checkin_location,
                "checkin_time": timezone.now(),
                "session_status": "in_session",
            }
        )

        if not created and not session.checkin_location:
            session.checkin_location = checkin_location
            session.save(update_fields=["checkin_location"])

        token.session = session
        token.token_expiry = timezone.now()  # burn token
        token.save(update_fields=["session", "token_expiry"])

        if created:
            push_session_created(
        shipment.shipment_id,
        session,
    )

        return Response(
            ConfirmCheckinResponseSerializer(session).data,
            status=status.HTTP_200_OK
        )

    except Exception:
        logger.exception("Error confirming provider check-in")

        return Response(
            {
                "detail": "Unable to confirm check-in at this time."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
@api_view(["GET"])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([HeavyReadThrottle])
def client_get_session_by_shipment(request, shipment_id):
    """
    Retrieve the session associated with a shipment.
    Includes shipment details and session duration.
    """
    try:
        session = Session.objects.select_related(
            "shipment",
            "shipment__service_ordered",
            "shipment__service_ordered__order",
            "shipment__service_ordered__order__client",
            "shipment__service_ordered__order__client__client_profile",
        ).get(
            shipment_id=shipment_id,
            shipment__service_ordered__order__client__client_profile=request.user,
        )
    except Session.DoesNotExist:
        return Response(
            {"detail": "Session not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    serializer = SessionReadSerializer(session)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(["GET"])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([HeavyReadThrottle])
def get_session_by_shipment(request, shipment_id):
    """
    Retrieve the session associated with a shipment.
    Includes shipment details and session duration.
    """
    try:
        session = Session.objects.select_related(
            "shipment",
            "shipment__service_ordered",
            "shipment__service_ordered__order",
            "shipment__service_ordered__order__provider_for_service",
            "shipment__service_ordered__order__provider_for_service__provider",
            "shipment__service_ordered__order__provider_for_service__provider__sp_profile",
        ).get(
            shipment_id=shipment_id,
            shipment__service_ordered__order__provider_for_service__provider__sp_profile=request.user,
        )
    except Session.DoesNotExist:
        return Response(
            {"detail": "Session not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    serializer = SessionReadSerializer(session)
    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(['POST'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def session_geofence_check(request, session_id):
    """
    Check if the provider is inside the geofence for a session
    and record the location ping.
    """

    try:
        lat = request.data.get("latitude")
        lng = request.data.get("longitude")

        if lat is None or lng is None:
            return Response(
                {"detail": "latitude and longitude are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            lat = float(lat)
            lng = float(lng)
        except (TypeError, ValueError):
            return Response(
                {"detail": "latitude and longitude must be numbers"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 🔒 RLS: provider can only access their own sessions
        session = Session.objects.select_related(
            "shipment",
            "shipment__service_ordered",
            "shipment__service_ordered__order",
            "shipment__service_ordered__order__provider_for_service",
            "shipment__service_ordered__order__provider_for_service__provider",
            
        ).get(
            session_id=session_id,
            shipment__service_ordered__order__provider_for_service__provider__sp_profile=request.user,
        )

        # Geofence center (client address)
        address = session.shipment.service_ordered.order.delivery_address
        center_lat = float(address.latitude)
        center_lng = float(address.longitude)

        # Calculate distance
        distance = calculate_distance_meters(
            center_lat,
            center_lng,
            lat,
            lng
        )

        inside_geofence = (
            distance <= getattr(
                settings,
                "SESSION_GEOFENCE_RADIUS_METERS",
                50
            )
        )

        # Save location ping
        ping = SessionLocationPing.objects.create(
            session=session,
            latitude=lat,
            longitude=lng,
            distance_from_site_meters=distance,
            inside_geofence=inside_geofence
        )

        serializer = SessionLocationPingWriteSerializer(ping)

        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED
        )

    except Session.DoesNotExist:
        return Response(
            {"detail": "Session not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
        logger.exception("Error performing session geofence check")

        return Response(
            {
                "detail": "Unable to process geofence check."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    




@api_view(["PATCH"])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([HeavyReadThrottle])
@transaction.atomic
def cancel_shipment(request, shipment_id):

    # --------------------------------------------
    # RLS: ensure shipment belongs to authenticated client
    # --------------------------------------------
    shipment = get_object_or_404(
        Shipment.objects.select_related(
            "service_ordered__order__client"
        ),
        shipment_id=shipment_id,
        service_ordered__order__client__client_profile=request.user
    )

    booking_item = shipment.service_ordered
    order = booking_item.order

    if shipment.shipment_status in [
        "in_session",
        "completed",
    ]:
        return Response(
            {
                "detail": (
                    "This booking has already started and can no longer be cancelled."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # --------------------------------------------
    # Prevent double cancellation
    # --------------------------------------------
    if shipment.shipment_status == "canceled":
        return Response(
            {"detail": "Shipment already canceled."},
            status=status.HTTP_400_BAD_REQUEST
        )
    

    old_status = shipment.shipment_status

    # --------------------------------------------
    # Update shipment
    # --------------------------------------------
    shipment.shipment_status = "canceled"
    shipment.save(update_fields=["shipment_status", "updated_date"])

    # --------------------------------------------
    # Update order status
    # --------------------------------------------
    OrderStatusService.set_status(order, "canceled")

    # --------------------------------------------
    # Create shipment history
    # --------------------------------------------
    ShipmentHistory.objects.create(
        shipment=shipment,
        previous_status=old_status,
        new_status="cancelled",
        notes="Shipment cancelled by client."
    )

    # --------------------------------------------
    # Emit event (provider notification)
    # --------------------------------------------
    EventBus.emit(
    OrderCancelledEvent(
        {
            "shipment": shipment,
            "order": order
        }
    )
)

    # --------------------------------------------
    # Response (clean contract only)
    # --------------------------------------------
    return Response(
        {
            "success": True,
            "message": "Shipment cancelled successfully",
            "data": {
                "shipment_id": shipment.shipment_id,
                "shipment_status": shipment.shipment_status,
                "order_id": order.order_id,
                "order_status": order.status,
            }
        },
        status=status.HTTP_200_OK
    )

@api_view(["PATCH"])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([HeavyReadThrottle])
@transaction.atomic
def provider_cancel_shipment(request, shipment_id):

    shipment = get_object_or_404(
        Shipment.objects.select_related(
            "service_ordered__order__provider_for_service__provider__sp_profile",
            "service_ordered__order__client",
        ),
        shipment_id=shipment_id,
        service_ordered__order__provider_for_service__provider__sp_profile=request.user,
    )

    booking_item = shipment.service_ordered
    order = booking_item.order

    if shipment.shipment_status in [
        "in_session",
        "completed",
    ]:
        return Response(
            {
                "detail": "This booking has already started and can no longer be cancelled."
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if shipment.shipment_status == "canceled":
        return Response(
            {
                "detail": "Shipment already cancelled."
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    old_status = shipment.shipment_status

    shipment.shipment_status = "canceled"
    shipment.save(update_fields=["shipment_status", "updated_date"])

    OrderStatusService.set_status(order, "canceled")

    ShipmentHistory.objects.create(
        shipment=shipment,
        previous_status=old_status,
        new_status="canceled",
        notes="Shipment cancelled by provider.",
    )

    EventBus.emit(
        ProviderOrderCancelledEvent(
            {
                "shipment": shipment,
                "order": order,
                "provider": shipment.service_ordered.order.provider_for_service,
            }
        )
    )

    return Response(
        {
            "success": True,
            "message": "Shipment cancelled successfully.",
            "data": {
                "shipment_id": shipment.shipment_id,
                "shipment_status": shipment.shipment_status,
                "order_id": order.order_id,
                "order_status": order.status,
            },
        },
        status=status.HTTP_200_OK,
    )

@api_view(["PATCH"])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([HeavyReadThrottle])
@transaction.atomic
def reschedule_shipment(request, shipment_id):

    # --------------------------------------------
    # RLS: ensure shipment belongs to client
    # --------------------------------------------
    shipment = get_object_or_404(
        Shipment.objects.select_related(
            "service_ordered__order__client"
        ),
        shipment_id=shipment_id,
        service_ordered__order__client__client_profile=request.user
    )

    booking_item = shipment.service_ordered
    order = booking_item.order

    # --------------------------------------------
    # Old schedule snapshot
    # --------------------------------------------
    old_date = shipment.shipment_schedule_date
    old_time = shipment.shipment_schedule_time

    # --------------------------------------------
    # Input validation
    # --------------------------------------------
    new_date = request.data.get("shipment_schedule_date")
    new_time = request.data.get("shipment_schedule_time")

    if not new_date or not new_time:
        return Response(
            {"detail": "shipment_schedule_date and shipment_schedule_time are required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        new_date = timezone.datetime.strptime(new_date, "%Y-%m-%d").date()
        new_time = timezone.datetime.strptime(new_time, "%H:%M:%S").time()
    except ValueError:
        return Response(
            {"detail": "Invalid date or time format"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # --------------------------------------------
    # RULE 1: cannot reschedule into the past
    # --------------------------------------------
    if new_date < timezone.now().date():
        return Response(
            {"detail": "Cannot reschedule to a past date"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # --------------------------------------------
    # RULE 2: cannot be earlier than current schedule
    # (strong business constraint)
    # --------------------------------------------
    old_datetime = timezone.datetime.combine(old_date, old_time)
    new_datetime = timezone.datetime.combine(new_date, new_time)

    if new_datetime < old_datetime:
        return Response(
            {
                "detail": (
                    "New schedule cannot be earlier than the current scheduled date and time."
                )
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    if shipment.shipment_status in [
        "in_session",
        "completed",
    ]:
        return Response(
            {
                "detail": (
                    "This booking has already started and can no longer be rescheduled."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # --------------------------------------------
    # Update shipment
    # --------------------------------------------
    shipment.shipment_schedule_date = new_date
    shipment.shipment_schedule_time = new_time
    shipment.shipment_status = "rescheduled"

    shipment.save(update_fields=[
        "shipment_schedule_date",
        "shipment_schedule_time",
        "shipment_status",
        "updated_date"
    ])

    # --------------------------------------------
    # Update order
    # --------------------------------------------
    OrderStatusService.set_status(order, "rescheduled")

    # --------------------------------------------
    # History tracking
    # --------------------------------------------
    ShipmentHistory.objects.create(
        shipment=shipment,
        previous_status="previous_schedule",
        new_status="rescheduled",
        notes=f"Rescheduled from {old_date} {old_time} → {new_date} {new_time}"
    )

    # --------------------------------------------
    # Event emit (provider notification)
    # --------------------------------------------
    # --------------------------------------------
# Event emit (provider notification)
# --------------------------------------------
    EventBus.emit(
    OrderRescheduledEvent(
        payload={
            "order": order,
            "shipment": shipment,
            "old_date": old_date,
            "old_time": old_time,
        }
    )
)

    # --------------------------------------------
    # Clean response (no stack traces ever)
    # --------------------------------------------
    return Response(
        {
            "success": True,
            "message": "Shipment rescheduled successfully",
            "data": {
                "order_status": order.status,
            }
        },
        status=status.HTTP_200_OK
    )


@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@permission_classes([IsAuthenticated])

def session_location_pings(request, session_id):
    """
    GET all location pings for a given session.
    URL: /api/sessions/<session_id>/pings/
    """
    pings = SessionLocationPing.objects.filter(session__session_id=session_id)
    serializer = SessionLocationPingReadSerializer(pings, many=True)
    return Response(serializer.data)














###add rls

@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([ClientJWTAuthentication])
# @permission_classes([IsAuthenticated])
def session_latest_ping(request, session_id):
    """
    GET the latest location ping for a given session.
    URL: /api/sessions/<session_id>/latest-ping/
    """
    ping = (
        SessionLocationPing.objects
        .filter(session__session_id=session_id)
        .order_by('-created_at')
        .first()
    )

    if not ping:
        return Response({"detail": "No pings found"}, status=404)

    serializer = SessionLocationPingReadSerializer(ping)
    return Response(serializer.data)




@api_view(['PATCH'])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([HeavyReadThrottle])
def update_session_status(request, session_id):

    with transaction.atomic():
        try:
            session = (
                Session.objects
                .select_related(
                    "shipment",
                    "shipment__service_ordered",
                    "shipment__service_ordered__order",
                    "shipment__service_ordered__order__provider_for_service",
                    "shipment__service_ordered__order__provider_for_service__provider",
                    "shipment__service_ordered__order__provider_for_service__provider__sp_profile",
                )
                .select_for_update()
                .get(
                    session_id=session_id,
                    shipment__service_ordered__order__provider_for_service__provider__sp_profile=request.user,
                )
            )
        except Session.DoesNotExist:
            return Response(
                {"detail": "Session not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Prevent reopening sessions
        if session.session_status == "completed":
            return Response(
                {"detail": "Session already completed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_status = request.data.get("session_status")

        if (
            new_status == "completed"
            and not request.data.get("checkout_location")
        ):
            return Response(
                {
                    "detail": "Checkout location required when completing a session."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = SessionStatusUpdateSerializer(
            session,
            data=request.data,
            partial=True,
        )

        serializer.is_valid(raise_exception=True)
        session = serializer.save()

        # Finalize checkout
        if session.session_status == "completed":
            session.checkout_time = timezone.now()
            session.save(update_fields=["checkout_time"])

    # Notify after the transaction commits.
    if session.session_status == "completed":
        push_session_completed(session)

    return Response(
        {
            "message": "Session updated successfully",
            "session_id": session.session_id,
            "session_status": session.session_status,
            "duration_seconds": int(session.duration().total_seconds()),
            "checkout_time": session.checkout_time,
        },
        status=status.HTTP_200_OK,
    )


class RatingsPagination(PageNumberPagination):
    page_size = 5
    page_size_query_param = "page_size"
    max_page_size = 10
    
@api_view(['GET'])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([HeavyReadThrottle])
def get_my_ratings(request):
    sp_profile = get_sp_profile(request)
    session_id = request.query_params.get("session_id")

    ratings = (
        Rating.objects
        .filter(rater_provider__sp_profile=sp_profile)

        .select_related("session__shipment")
        .order_by("-created_at", "-pk")   
    )

    if session_id:
        ratings = ratings.filter(session__session_id=session_id)
        return Response(RatingReadSerializer(ratings, many=True).data)

    paginator = RatingsPagination()
    page = paginator.paginate_queryset(ratings, request)
    serializer = RatingReadSerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)





class ClientRatingsPagination(PageNumberPagination):
    page_size = 7
    page_size_query_param = "page_size"
    max_page_size = 15


@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_ratings_by_client_email(request, client_id):
    """
    Ratings for the authenticated client.
    Optional query params: session_id, page, page_size.
    """
    try:
        client = get_client_details(request)

        # RLS: the URL id must belong to the authenticated client. Same
        # check as pending_orders_by_client_id.
        if client.client_profile.id != client_id:
            return Response(
                {"success": False,
                 "message": "You do not have permission to access records for this profile."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Filter by the authenticated client, not by the id in the URL.
        # Add select_related for the relations RatingReadSerializer nests
        # (session -> shipment -> ...), otherwise each row costs extra queries.
        ratings = Rating.objects.filter(rater_client=client).order_by("-pk")

        session_id = request.query_params.get("session_id")
        if session_id:
            # A single session has very few ratings: keep the plain list.
            ratings = ratings.filter(session__session_id=session_id)
            return Response(
                RatingReadSerializer(ratings, many=True).data,
                status=status.HTTP_200_OK,
            )

        # Old app versions send no paging params and expect a plain list.
        if "page" not in request.query_params and "page_size" not in request.query_params:
            return Response(
                RatingReadSerializer(ratings, many=True).data,
                status=status.HTTP_200_OK,
            )

        paginator = ClientRatingsPagination()
        page = paginator.paginate_queryset(ratings, request)
        return paginator.get_paginated_response(
            RatingReadSerializer(page, many=True).data
        )

    except APIException:
        # Without this, the paginator's "invalid page" 404 became a 500.
        raise

    except Exception:
        logger.error("Unexpected error in get_ratings_by_client", exc_info=True)
        return Response(
            {"success": False, "message": "Unexpected server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


##public
@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_sp_ratings(request, sp_id):

    try:
        ratings = (
            Rating.objects
            .filter(
                rater_provider__sp_profile__id=sp_id
            )
            .select_related(
                'rater_client'
            )
            .order_by('-created_at')[:3]
        )

        serializer = ClientRatingReadSerializer(
            ratings,
            many=True
        )

        return Response(
            {
                "success": True,
                "data": serializer.data
            },
            status=status.HTTP_200_OK
        )

    except Exception:
        logger.exception(
            "Unexpected error in get_sp_ratings"
        )

        return Response(
            {
                "success": False,
                "message": "Unexpected server error."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    


@api_view(['PATCH'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def submit_client_rating(request, session_id, client_id):

    try:
        rating = Rating.objects.select_related(
            "rater_client",
            "rater_client__client_profile"
        ).get(
            session__session_id=session_id,
            rater_client__client_profile__id=client_id,
            rater_client__client_profile=request.user  # RLS
        )

        serializer = SubmitRatingSerializer(
            rating,
            data=request.data,
            partial=True
        )

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    except Rating.DoesNotExist:
        return Response(
            {"error": "Rating not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
        logger.exception(
            "Unexpected error in submit_client_rating"
        )

        return Response(
            {"error": "Unexpected server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['PATCH'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def submit_provider_rating(request, session_id, provider_id):
    """
    Provider submits rating for client.
    """

    try:
        rating = Rating.objects.select_related(
            "rater_provider",
            "rater_provider__sp_profile"
        ).get(
            session__session_id=session_id,
            rater_provider__sp_profile__id=provider_id,
            rater_provider__sp_profile=request.user  # RLS
        )

        serializer = SubmitRatingSerializer(
            rating,
            data=request.data,
            partial=True
        )

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    except Rating.DoesNotExist:
        return Response(
            {"error": "Rating not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
        logger.exception(
            "Unexpected error in submit_provider_rating"
        )

        return Response(
            {"error": "Unexpected server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    


@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def check_session_status(request, session_id):
    """
    Returns the current session status.
    """

    try:
        session = Session.objects.select_related(
            "shipment__service_ordered__order",
            "shipment__provider__sp_profile"
        ).get(
            session_id=session_id,
            shipment__provider__sp_profile=request.user  # RLS
        )

        return Response(
            {
                "session_id": session.session_id,
                "status": session.shipment.service_ordered.order.status,
                "checkout_time": session.checkout_time
            },
            status=status.HTTP_200_OK
        )

    except Session.DoesNotExist:
        return Response(
            {"error": "Session not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
        logger.exception(
            "Unexpected error in check_session_status"
        )

        return Response(
            {"error": "Unexpected server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )