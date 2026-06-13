from sqlite3 import IntegrityError

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from psycopg import logger
from rest_framework.decorators import api_view, authentication_classes, parser_classes, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from api.clientsDB.services.jwt_client_authentication import ClientJWTAuthentication
from plug_backend.helpers.auth_helpers import get_client_details
from plug_backend.throttles import ProfileWriteThrottle, UserReadThrottle
from plug_backend.utils.client_jwt_helper import generate_client_tokens


# from rest_framework.permissions import IsAuthenticated
from .models.models import ClientAuth, ClientDetails, Address, ClientAddress, ClientNotification, DeviceToken 
from .serializers import AddressClaimSerializer, AddressOnlySerializer, AddressVerificationCreateSerializer, ClientAddressNoDuplicatesSerializer, AddressSerializer, ClientAddressWriteSerializer, ClientAuthReadSerializer, ClientLoginSerializer, ClientProfileSerializer, ClientRegisterSerializer, ClientSerializer, ClientAddressSerializer, DefaultAddressSerializer, DeviceTokenWriteSerializer

@api_view(['POST'])
@throttle_classes([ProfileWriteThrottle])
def register_client(request):

    serializer = ClientRegisterSerializer(data=request.data)

    if serializer.is_valid():

        email = serializer.validated_data['email_address'].lower()

        # Prevent duplicate accounts
        if ClientAuth.objects.filter(email_address=email).exists():
            return Response(
                {"error": "A user with this email already exists."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if ClientAuth.objects.filter(
            mobile_number=serializer.validated_data["mobile_number"]
                ).exists():
            return Response(
                {"error": "A user with this mobile number already exists."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():

                
                client_auth = serializer.save()

                # Ensure profile exists
                ClientDetails.objects.get_or_create(
                    client_profile=client_auth
                )

                
                tokens = generate_client_tokens(client_auth)

            return Response(
                {
                    "success": True,
                    "message": "Registration successful.",
                    "data": {
                        "id": client_auth.id,
                        "email": client_auth.email_address,
                        "mobile_number": client_auth.mobile_number,
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
                    "message": "A user with this email or mobile already exists."
                },
                status=status.HTTP_409_CONFLICT
            )

        except Exception as e:
            logger.error(f"Client Registration Error: {str(e)}")
            return Response(
                {
                    "success": False,
                    "message": "A server error occurred. Please try again later."
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([UserReadThrottle])
def get_my_profile(request):

    try:
        client = ClientDetails.objects.select_related(
            'client_profile'
        ).get(
            client_profile=request.user
        )
    except ClientDetails.DoesNotExist:
        return Response(
            {"error": "Client not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = ClientSerializer(
        client,
        context={'request': request}
    )

    return Response(serializer.data)

@api_view(['PATCH'])
@throttle_classes([ProfileWriteThrottle])
@parser_classes([MultiPartParser, FormParser])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def complete_profile(request):
    print("FILES RECEIVED:", request.FILES)
    print("POST DATA:", request.data) 
    try:
        client = get_client_details(request)

    except ClientDetails.DoesNotExist:
        return Response(
            {"error": "Client not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = ClientSerializer(
        client,
        data=request.data,
        partial=True,
        context={'request': request}
    )

    if serializer.is_valid():

        updated_client = serializer.save()

        if (
            updated_client.first_name and
            updated_client.last_name and
            updated_client.date_of_birth
        ):
            updated_client.client_profile.is_profile_completed = "in-address"
            updated_client.client_profile.save(
                update_fields=["is_profile_completed"]
            )

        return Response({
            "success": True,
            "data": serializer.data,
            "profile_status": updated_client.client_profile.is_profile_completed,
        })

    return Response(
        serializer.errors,
        status=status.HTTP_400_BAD_REQUEST
    )

@api_view(['PATCH'])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([ProfileWriteThrottle])
def set_default_address(request, address_id):

    try:
        client = get_client_details(request)

    except ClientDetails.DoesNotExist:
        return Response(
            {"detail": "Client not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    try:
        client_address = ClientAddress.objects.get(
            pk=address_id,
            client=client
        )

    except ClientAddress.DoesNotExist:
        return Response(
            {"detail": "Address not found for this client."},
            status=status.HTTP_404_NOT_FOUND
        )

    client_address.is_default = True
    client_address.save()

    return Response(
        {
            "success": True,
            "detail": f"Address {client_address.address} is now default."
        },
        status=status.HTTP_200_OK
    )


@api_view(['POST'])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def add_residential_address(request):

    try:
        client = get_client_details(request)

    except ClientDetails.DoesNotExist:
        return Response(
            {"error": "Client not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = ClientAddressWriteSerializer(
        data=request.data,
        context={"client": client}
    )

    if not serializer.is_valid():
        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    client_address = serializer.save()

    client.client_profile.is_profile_completed = "completed"
    client.client_profile.save(
        update_fields=["is_profile_completed"]
    )

    return Response(
        {
            "success": True,
            "message": "Address added successfully.",
            "data": ClientAddressSerializer(client_address).data,
            "profile_status": client.client_profile.is_profile_completed,
        },
        status=status.HTTP_201_CREATED
    )

@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_my_auth(request):

    serializer = ClientAuthReadSerializer(
        request.user,
        context={"request": request}
    )

    return Response(
        serializer.data,
        status=status.HTTP_200_OK
    )

@api_view(["POST"])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([ProfileWriteThrottle])
def submit_address_verification(request, client_address_id):

    try:
        client = get_client_details(request)

        client_address = ClientAddress.objects.get(
            id=client_address_id,
            client=client
        )

    except ClientAddress.DoesNotExist:
        return Response(
            {"error": "Client address not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = AddressVerificationCreateSerializer(
        data={
            "client_address": client_address.id,
            "proof_of_residence": request.FILES.get("proof_of_residence"),
            "id_document": request.FILES.get("id_document"),
        },
        context={"request": request}
    )

    if serializer.is_valid():
        verification = serializer.save()

        return Response(
            {
                "success": True,
                "message": "Verification submitted successfully.",
                "status": verification.status,
            },
            status=status.HTTP_201_CREATED
        )

    return Response(
        serializer.errors,
        status=status.HTTP_400_BAD_REQUEST
    )

@api_view(['POST'])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def register_device_token(request):
    print("FILES RECEIVED:", request.FILES)
    print("POST DATA:", request.data)   
    serializer = DeviceTokenWriteSerializer(data=request.data, context={'request': request})
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    token = serializer.validated_data["fcm_token"]

    
    DeviceToken.objects.filter(
    fcm_token=token
).exclude(
    client=request.user
).delete()

    device_token = serializer.save()

    return Response(
        {"message": "Device token registered successfully", "token_id": device_token.id},
        status=status.HTTP_201_CREATED
    )

@api_view(['POST'])
@throttle_classes([ProfileWriteThrottle])


def client_login(request):

    serializer = ClientLoginSerializer(data=request.data)

    if serializer.is_valid():

        user = serializer.validated_data["user"]

        client_details = getattr(user, "clientdetails", None)

        tokens = generate_client_tokens(user)

        return Response({
            "success": True,
            "message": "Login successful",
            "data": {
                "id": user.id,
                "email": user.email_address,
                "mobile_number": user.mobile_number,
                "first_name": getattr(client_details, "first_name", ""),
                "last_name": getattr(client_details, "last_name", ""),
                "is_profile_completed": user.is_profile_completed,

                "access_token": tokens["access"],
                "refresh_token": tokens["refresh"],
            }
        }, status=status.HTTP_200_OK)

    return Response({
        "success": False,
        "errors": serializer.errors
    }, status=status.HTTP_400_BAD_REQUEST)



@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def address_list(request,format=None):

    if request.method == 'PUT':
        serializer = AddressSerializer(data=request.data)
        if serializer.is_valid():
            address = Address.objects.get(id=request.data.get('id'))
            serializer.update(address, request.data)
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)

    if request.method == 'DELETE':
        address_id = request.data.get('id')
        try:
            address = Address.objects.get(id=address_id)
            address.delete()
            return Response({'message': 'Address deleted successfully.'}, status=204)
        except Address.DoesNotExist:
            return Response({'error': 'Address not found.'}, status=404)

@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def client_address_list(request,format=None):
    if request.method == 'POST':
        serializer = ClientAddressSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({'message': 'Client Address created successfully.', 'data': serializer.data}, status=201)
        return Response({'error': 'Invalid data provided.', 'details': serializer.errors}, status=400)

        

@api_view(['GET', 'PUT', 'PATCH'])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([UserReadThrottle])
def clientProfile_detail(request, format=None):
    try:
        client_profile = get_client_details(request)
    except ClientAuth.DoesNotExist:
        return Response({'error': 'Client Profile not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = ClientProfileSerializer(client_profile)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method in ['PUT', 'PATCH']:
        data = request.data.copy()
        if 'email_address' in data and data['email_address'] != client_profile.email_address:
            return Response({'error': 'You cannot update the email address.'}, status=status.HTTP_400_BAD_REQUEST)

        partial = request.method == 'PATCH'
        serializer = ClientProfileSerializer(client_profile, data=data, partial=partial)
        if serializer.is_valid():
            serializer.save()
            return Response({'message': 'Client Profile updated successfully.', 'data': serializer.data}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', ])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def client_detail(request,format=None):
    try:
        client = get_client_details(request)
    except ClientDetails.DoesNotExist:
        return Response({'error': 'Client not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = ClientSerializer(client)
        return Response(serializer.data)

    elif request.method == 'PUT':
        serializer = ClientSerializer(client, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({'message': 'Client updated successfully.', 'client': serializer.data})
        return Response({'error': 'Invalid data provided.', 'details': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)



@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def address_detail(request, id,format=None):
    try:
        address = Address.objects.get(id=id)
    except Address.DoesNotExist:
        return Response({'error': 'Address not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = AddressSerializer(address)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method in ['PUT', 'PATCH']:
        serializer = AddressSerializer(address, data=request.data, partial=(request.method == 'PATCH'))
        if serializer.is_valid():
            serializer.save()
            return Response({'message': 'Address updated successfully.', 'data': serializer.data}, status=status.HTTP_200_OK)
        return Response({'error': 'Invalid data provided.', 'details': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        address.delete()
        return Response({'message': 'Address deleted successfully.'}, status=status.HTTP_204_NO_CONTENT)

@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def client_address_detail(request, client_id, format=None):
    try:
        # RLS-style enforcement: user can only access their own client record
        client = ClientDetails.objects.get(
            client_profile__id=client_id,
            client_profile=request.user
        )
    except ClientDetails.DoesNotExist:
        return Response(
            {'error': 'Client not found or access denied.'},
            status=status.HTTP_404_NOT_FOUND
        )

    client_addresses = (
        ClientAddress.objects
        .filter(client=client)
        .order_by('-is_default', 'id')
    )

    if not client_addresses.exists():
        return Response(
            {'error': 'Client Address not found.'},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = ClientAddressSerializer(client_addresses, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)

    
    

@api_view(['GET', 'PUT'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def client_profile_me(request):
    try:
        client = ClientDetails.objects.get(client_profile=request.user)
    except ClientDetails.DoesNotExist:
        return Response({'error': 'Client profile not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = ClientSerializer(client, context={'request': request})
        return Response(serializer.data)

    elif request.method == 'PUT':
        serializer = ClientSerializer(client, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def client_saved_addresses(request, client_id):
    try:
        # RLS-style enforcement: ensure user can only access their own client record
        client = ClientDetails.objects.get(
            id=client_id,
            client_profile=request.user  # enforce ownership via auth context
        )
    except ClientDetails.DoesNotExist:
        return Response(
            {'error': 'Client not found or access denied.'},
            status=status.HTTP_404_NOT_FOUND
        )

    client_addresses = (
        ClientAddress.objects
        .filter(client=client)
        .select_related('address')
    )

    # Attach relation metadata efficiently
    address_data = []
    for ca in client_addresses:
        addr = ca.address
        addr.clientaddress = ca  # keep your existing serializer dependency
        address_data.append(addr)

    serializer = AddressOnlySerializer(address_data, many=True)
    return Response(
        {'addresses': serializer.data},
        status=status.HTTP_200_OK
    )




@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def client_default_address(request):

    try:
        client = get_client_details(request)

        default_address = ClientAddress.objects.get(
            client=client,
            is_default=True
        )

    except ClientAddress.DoesNotExist:
        return Response(
            {"error": "No default address found."},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = ClientAddressNoDuplicatesSerializer(
        default_address
    )

    return Response(
        {
            "client_address": serializer.data
        },
        status=status.HTTP_200_OK
    )

@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def clients_by_addresses(request):

    try:
        client = get_client_details(request)
    except ClientDetails.DoesNotExist:
        return Response(
            {"error": "Client not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    ids_param = request.query_params.get("ids")

    if not ids_param:
        return Response(
            {"error": "Address IDs are required. Use ?ids=1,2,3"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        address_ids = [
            int(x.strip())
            for x in ids_param.split(",")
        ]
    except ValueError:
        return Response(
            {"error": "Invalid address IDs format."},
            status=status.HTTP_400_BAD_REQUEST
        )

    client_addresses = ClientAddress.objects.filter(
        client=client,
        address_id__in=address_ids
    ).select_related(
        "address"
    )

    serializer = ClientAddressSerializer(
        client_addresses,
        many=True,
        context={"request": request}
    )

    return Response(
        {
            "addresses": serializer.data
        },
        status=status.HTTP_200_OK
    )

@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def clients_by_address(request, address_id):

    try:
        client = get_client_details(request)

    except ClientDetails.DoesNotExist:
        return Response(
            {"error": "Client not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    try:
        client_address = ClientAddress.objects.select_related(
            "address"
        ).get(
            client=client,
            address_id=address_id
        )

    except ClientAddress.DoesNotExist:
        return Response(
            {
                "error": "Address not found or does not belong to you."
            },
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = ClientAddressSerializer(
        client_address,
        context={"request": request}
    )

    return Response(
        {
            "success": True,
            "data": serializer.data
        },
        status=status.HTTP_200_OK
    )