from decimal import Decimal
import time
from django.db import transaction, OperationalError
from django.utils import timezone
from math import asin, cos, radians, sin, sqrt
from django.shortcuts import get_object_or_404, render
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import CostOfService, SPLiveLocation, SPLocationHistory, SPProfile, ServiceGroup, Service, ServiceProvider, Address
from .serializers import (
    CostOfServiceSerializer,
    SPLiveLocationSerializer,
    SPProfileSerializer,
    ServiceGroupSerializer,
    ServiceProviderReadSerializer,
    ServiceProviderWriteSerializer,
    ServiceSerializer,
    SPAddressSerializer
)

# 
# -------- SPProfile --------

@api_view(['GET', 'POST'])
def sp_profile_list(request):
    if request.method == 'GET':
        profiles = SPProfile.objects.all()
        serializer = SPProfileSerializer(profiles, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        serializer = SPProfileSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
def sp_profile_detail(request, email):
    try:
        profile = SPProfile.objects.get(email_address=email)
    except SPProfile.DoesNotExist:
        return Response({'error': 'Profile not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = SPProfileSerializer(profile)
        return Response(serializer.data)

    elif request.method in ['PUT', 'PATCH']:
        serializer = SPProfileSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    elif request.method == 'DELETE':
        profile.delete()
        return Response(status=204)



# -------- ServiceGroup --------

@api_view(['GET', 'POST'])
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

@api_view(['GET', 'POST'])
def service_list(request):
    if request.method == 'GET':
        services = Service.objects.all()
        serializer = ServiceSerializer(services, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        serializer = ServiceSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
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
def service_provider_list_service(request):
    if request.method == 'GET':
        service_id = request.query_params.get('service_id', None)
        if service_id is not None:
            # Only active providers for the given service
            providers = ServiceProvider.objects.filter(
                services__service_id=service_id,
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
def update_sp_live_location(request):
    email = request.data.get("email")
    latitude = request.data.get("latitude")
    longitude = request.data.get("longitude")

    if not email or not latitude or not longitude:
        return Response(
            {"error": "email, latitude and longitude are required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        provider = ServiceProvider.objects.select_related("sp_profile").get(
            sp_profile__email_address=email
        )
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
                                "provider_email": provider.sp_profile.email_address,
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




@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
def service_provider_detail(request, email):
    try:
        provider = ServiceProvider.objects.get(sp_profile__email_address=email)
    except ServiceProvider.DoesNotExist:
        return Response({'error': 'Service Provider not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = ServiceProviderReadSerializer(provider)
        return Response(serializer.data)

    elif request.method in ['PUT', 'PATCH']:
        partial = request.method == 'PATCH'
        serializer = ServiceProviderWriteSerializer(provider, data=request.data, partial=partial)
        if serializer.is_valid():
            serializer.save()
            return Response(ServiceProviderReadSerializer(provider).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        provider.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    
# -------- ServiceProvider Address --------
@api_view(['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
def service_provider_address_detail(request, id):
    try:
        address = Address.objects.get(id=id)
    except Address.DoesNotExist:
        return Response({'error': 'Address not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = SPAddressSerializer(address)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method in ['PUT', 'PATCH']:
        serializer = SPAddressSerializer(address, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        address.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    return Response({'error': 'Method not allowed'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
def service_provider_address(request,):
    try:
        address = Address.objects.all()
    except Address.DoesNotExist:
        return Response({'error': 'Address not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = SPAddressSerializer(address, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method in ['PUT', 'PATCH']:
        serializer = SPAddressSerializer(address, data=request.data, partial=(request.method == 'PATCH'))
        if serializer.is_valid():
            serializer.save()
            return Response({'message': 'Address updated successfully.', 'data': serializer.data}, status=status.HTTP_200_OK)
        return Response({'error': 'Invalid data provided.', 'details': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        address.delete()
        return Response({'message': 'Address deleted successfully.'}, status=status.HTTP_204_NO_CONTENT)
    
@api_view(['GET'])
def providers_by_service(request, service_id):
    providers = ServiceProvider.objects.filter(services__service_id=service_id)
    serializer = ServiceProviderReadSerializer(providers, many=True)
    return Response(serializer.data)

@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
# @permission_classes([IsAuthenticated])
# @permission_classes([IsAuthenticated])
def costs_by_sp_email(request, email):
    try:
        sp = ServiceProvider.objects.get(sp_profile__email_address=email)
    except ServiceProvider.DoesNotExist:
        return Response({"detail": "Service provider not found."}, status=status.HTTP_404_NOT_FOUND)

    costs = CostOfService.objects.filter(provider=sp)
    serializer = CostOfServiceSerializer(costs, many=True)
    return Response(serializer.data)



@api_view(['GET'])
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
def fetch_sp_live_locations_by_service(request, service_id):
    """
    Fetch all active service providers for a service along with their latest live location.
    """
    # Get all active providers for the service
    providers = ServiceProvider.objects.filter(
        services__service_id=service_id,
        is_active=True
    )

    # Get their latest live locations
    live_locations = SPLiveLocation.objects.filter(
        provider__in=providers
    ).order_by('provider', '-updated_at')  # latest first

    # Only take the latest location per provider
    latest_locations = {}
    for loc in live_locations:
        if loc.provider_id not in latest_locations:
            latest_locations[loc.provider_id] = loc

    data = [SPLiveLocationSerializer(loc).data for loc in latest_locations.values()]

    return Response(data)


@api_view(['GET'])
def sps_by_address(request, address_id):
    """
    GET: Fetch all service providers linked to a specific address ID.
    """
    try:
        address = Address.objects.get(id=address_id)
    except Address.DoesNotExist:
        return Response({'error': 'Address not found.'}, status=status.HTTP_404_NOT_FOUND)

    # Fetch all service providers linked to this address
    sps = ServiceProvider.objects.filter(location=address).select_related("sp_profile", "location").prefetch_related("services")

    if not sps.exists():
        return Response({'error': 'No service providers found for this address.'}, status=status.HTTP_404_NOT_FOUND)

    serializer = ServiceProviderReadSerializer(sps, many=True, context={'request': request})
    return Response({'service_providers': serializer.data}, status=status.HTTP_200_OK)



@api_view(['GET'])
def sps_by_addresses(request):
    """
    GET: Fetch all active service providers linked to multiple address IDs.
    Example: /api/clientsDB/sp-by-addresses/?ids=1,2,3
    """
    ids = request.GET.get('ids')
    if not ids:
        return Response({'error': 'Please provide address IDs.'}, status=status.HTTP_400_BAD_REQUEST)

    id_list = [int(i) for i in ids.split(',') if i.isdigit()]

    sps = (
        ServiceProvider.objects
        .filter(location__id__in=id_list, is_active=True)  # ✅ Only active
        .select_related("sp_profile", "location")
        .prefetch_related("services")
    )

    if not sps.exists():
        return Response({'error': 'No active service providers found for the given addresses.'}, status=status.HTTP_404_NOT_FOUND)

    serializer = ServiceProviderReadSerializer(sps, many=True, context={'request': request})
    return Response({'service_providers': serializer.data}, status=status.HTTP_200_OK)





@api_view(['GET'])
def sps_by_live_location(request):
    """
    GET: Fetch all active service providers linked to multiple live location IDs.
    Example: /api/service_providersDB/sp-by-live-locations/?ids=1,2,3
    """
    ids = request.GET.get('ids')
    if not ids:
        return Response({'error': 'Please provide live location IDs.'}, status=status.HTTP_400_BAD_REQUEST)

    # Parse IDs safely
    id_list = [int(i) for i in ids.split(',') if i.isdigit()]

    # Get all live locations that match the IDs
    live_locations = SPLiveLocation.objects.filter(id__in=id_list).select_related('provider')

    # Fetch the associated active service providers
    sps = ServiceProvider.objects.filter(
        sp_profile__in=[loc.provider.sp_profile for loc in live_locations],
        is_active=True
    ).select_related('sp_profile', 'location').prefetch_related('services')

    if not sps.exists():
        return Response({'error': 'No active service providers found for the given live location IDs.'}, status=status.HTTP_404_NOT_FOUND)

    serializer = ServiceProviderReadSerializer(sps, many=True, context={'request': request})
    return Response({'service_providers': serializer.data}, status=status.HTTP_200_OK)
