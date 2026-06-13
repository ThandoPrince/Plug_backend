from decimal import Decimal
import json
import time
from django.db import transaction, OperationalError
from django.db import IntegrityError, transaction
from django.forms import ValidationError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
import logging
from django.db.models import Count, Q, OuterRef, Subquery
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from api.clientsDB.models.models import DeviceToken
from api.clientsDB.services.jwt_client_authentication import ClientJWTAuthentication
from api.serviceProvidersDB.services.service_validator import validate_service_submission
from api.serviceProvidersDB.services.sp_jwt_authentication import SPJWTAuthentication
from plug_backend.helpers.auth_helpers import get_service_provider
from plug_backend.throttles import AuthThrottle, LiveLocationReadThrottle, LiveLocationWriteThrottle, ProfileWriteThrottle, RegisterThrottle, UploadThrottle, UserReadThrottle
from plug_backend.utils.sp_jwt_helper import generate_sp_tokens
from .models import CostOfService, CostOfServiceImage, ProviderService, SPLiveLocation, SPLocationHistory, SPProfile, ServiceGroup, Service, ServiceProvider, Address
from .serializers import (
    CostOfServiceImageReadSerializer,
    CostOfServiceImageWriteSerializer,
    CostOfServiceSerializer,
    DeviceTokenWriteSerializer,
    ProviderSeviceSerializer,
    SPAddressDocumentWriteSerializer,
    SPLiveLocationSerializer,
    SPLoginSerializer,
    SPProfileReadSerializer,
    SPProfileWriteSerializer,
    ServiceGroupSerializer,
    ServiceProviderPatchSerializer,
    ServiceProviderReadSerializer,
    ServiceProviderWriteSerializer,
    ServiceReadSerializer,
    ServiceSerializer,
    SPAddressSerializer,
    ServiceWriteSerializer
)

logger = logging.getLogger(__name__)  ##do not remove




