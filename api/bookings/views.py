from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.db.models import Exists, OuterRef
from api.bookings.services.calculate_distance_meters import calculate_distance_meters
from api.bookings.services.shipment_transition_function import InvalidShipmentTransition, transition_shipment
from api.clientsDB.services.jwt_client_authentication import ClientJWTAuthentication
from api.serviceProvidersDB.models import ProviderService, ServiceProvider
from api.serviceProvidersDB.services.sp_jwt_authentication import SPJWTAuthentication
from plug_backend.throttles import BookingLikeWriteThrottle, HeavyReadThrottle, UserReadThrottle

from .models import BookingItem, NegotiationRound, OrderService, Negotiation, Rating, Session, SessionLocationPing, SessionToken, Shipment, ShipmentRoute
from .serializers import (
    ConfirmCheckinResponseSerializer,
    ConfirmCheckinSerializer,
    NegotiationRoundWriteSerializer,
    OrderFinalPricePatchSerializer,
    OrderServiceReadSerializer,
    OrderServiceWriteSerializer,
    NegotiationReadSerializer,
    NegotiationWriteSerializer,
    NegotiationClientCounterSerializer,
    BookingItemReadSerializer,
    NegotiationRoundReadSerializer,
    RatingReadSerializer,
    RatingWriteSerializer,
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
@throttle_classes([HeavyReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def order_service_create(request):
    print("FILES RECEIVED:", request.FILES)
    print("POST DATA:", request.data)

    serializer = OrderServiceWriteSerializer(
        data=request.data,
        context={'request': request}
    )

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    with transaction.atomic():
        order = serializer.save()

        transaction.on_commit(
            lambda: order.notify_invited_providers_of_new_booking()
        )

    read_serializer = OrderServiceReadSerializer(order)

    return Response(
        read_serializer.data,
        status=status.HTTP_201_CREATED
    )
@api_view(['GET', 'PUT', 'PATCH'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def order_service_detail(request, pk):
    """Retrieve, update, or delete a specific order"""
    order = get_object_or_404(OrderService, pk=pk)

    if request.method == 'GET':
        serializer = OrderServiceReadSerializer(order)
        return Response(serializer.data)

    elif request.method in ['PUT', 'PATCH']:
        serializer = OrderServiceWriteSerializer(order, data=request.data, partial=(request.method == 'PATCH'), context={'request': request})
        if serializer.is_valid():
            order = serializer.save()
            read_serializer = OrderServiceReadSerializer(order)
            return Response(read_serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
@api_view(['GET', 'PUT', 'PATCH'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def provider_order_service_detail(request, pk):
    """Retrieve, update, or delete a specific order"""
    order = get_object_or_404(OrderService, pk=pk)

    if request.method == 'GET':
        serializer = OrderServiceReadSerializer(order)
        return Response(serializer.data)

    elif request.method in ['PUT', 'PATCH']:
        serializer = OrderServiceWriteSerializer(order, data=request.data, partial=(request.method == 'PATCH'), context={'request': request})
        if serializer.is_valid():
            order = serializer.save()
            read_serializer = OrderServiceReadSerializer(order)
            return Response(read_serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

 


# ---------------- Negotiation ----------------

@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def negotiation_list(request):
    """List all negotiations"""
    negotiations = Negotiation.objects.all()
    serializer = NegotiationReadSerializer(negotiations, many=True)
    return Response(serializer.data)


@api_view(['GET', 'PUT', 'PATCH'])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([HeavyReadThrottle])
def negotiation_detail(request, pk):
    """Retrieve or update a negotiation"""
    negotiation = get_object_or_404(Negotiation, pk=pk)

    if request.method == 'GET':
        serializer = NegotiationReadSerializer(negotiation)
        return Response(serializer.data)

    elif request.method in ['PUT', 'PATCH']:
        # Decide if provider or client update
        user = getattr(request, 'user', None)
        is_provider = negotiation.provider_for_negotiation.provider.user == user if negotiation.provider_for_negotiation else False
        is_client = negotiation.service_order.client.client_profile.user == user if negotiation.service_order.client.client_profile else False

        if is_provider:
            serializer_class = NegotiationWriteSerializer
        elif is_client:
            serializer_class = NegotiationClientCounterSerializer
        else:
            return Response({"detail": "You do not have permission to update this negotiation."}, status=status.HTTP_403_FORBIDDEN)

        serializer = serializer_class(negotiation, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            negotiation = serializer.save()
            read_serializer = NegotiationReadSerializer(negotiation)
            return Response(read_serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
@api_view(['POST'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def provider_accept_negotiation(request, negotiation_id):
    """
    Endpoint for a provider to accept a negotiation.
    """
    negotiation = get_object_or_404(Negotiation, pk=negotiation_id)
    order = negotiation.service_order

    # If already accepted, return a friendly message
    if order.status == 'accepted':
        return Response(
            {"detail": "This order has already been accepted."},
            status=status.HTTP_200_OK
        )

    # Get provider for this negotiation
    provider_service = negotiation.provider_for_negotiation
    if not provider_service:
        return Response(
            {"detail": "No provider assigned to this negotiation."},
            status=status.HTTP_400_BAD_REQUEST
        )

    with transaction.atomic():
        # Accept negotiation
        negotiation.provider_response_price = negotiation.provider_response_price or negotiation.proposed_price
        negotiation.status = 'accepted'
        negotiation.last_responder = 'provider'
        negotiation.save()

       
        order.final_price = negotiation.provider_response_price
        order.provider_for_service = provider_service
        order.is_negotiated = True
        order.status = 'accepted'
        order.save()

        # ✅ Clear all invited providers when accepted
        order.invited_providers.clear()

    return Response({
        "detail": "Negotiation accepted successfully.",
        "order_id": order.order_id,
        "final_price": order.final_price,
        "provider": provider_service.provider.sp_profile.email_address
    }, status=status.HTTP_200_OK)




# ---------------- Additional endpoints ----------------

@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
def negotiations_by_order(request, order_id):
    """Get all negotiations for a specific order"""
    order = get_object_or_404(OrderService, pk=order_id)
    negotiations = Negotiation.objects.filter(service_order=order).order_by('-created_at')
    serializer = NegotiationReadSerializer(negotiations, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([HeavyReadThrottle])
def negotiations_by_order_and_provider(request, order_id, email):
    """Get all negotiations for a specific order and provider email"""
    order = get_object_or_404(OrderService, pk=order_id)
    negotiations = Negotiation.objects.filter(
        service_order=order,
        provider_for_negotiation__provider__sp_profile__email_address=email
    ).order_by('-created_at')
    serializer = NegotiationReadSerializer(negotiations, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def bookings_by_invited_provider(request, email):
    """Get all bookings where the given provider email is invited"""
    orders = OrderService.objects.filter(
        invited_providers__provider__sp_profile__email_address=email,
        status__in=['pending', 'in_progress', 'in-negotiation']
    ).distinct().order_by('-date_and_time_created')

    serializer = OrderServiceReadSerializer(orders, many=True)
    return Response(serializer.data)

@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
def pending_orders_by_client_email(request, email):
    """
    Fetch pending orders for a given client email,
    including whether each order is in negotiation.
    """
    try:
        negotiation_subquery = Negotiation.objects.filter(
            service_order=OuterRef('pk')
        )

        orders = (
            OrderService.objects.filter(
                client__client_profile__email_address=email,
                status__in=['pending', 'in-negotiation']
            )
            .annotate(in_negotiation=Exists(negotiation_subquery))
            .order_by('-date_and_time_created')
        )

        serializer = OrderServiceReadSerializer(orders, many=True)
        data = serializer.data

        for i, order in enumerate(orders):
            data[i]['in_negotiation'] = order.in_negotiation

        return Response(data, status=status.HTTP_200_OK)

    except Exception as e:
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

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

    with transaction.atomic():
        # Prevent exceeding the allowed number of rounds
        if negotiation.round_count >= negotiation.max_rounds:
            return Response(
                {"error": "Maximum negotiation rounds reached."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create the new provider round
        new_round = NegotiationRound.objects.create(
            negotiation=negotiation,
            sender_type="provider",
            offered_price=offered_price,
            message=message,
        )

        # Let signals handle:
        # - negotiation.round_count
        # - negotiation.status
        # - order.status / final_price / provider assignment

    read_serializer = NegotiationRoundReadSerializer(new_round)
    return Response(read_serializer.data, status=status.HTTP_201_CREATED)

@api_view(['PATCH'])
@throttle_classes([HeavyReadThrottle])
def patch_order_final_price(request, order_id):
    try:
        order = OrderService.objects.get(order_id=order_id)
    except OrderService.DoesNotExist:
        return Response(
            {"detail": "Order not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = OrderFinalPricePatchSerializer(
        order,
        data=request.data,
        partial=True
    )

    if serializer.is_valid():
        serializer.save()
        return Response(
            {
                "message": "Final price updated successfully.",
                "order_id": order.order_id,
                "final_price": serializer.data.get("final_price"),
            },
            status=status.HTTP_200_OK
        )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


    

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
    """
    Allows a client to start or respond to a negotiation round.
    Delegates order and negotiation status updates to signals.
    """
    negotiation = get_object_or_404(Negotiation, pk=negotiation_id)
    order = negotiation.service_order

    if order.status in ['accepted', 'cancelled'] or negotiation.status in ['accepted', 'cancelled']:
        return Response(
            {"error": f"Negotiation cannot continue. This order is {order.status} and negotiation is {negotiation.status}."},
            status=status.HTTP_400_BAD_REQUEST
        )

    serializer = NegotiationRoundWriteSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    offered_price = serializer.validated_data['offered_price']
    message = serializer.validated_data.get('message', '')

    with transaction.atomic():
        if negotiation.round_count >= negotiation.max_rounds:
            return Response(
                {"error": "Maximum negotiation rounds reached."},
                status=status.HTTP_400_BAD_REQUEST
            )

        new_round = NegotiationRound.objects.create(
            negotiation=negotiation,
            sender_type="client",
            offered_price=offered_price,
            message=message,
        )

        # Signals will handle:
        # - negotiation.round_count
        # - negotiation.status
        # - order.status / final_price if provider accepts

    read_serializer = NegotiationRoundReadSerializer(new_round)
    return Response(read_serializer.data, status=status.HTTP_201_CREATED)

@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def accepted_orders_by_provider_email(request, email):
    """
    Fetch all orders accepted by a provider using their email address.
    """
    try:
        orders = OrderService.objects.filter(
            provider_for_service__provider__sp_profile__email_address=email,
            status='accepted'
        ).order_by('-date_and_time_created')

        serializer = OrderServiceReadSerializer(orders, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
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



@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_shipments_by_provider(request, provider_email):
    """
    Returns all shipments for a given provider based on provider email
    filtered by specific statuses.
    """

    # 1️⃣ Find the ServiceProvider
    try:
        provider = ServiceProvider.objects.get(
            sp_profile__email_address=provider_email
        )
    except ServiceProvider.DoesNotExist:
        return Response({"error": "Provider not found."}, status=status.HTTP_404_NOT_FOUND)

    # 2️⃣ Get all ProviderService instances for this provider
    provider_services = ProviderService.objects.filter(provider=provider)

    # 3️⃣ Get all OrderService instances assigned to these provider_services
    provider_orders = OrderService.objects.filter(provider_for_service__in=provider_services)

    # 4️⃣ Get BookingItems linked to these orders
    booking_items = BookingItem.objects.filter(order__in=provider_orders)

    # 5️⃣ Get all Shipments linked to these booking items with specific statuses
    shipments = Shipment.objects.filter(
        service_ordered__in=booking_items,
        shipment_status__in=[
            "Pending",
            "in_transit",
            "arrived",
            "delivered",
            "in_session"
        ]
    ).order_by('-created_at')  # newest first

    # 6️⃣ Serialize and return
    serializer = ShipmentReadSerializer(shipments, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)



@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_shipments_by_client(request, client_email):
    """
    Returns all shipments for a given client based on client email.
    Only includes shipments with statuses: pending, in_transit, arrived, delivered, in_session.
    Newest shipments are returned first.
    """

    # 1️⃣ Get all orders belonging to this client
    client_orders = OrderService.objects.filter(
        client__client_profile__email_address=client_email
    )

    if not client_orders.exists():
        return Response([], status=status.HTTP_200_OK)

    # 2️⃣ Get booking items linked to these orders
    booking_items = BookingItem.objects.filter(order__in=client_orders)

    # 3️⃣ Get shipments linked to these booking items with specific statuses
    shipments = Shipment.objects.filter(
        service_ordered__in=booking_items,
        shipment_status__in=[
            "Pending",
            "in_transit",
            "arrived",
            "delivered",
            "in_session"
        ]
    ).order_by('-shipment_schedule_date', '-shipment_schedule_time')

    # 4️⃣ Serialize and return
    serializer = ShipmentReadSerializer(shipments, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)

@api_view(["POST"])
@throttle_classes([BookingLikeWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def change_shipment_status(request, shipment_id):
    shipment = get_object_or_404(Shipment, pk=shipment_id)

    new_status = request.data.get("status")

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

    return Response(
        ShipmentReadSerializer(shipment).data,
        status=status.HTTP_200_OK
    )





@api_view(["GET", "POST"])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([HeavyReadThrottle])
# @permission_classes([IsAuthenticated])
def shipment_routes_view(request, shipment_id):
    """
    GET  -> List routes for a shipment
    POST -> Create a new route for a shipment
    """

    # --------------------
    # GET: Read routes
    # --------------------
    if request.method == "GET":
        routes = ShipmentRoute.objects.filter(
            shipment_id=shipment_id
        ).order_by("-created_at")

        serializer = ShipmentRouteReadSerializer(routes, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    # --------------------
    # POST: Create route
    # --------------------
    if request.method == "POST":
        data = request.data.copy()
        data["shipment_id"] = shipment_id

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
    shipment = get_object_or_404(Shipment, shipment_id=shipment_id)

    if shipment.shipment_confirmation:
        return Response(
            {"detail": "Shipment already confirmed"},
            status=status.HTTP_400_BAD_REQUEST
        )

    shipment.shipment_confirmation = True
    shipment.save(update_fields=["shipment_confirmation"])

    
    if shipment.shipment_status == "arrived":
        
        transition_shipment(shipment, "delivered")

    serializer = ShipmentReadSerializer(shipment)
    return Response(serializer.data, status=status.HTTP_200_OK)

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
        shipment = Shipment.objects.select_related(
            "service_ordered__order"
        ).get(pk=shipment_id)
    except Shipment.DoesNotExist:
        return Response(
            {"detail": "Shipment not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    if shipment.shipment_status != "delivered":
        return Response(
            {"detail": "Shipment not delivered yet"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # 🔍 Get latest token (if any)
    token = (
        SessionToken.objects
        .filter(shipment=shipment, session__isnull=True)
        .order_by("-created_at")
        .first()
    )

    # 🔁 Create new token if none or expired
    if not token or not token.is_valid():
        token = SessionToken.objects.create(
            shipment=shipment,
            token_expiry=timezone.now() + timedelta(minutes=15)
        )

    serializer = SessionTokenReadSerializer(token)
    return Response(serializer.data, status=status.HTTP_200_OK)






@api_view(["POST"])
@throttle_classes([BookingLikeWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@transaction.atomic
def confirm_checkin(request):
    serializer = ConfirmCheckinSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    # 🔄 Expired token path
    if "expired_token" in serializer.validated_data:
        old_token = serializer.validated_data["expired_token"]

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

    # ✅ Valid token path
    token = serializer.validated_data["token_instance"]
    shipment = token.shipment
    checkin_location = serializer.validated_data["checkin_location"]

    session, created = Session.objects.get_or_create(
        shipment=shipment,
        defaults={
            "checkin_location": checkin_location,
            "checkin_time": timezone.now(),
            "session_status": "in_session"

        }
    )

    if not created and not session.checkin_location:
        session.checkin_location = checkin_location
        session.save(update_fields=["checkin_location"])

    token.session = session
    token.token_expiry = timezone.now()  # 🔒 burn token
    token.save(update_fields=["session", "token_expiry"])

    return Response(
        ConfirmCheckinResponseSerializer(session).data,
        status=status.HTTP_200_OK
    )


@api_view(["GET"])
@throttle_classes([HeavyReadThrottle])
def get_session_by_shipment(request, shipment_id):
    """
    Retrieve the session associated with a shipment.
    Includes shipment details and session duration.
    """
    try:
        session = Session.objects.get(shipment_id=shipment_id)
    except Session.DoesNotExist:
        return Response(
            {"detail": "Session not found for this shipment."},
            status=status.HTTP_404_NOT_FOUND
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
    lat = request.data.get("latitude")
    lng = request.data.get("longitude")
    
    

    if lat is None or lng is None:
        return Response(
            {"detail": "latitude and longitude are required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Convert to float safely
    try:
        lat = float(lat)
        lng = float(lng)
    except ValueError:
        return Response(
            {"detail": "latitude and longitude must be numbers"},
            status=status.HTTP_400_BAD_REQUEST
        )

    session = get_object_or_404(Session, session_id=session_id)

    # Geofence center (client address)
    address = session.shipment.service_ordered.order.delivery_address
    center_lat = address.latitude
    center_lng = address.longitude

    # Calculate distance
    distance = calculate_distance_meters(center_lat, center_lng, lat, lng)
    inside_geofence = distance <= getattr(settings, "SESSION_GEOFENCE_RADIUS_METERS", 50)

    # Save location ping
    ping = SessionLocationPing.objects.create(
        session=session,
        latitude=lat,
        longitude=lng,
        distance_from_site_meters=distance,
        inside_geofence=inside_geofence
    )

    serializer = SessionLocationPingWriteSerializer(ping)

    return Response(serializer.data, status=status.HTTP_201_CREATED)



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

@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
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

    try:
        session = Session.objects.get(session_id=session_id)
    except Session.DoesNotExist:
        return Response(
            {"detail": "Session not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Prevent reopening sessions
    if session.session_status == "completed":
        return Response(
            {"detail": "Session already completed."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    new_status = request.data.get("session_status")

    if new_status == "completed" and not request.data.get("checkout_location"):
        return Response(
            {"detail": "Checkout location required when completing a session."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    serializer = SessionStatusUpdateSerializer(
        session,
        data=request.data,
        partial=True,
    )

    serializer.is_valid(raise_exception=True)
    session = serializer.save()

    # finalize checkout
    if session.session_status == "completed":
        session.checkout_time = timezone.now()
        session.save(update_fields=["checkout_time"])

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

@api_view(['GET'])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([HeavyReadThrottle])
def get_ratings_by_provider_email(request, email):
    """
    Get ratings for a provider.
    Optional query param:
        ?session_id=5
    """

    session_id = request.query_params.get("session_id")

    ratings = Rating.objects.filter(
        rater_provider__sp_profile__email_address=email
    )

    if session_id:
        ratings = ratings.filter(session__session_id=session_id)

    serializer = RatingReadSerializer(ratings, many=True)
    return Response(serializer.data)



@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_ratings_by_client_email(request, email):
    """
    Get ratings for a client.
    Optional query param:
            
    """

    session_id = request.query_params.get("session_id")

    ratings = Rating.objects.filter(
        rater_client__client_profile__email_address=email
    )

    if session_id:
        ratings = ratings.filter(session__session_id=session_id)

    serializer = RatingReadSerializer(ratings, many=True)
    return Response(serializer.data)

@api_view(['PATCH'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def submit_client_rating(request, session_id, client_email):
    """
    Client submits rating for provider.
    """

    try:
        rating = Rating.objects.get(
            session__session_id=session_id,
            rater_client__client_profile__email_address=client_email
        )
    except Rating.DoesNotExist:
        return Response(
            {"error": "Rating not found."},
            status=status.HTTP_404_NOT_FOUND
        )


    serializer = SubmitRatingSerializer(
        rating,
        data=request.data,
        partial=True
    )

    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['PATCH'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def submit_provider_rating(request, session_id, provider_email):
    """
    Provider submits rating for client.
    """

    try:
        rating = Rating.objects.get(
    session__session_id=session_id,
    rater_provider__sp_profile__email_address=provider_email
)
    except Rating.DoesNotExist:
        return Response(
            {"error": "Rating not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = SubmitRatingSerializer(
        rating,
        data=request.data,
        partial=True
    )

    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@throttle_classes([HeavyReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def check_session_status(request, session_id):
    """
    Returns the current session status.
    Used by client app to detect when session is completed.
    """

    try:
        session = Session.objects.select_related(
            "shipment__service_ordered__order"
        ).get(session_id=session_id)

        return Response({
            "session_id": session.session_id,
            "status": session.shipment.service_ordered.order.status,
            "checkout_time": session.checkout_time
        })

    except Session.DoesNotExist:
        return Response(
            {"error": "Session not found"},
            status=status.HTTP_404_NOT_FOUND
        )