@api_view(['POST'])
@throttle_classes([AuthThrottle])
def sp_login(request):
    try:
        serializer = SPLoginSerializer(data=request.data)
        
        if serializer.is_valid():
            user = serializer.validated_data["user"]
            tokens = generate_sp_tokens(user)
            
            return Response({
                "success": True,
                "message": "Login successful",
                "data": {
                    "email": user.email_address,
                    "is_profile_completed": user.is_profile_completed,
                    "access_token": tokens["access"],
                    "refresh_token": tokens["refresh"],


                    
                }
            }, status=status.HTTP_200_OK)

        # Handle Validation Errors (400)
        # We extract the first error message for a cleaner Flutter snackbar
        error_data = serializer.errors
        first_error = next(iter(error_data.values()))[0] if error_data else "Invalid data"

        return Response({
            "success": False,
            "message": first_error,
            "errors": error_data
        }, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        # Handle Unexpected Server Errors (500)
        logger.error(f"Login Exception: {str(e)}")
        return Response({
            "success": False,
            "message": "A server error occurred. Please try again later."
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(["POST"])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def sp_add_address_document(request):
    print("FILES RECEIVED:", request.FILES)
    print("POST DATA:", request.data)

    address_raw = request.data.get('address')

    if not address_raw:
        return Response({"success": False, "message": "Address data missing"}, status=400)

    try:
        address_dict = json.loads(address_raw)
    except (json.JSONDecodeError, TypeError):
        return Response({"success": False, "message": "Invalid address format"}, status=400)

    clean_data = {
        "email": request.data.get("email"),
        "address": address_dict,
        "id_type": request.data.get("id_type"),
        "front_file": request.FILES.get("front_file"),
        "back_file": request.FILES.get("back_file"),
    }

    serializer = SPAddressDocumentWriteSerializer(data=clean_data)

    if not serializer.is_valid():
        print("SERIALIZER ERRORS:", serializer.errors)
        return Response(
            {"success": False, "errors": serializer.errors},
            status=400
        )

    try:
        with transaction.atomic():
            service_provider = serializer.save()

            # Move onboarding to next step
            sp_profile = service_provider.sp_profile
            sp_profile.is_profile_completed = "in-services"
            sp_profile.save(update_fields=["is_profile_completed"])

        return Response({
            "success": True,
            "message": "Registration completed successfully.",
            "provider_id": service_provider.sp_profile_id,
            "profile_status": sp_profile.is_profile_completed
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response(
            {"success": False, "error": str(e)},
            status=400
        )




@api_view(['POST'])
@throttle_classes([RegisterThrottle])
def sp_register(request):

    serializer = SPProfileWriteSerializer(data=request.data)

    if not serializer.is_valid():
        return Response(
            {
                "success": False,
                "message": "Validation failed",
                "errors": serializer.errors
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        with transaction.atomic():

            sp_profile = serializer.save(
                is_profile_completed="in-details"
            )

            tokens = generate_sp_tokens(sp_profile)

        return Response(
            {
                "success": True,
                "message": "Service Provider registered successfully.",
                "data": {
                    "id": sp_profile.id,
                    "email": sp_profile.email_address,
                    "mobile": sp_profile.mobile_number,
                    "profile_status": sp_profile.is_profile_completed,
                    "access_token": tokens["access"],
                    "refresh_token": tokens["refresh"],
                }
            },
            status=status.HTTP_201_CREATED
        )

    except IntegrityError:

        return Response(
            {
                "success": False,
                "message": "An account with this email or mobile already exists."
            },
            status=status.HTTP_409_CONFLICT
        )

    except Exception as e:

        logger.error(f"Registration Error: {str(e)}")

        return Response(
            {
                "success": False,
                "message": "A server error occurred. Please try again later."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
@api_view(['POST'])
@throttle_classes([RegisterThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def register_device_token(request):
    serializer = DeviceTokenWriteSerializer(
        data=request.data,
        context={'request': request},
    )

    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    token = serializer.validated_data["fcm_token"]

    # Remove duplicate tokens across all providers
    DeviceToken.objects.filter(fcm_token=token).delete()

    device_token = serializer.save()

    return Response(
        {
            "message": "Device token registered successfully",
            "token_id": device_token.id,
        },
        status=status.HTTP_201_CREATED,
    )

@api_view(["PATCH"])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def patch_sp_profile(request):

    try:
        service_provider = ServiceProvider.objects.select_related(
            'sp_profile'
        ).get(sp_profile=request.user)

    except ServiceProvider.DoesNotExist:
        return Response({
            "success": False,
            "message": "Service Provider profile not found."
        }, status=status.HTTP_404_NOT_FOUND)

    serializer = ServiceProviderPatchSerializer(
        service_provider,
        data=request.data,
        partial=True,
        context={'request': request}
    )

    if serializer.is_valid():
        serializer.save()

        sp_profile = service_provider.sp_profile
        sp_profile.is_profile_completed = "in-address"
        sp_profile.save(update_fields=["is_profile_completed"])

        return Response({
            "success": True,
            "message": "Profile updated successfully.",
            "data": {
                **serializer.data,
                "profile_status": sp_profile.is_profile_completed,
            }
        }, status=status.HTTP_200_OK)

    return Response({
        "success": False,
        "message": "Please fix the errors below.",
        "errors": serializer.errors
    }, status=status.HTTP_400_BAD_REQUEST)



@api_view(["GET"])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def approved_services_list(request):
    """
    Return only APPROVED services.
    """
    services = Service.objects.filter(
        review_status="APPROVED"
    ).select_related("service_group")

    serializer = ServiceReadSerializer(services, many=True)

    return Response(serializer.data, status=status.HTTP_200_OK)




@api_view(['POST'])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def submit_service(request, provider_id):

    service_name = request.data.get("service_name")
    description = request.data.get("description", "")
    service_group_id = request.data.get("service_group")

    if not service_name:
        return Response(
            {"error": "service_name is required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Get Provider
    try:
        provider = ServiceProvider.objects.select_related('sp_profile').get(
            sp_profile__id=provider_id
        )
    except ServiceProvider.DoesNotExist:
        return Response(
            {"error": "No provider found with this email."},
            status=status.HTTP_404_NOT_FOUND
        )

    # Validate Service Submission
    validation = validate_service_submission(service_name, description)

    if validation["status"] == "rejected":
        return Response({
            "status": "rejected",
            "reason": validation.get("reason", "Service violates policy")
        }, status=status.HTTP_400_BAD_REQUEST)

    try:
        with transaction.atomic():

            # If Service Already Exists
            if validation["status"] == "exists":

                service = validation["service"]

                if ProviderService.objects.filter(
                    provider=provider,
                    service=service
                ).exists():
                    return Response(
                        {"error": "Service already linked to this provider."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                provider_service = ProviderService.objects.create(
                    provider=provider,
                    service=service
                )

                provider.sp_profile.is_profile_completed = "in-cost"
                provider.sp_profile.save(update_fields=["is_profile_completed"])

                return Response({
                    "status": "linked_existing",
                    "is_primary": provider_service.is_primary,
                    "service": ServiceReadSerializer(service).data,
                    "profile_status": provider.sp_profile.is_profile_completed
                }, status=status.HTTP_200_OK)

            # New Service Creation Requires Group
            if not service_group_id:
                return Response(
                    {"error": "service_group is required for new service."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                service_group = ServiceGroup.objects.select_related(
                    'category'
                ).get(group_id=service_group_id)
            except ServiceGroup.DoesNotExist:
                return Response(
                    {"error": "Invalid service_group provided."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            review_status = (
                "PENDING"
                if validation["status"] == "requires_review"
                else "APPROVED"
            )

            # Create Service
            service = Service.objects.create(
                service_name=service_name.strip().title(),
                description=description,
                service_group=service_group,
                review_status=review_status,
                risk_level=service_group.category.risk_level
            )

            # Link Provider to Service
            provider_service = ProviderService.objects.create(
                provider=provider,
                service=service
            )

            provider.sp_profile.is_profile_completed = "in-cost"
            provider.sp_profile.save(update_fields=["is_profile_completed"])

            return Response({
                "status": validation["status"],
                "is_primary": provider_service.is_primary,
                "service": ServiceReadSerializer(service).data,
                "profile_status": provider.sp_profile.is_profile_completed
            }, status=status.HTTP_201_CREATED)

    except ValidationError as e:
        return Response(
            {"error": e.message_dict if hasattr(e, "message_dict") else str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )

    except IntegrityError:
        return Response(
            {"error": "Database integrity error."},
            status=status.HTTP_400_BAD_REQUEST
        )
    
@api_view(['PATCH'])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def update_cost_of_service(request, service_id):
    try:
        provider = ServiceProvider.objects.select_related(
            'sp_profile'
        ).get(sp_profile=request.user)
    except ServiceProvider.DoesNotExist:
        return Response({"error": "Provider not found"}, status=404)

    try:
        service = Service.objects.get(service_id=service_id)
    except Service.DoesNotExist:
        return Response({"error": "Service not found"}, status=404)

    provider_service, created = ProviderService.objects.get_or_create(
        provider=provider,
        service=service
    )

    data = request.data
    base_price = data.get("base_price")
    negotiable = data.get("negotiable", True)
    notes = data.get("notes", "")

    try:
        if provider_service.cost_of_service is None:
            cost = CostOfService.objects.create(
                base_price=base_price,
                negotiable=negotiable,
                notes=notes
            )
            provider_service.cost_of_service = cost
            provider_service.save()
        else:
            cost = provider_service.cost_of_service
            cost.base_price = base_price
            cost.negotiable = negotiable
            cost.notes = notes
            cost.save()

        provider.sp_profile.is_profile_completed = "completed"
        provider.sp_profile.save(update_fields=["is_profile_completed"])

        return Response({
            "success": True,
            "cost_of_service": {
                "id": cost.id,
                "base_price": str(cost.base_price) if cost.base_price is not None else None,
                "negotiable": cost.negotiable,
                "notes": cost.notes,
            },
            "profile_status": provider.sp_profile.is_profile_completed
        }, status=200)

    except Exception as e:
        return Response({"error": f"Internal error: {str(e)}"}, status=500)
        

@api_view(['GET', 'POST'])
@throttle_classes([UserReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def sp_profile_list(request):
    
    if request.method == 'POST':
        serializer = SPProfileReadSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@throttle_classes([UserReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def sp_profile_detail(request):
    try:
        profile = request.user
    except SPProfile.DoesNotExist:
        return Response({'error': 'Profile not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = SPProfileReadSerializer(profile)
        return Response(serializer.data)

    elif request.method in ['PUT', 'PATCH']:
        serializer = SPProfileReadSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    elif request.method == 'DELETE':
        profile.delete()
        return Response(status=204)
    
@api_view(['PATCH'])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def toggle_provider_active(request):
    try:
        provider = ServiceProvider.objects.get(
    sp_profile=request.user
)
    except ServiceProvider.DoesNotExist:
        return Response(
            {
                "success": False,
                "message": "Service provider not found",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    provider.is_active = not provider.is_active
    provider.save(update_fields=['is_active'])

    return Response(
        {
            "success": True,
            "message": "Provider active status updated",
            "is_active": provider.is_active,
            
        },
        status=status.HTTP_200_OK,
    )

@api_view(['GET'])
@throttle_classes([UserReadThrottle])
def get_provider_services(request, provider_id):
    try:
        provider = get_object_or_404(
    ServiceProvider,
    sp_profile__id=provider_id,
    is_active=True
)
    except ServiceProvider.DoesNotExist:
        return Response(
            {
                "success": False,
                "message": "Provider not found."
            },
            status=status.HTTP_404_NOT_FOUND
        )

    provider_services = ProviderService.objects.select_related(
        'service',
        'provider',
        'cost_of_service',
        'provider__sp_profile'
    ).filter(provider=provider)

    serializer = ProviderSeviceSerializer(provider_services, many=True)

    return Response(
        {
            "success": True,
            "count": provider_services.count(),
            "data": serializer.data
        },
        status=status.HTTP_200_OK
    )

@api_view(['POST'])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def upload_service_images(request, cost_id):

    try:
        provider = ServiceProvider.objects.select_related(
            'sp_profile'
        ).get(
            sp_profile=request.user
        )
    except ServiceProvider.DoesNotExist:
        return Response(
            {
                "success": False,
                "message": "Provider not found."
            },
            status=status.HTTP_404_NOT_FOUND
        )

    try:
        cost = CostOfService.objects.get(
            id=cost_id,
            provider_service__provider=provider
        )
    except CostOfService.DoesNotExist:
        return Response(
            {
                "success": False,
                "message": "Cost of service not found or you do not have permission to modify it."
            },
            status=status.HTTP_404_NOT_FOUND
        )

    images = request.FILES.getlist("images")

    if not images:
        return Response(
            {
                "success": False,
                "message": "No images provided."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    current_count = cost.images.count()

    if current_count + len(images) > 5:
        return Response(
            {
                "success": False,
                "message": f"Maximum 5 images allowed. Currently stored: {current_count}."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    created_images = []

    for image_file in images:
        image = CostOfServiceImage.objects.create(
            cost_of_service=cost,
            image=image_file
        )
        created_images.append(image)

    serializer = CostOfServiceImageReadSerializer(
        created_images,
        many=True,
        context={"request": request}
    )

    return Response(
        {
            "success": True,
            "message": "Images uploaded successfully.",
            "count": len(created_images),
            "images": serializer.data,
        },
        status=status.HTTP_201_CREATED
    )

# -------- ServiceGroup --------

@api_view(['GET', 'POST'])
@throttle_classes([UserReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def service_group_list(request):
    if request.method == 'GET':
        groups = ServiceGroup.objects.all()
        serializer = ServiceGroupSerializer(groups, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        serializer = ServiceGroupSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@throttle_classes([UserReadThrottle])
def service_group_detail(request, group_id):
    try:
        group = ServiceGroup.objects.get(group_id=group_id)
    except ServiceGroup.DoesNotExist:
        return Response({'error': 'Service Group not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = ServiceGroupSerializer(group)
        return Response(serializer.data)

    elif request.method in ['PUT', 'PATCH']:
        partial = request.method == 'PATCH'
        serializer = ServiceGroupSerializer(group, data=request.data, partial=partial)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        group.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# -------- Service --------

@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def service_list(request):
    services = Service.objects.filter(
        review_status="APPROVED"
    ).annotate(
        active_provider_count=Count(
            'service_providers__provider',
            filter=Q(service_providers__provider__is_active=True),
            distinct=True
        )
    )

    serializer = ServiceSerializer(services, many=True)
    return Response(serializer.data)

  


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@throttle_classes([UserReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def service_detail(request, pk):
    try:
        service = Service.objects.get(pk=pk)
    except Service.DoesNotExist:
        return Response({'error': 'Service not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = ServiceSerializer(service)
        return Response(serializer.data)

    elif request.method in ['PUT', 'PATCH']:
        partial = request.method == 'PATCH'
        serializer = ServiceSerializer(service, data=request.data, partial=partial)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        service.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# -------- ServiceProvider --------

@api_view(['GET', 'POST'])
@throttle_classes([UserReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def service_provider_list(request):
    if request.method == 'GET':
        providers = ServiceProvider.objects.all()
        serializer = ServiceProviderReadSerializer(providers, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        serializer = ServiceProviderWriteSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
@api_view(['GET', 'POST'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def service_provider_list_service(request):
    if request.method == 'GET':
        service_id = request.query_params.get('service_id', None)
        if service_id is not None:
            # Only active providers for the given service
            providers = ServiceProvider.objects.filter(
                provider_services__service_id=service_id,
                is_active=True
            ).distinct()
        else:
            # All active providers
            providers = ServiceProvider.objects.filter(is_active=True)

        serializer = ServiceProviderReadSerializer(providers, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        serializer = ServiceProviderWriteSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    
MAX_RETRIES = 5
RETRY_DELAY = 0.1  

@api_view(['POST'])
@throttle_classes([LiveLocationWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def update_sp_live_location(request):
    
    latitude = request.data.get("latitude")
    longitude = request.data.get("longitude")

    if not latitude or not longitude:
        return Response(
            {"error": "latitude and longitude are required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        provider = get_service_provider(request)
    except ServiceProvider.DoesNotExist:
        return Response(
            {"error": "Service provider not found for this email"},
            status=status.HTTP_404_NOT_FOUND
        )

    lat = Decimal(str(latitude))
    lon = Decimal(str(longitude))

    for attempt in range(MAX_RETRIES):
        try:
            with transaction.atomic():
                # Try to get the live location row
                live_location = SPLiveLocation.objects.select_for_update(nowait=True).filter(provider=provider).first()

                # Skip if location unchanged
                if live_location and live_location.latitude == lat and live_location.longitude == lon:
                    return Response(
                        {
                            "message": "Location unchanged. No update needed.",
                            "data": {
                                "provider_id": provider.id,
                                "latitude": str(live_location.latitude),
                                "longitude": str(live_location.longitude),
                                "updated_at": live_location.updated_at,
                            }
                        },
                        status=status.HTTP_200_OK
                    )

                # Update existing or create new
                if live_location:
                    live_location.latitude = lat
                    live_location.longitude = lon
                    live_location.save()
                    created = False
                else:
                    live_location = SPLiveLocation.objects.create(
                        provider=provider,
                        latitude=lat,
                        longitude=lon
                    )
                    created = True

                # Save history asynchronously (can use Celery in production)
                SPLocationHistory.objects.create(
                    provider=provider,
                    latitude=lat,
                    longitude=lon,
                )

            # Success: break retry loop
            break

        except OperationalError as e:
            if "database is locked" in str(e):
                time.sleep(RETRY_DELAY)  # wait and retry
                continue
            else:
                raise

    else:  # if retries exhausted
        return Response(
            {"error": "Database is busy. Please try again."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )

    return Response(
        {
            "message": "Live location updated successfully",
            "created": created,
            "data": {
                "provider_email": provider.sp_profile.email_address,
                "latitude": str(live_location.latitude),
                "longitude": str(live_location.longitude),
                "updated_at": live_location.updated_at,
            }
        },
        status=status.HTTP_200_OK
    )




@api_view(['GET'])
@authentication_classes([ClientJWTAuthentication])


@permission_classes([IsAuthenticated])
def service_provider_detail(request, id):
    try:
        provider = ServiceProvider.objects.get(sp_profile__id=id)
    except ServiceProvider.DoesNotExist:
        return Response(
            {'error': 'Service Provider not found.'},
            status=status.HTTP_404_NOT_FOUND
        )

    if request.method == 'GET':
        serializer = ServiceProviderReadSerializer(provider)
        return Response(serializer.data)
    

@api_view(['GET', 'PUT', 'PATCH'])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def service_provider_details(request, id):
    try:
        provider = ServiceProvider.objects.get(sp_profile__id=id)
    except ServiceProvider.DoesNotExist:
        return Response(
            {'error': 'Service Provider not found.'},
            status=status.HTTP_404_NOT_FOUND
        )

    if request.method == 'GET':
        serializer = ServiceProviderReadSerializer(provider)
        return Response(serializer.data)


    
# -------- ServiceProvider Address --------
@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def service_provider_address_detail(request, id):

    provider = get_service_provider(request)

    try:
        address = Address.objects.get(
            id=id,
            serviceprovider=provider
        )

    except Address.DoesNotExist:
        return Response(
            {
                "success": False,
                "message": "Address not found."
            },
            status=status.HTTP_404_NOT_FOUND
        )

    if request.method == 'GET':
        serializer = SPAddressSerializer(address)
        return Response(serializer.data)

    elif request.method in ['PUT', 'PATCH']:

        serializer = SPAddressSerializer(
            address,
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

    elif request.method == 'DELETE':

        if provider.location_id == address.id:
            provider.location = None
            provider.save(update_fields=["location"])

        address.delete()

        return Response(
            status=status.HTTP_204_NO_CONTENT
        )

@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def service_provider_address(request,):
    try:
        provider = get_service_provider(request)

        addresses = Address.objects.filter(
        serviceprovider=provider
        )
    except Address.DoesNotExist:
        return Response({'error': 'Address not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = SPAddressSerializer(addresses , many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method in ['PUT', 'PATCH']:
        serializer = SPAddressSerializer(addresses, data=request.data, partial=(request.method == 'PATCH'))
        if serializer.is_valid():
            serializer.save()
            return Response({'message': 'Address updated successfully.', 'data': serializer.data}, status=status.HTTP_200_OK)
        return Response({'error': 'Invalid data provided.', 'details': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        addresses.delete()
        return Response({'message': 'Address deleted successfully.'}, status=status.HTTP_204_NO_CONTENT)
    
@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def providers_by_service(request, service_id):
    providers = ServiceProvider.objects.filter(services__service_id=service_id)
    serializer = ServiceProviderReadSerializer(providers, many=True)
    return Response(serializer.data)

@api_view(['GET'])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([UserReadThrottle])
def get_cost_of_service_images_by_cost_id(request, cost_id):
    try:
        CostOfService.objects.get(id=cost_id)
    except CostOfService.DoesNotExist:
        return Response(
            {"detail": "Cost of service not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    images = CostOfServiceImage.objects.filter(
        cost_of_service_id=cost_id
    ).order_by('-uploaded_at')

    serializer = CostOfServiceImageReadSerializer(
        images,
        many=True,
        context={'request': request}
    )
    return Response(serializer.data, status=status.HTTP_200_OK)

@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def costs_by_sp(request, provider_id, service_id=None):
    try:
        
        sp = ServiceProvider.objects.get(sp_profile__id=provider_id, is_active=True)
    except ServiceProvider.DoesNotExist:
        return Response(
            {"detail": "Service provider not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    provider_services = ProviderService.objects.select_related(
        'service',
        'cost_of_service'
    ).filter(
        provider=sp,
        cost_of_service__isnull=False
    )

    if service_id is not None:
        try:
            provider_service = provider_services.get(service_id=service_id)
        except ProviderService.DoesNotExist:
            return Response(
                {"detail": "Cost of service not found for this provider and service."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = CostOfServiceSerializer(provider_service.cost_of_service)
        return Response(serializer.data, status=status.HTTP_200_OK)

    costs = [ps.cost_of_service for ps in provider_services]
    serializer = CostOfServiceSerializer(costs, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)



@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def fetch_sp_addresses_by_service(request, service_id):

    # Get all providers for the service
    providers = ServiceProvider.objects.filter(services__service_id=service_id,is_active=True)

    # Get their addresses (exclude null locations)
    addresses = Address.objects.filter(serviceprovider__in=providers, latitude__isnull=False, longitude__isnull=False).distinct()

    # Serialize addresses
    data = [ SPAddressSerializer(addr).data
             for addr in addresses
    ]

    return Response(data)

@api_view(['GET'])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([LiveLocationReadThrottle])
def fetch_sp_live_locations_by_service(request, service_id):
    """
    Fetch up to 10 active service providers for a service
    along with their latest live location.
    """

    # Subquery for latest location per provider
    latest_location_subquery = SPLiveLocation.objects.filter(
        provider=OuterRef('pk')
    ).order_by('-updated_at').values('id')[:1]

    # Step 1: Limit providers FIRST
    providers = (
        ServiceProvider.objects.filter(
            provider_services__service__service_id=service_id,
            is_active=True
        )
        .distinct()
        .annotate(latest_location_id=Subquery(latest_location_subquery))
        [:10]  # ✅ LIMIT HERE
    )

    # Step 2: Get those latest locations
    latest_location_ids = providers.values_list('latest_location_id', flat=True)

    latest_locations = (
        SPLiveLocation.objects.filter(id__in=latest_location_ids)
        .select_related('provider')
    )

    serializer = SPLiveLocationSerializer(latest_locations, many=True)
    return Response(serializer.data)


@api_view(['GET'])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([LiveLocationReadThrottle])
def sps_by_live_location(request):
    """
    GET: Fetch all active service providers linked to multiple live location IDs.
    Example: /api/service_providersDB/sp-by-live-locations/?ids=1,2,3
    """
    ids = request.GET.get('ids')
    if not ids:
        return Response(
            {'error': 'Please provide live location IDs.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    id_list = [int(i) for i in ids.split(',') if i.isdigit()]

    live_locations = SPLiveLocation.objects.filter(
        id__in=id_list
    ).select_related('provider')

    sps = ServiceProvider.objects.filter(
        sp_profile__in=[loc.provider.sp_profile for loc in live_locations],
        is_active=True
    ).select_related(
        'sp_profile',
        'location'
    ).prefetch_related(
        'provider_services__service'   # ✅ FIXED
    ).distinct()

    if not sps.exists():
        return Response(
            {'error': 'No active service providers found for the given live location IDs.'},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = ServiceProviderReadSerializer(
        sps,
        many=True,
        context={'request': request}
    )

    return Response(
        {'service_providers': serializer.data},
        status=status.HTTP_200_OK
    )

@api_view(['GET'])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([LiveLocationReadThrottle])
def client_get_sps_by_live_location(request):
    """
    GET: Fetch all active service providers linked to multiple live location IDs.
    Example: /api/service_providersDB/sp-by-live-locations/?ids=1,2,3
    """
    ids = request.GET.get('ids')
    if not ids:
        return Response(
            {'error': 'Please provide live location IDs.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    id_list = [int(i) for i in ids.split(',') if i.isdigit()]

    live_locations = SPLiveLocation.objects.filter(
        id__in=id_list
    ).select_related('provider')

    sps = ServiceProvider.objects.filter(
        sp_profile__in=[loc.provider.sp_profile for loc in live_locations],
        is_active=True
    ).select_related(
        'sp_profile',
        'location'
    ).prefetch_related(
        'provider_services__service'   # ✅ FIXED
    ).distinct()

    if not sps.exists():
        return Response(
            {'error': 'No active service providers found for the given live location IDs.'},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = ServiceProviderReadSerializer(
        sps,
        many=True,
        context={'request': request}
    )

    return Response(
        {'service_providers': serializer.data},
        status=status.HTTP_200_OK
    )