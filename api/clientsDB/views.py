from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, parser_classes, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny

from plug_backend.throttles import ProfileWriteThrottle, UserReadThrottle


# from rest_framework.permissions import IsAuthenticated
from .models.models import ClientAuth, ClientDetails, Address, ClientAddress, ClientNotification, DeviceToken 
from .serializers import AddressClaimSerializer, AddressOnlySerializer, AddressVerificationCreateSerializer, ClientAddressNoDuplicatesSerializer, AddressSerializer, ClientAddressWriteSerializer, ClientAuthReadSerializer, ClientLoginSerializer, ClientProfileSerializer, ClientRegisterSerializer, ClientSerializer, ClientAddressSerializer, DefaultAddressSerializer, DeviceTokenWriteSerializer

@api_view(['POST'])
@throttle_classes([ProfileWriteThrottle])
def register_client(request):
    serializer = ClientRegisterSerializer(data=request.data)

    if serializer.is_valid():
        email = serializer.validated_data['email_address'].lower()
        
        # Check if a client with this email already exists
        if ClientAuth.objects.filter(email_address=email).exists():
            return Response(
                {"error": "A user with this email already exists."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create authentication record
        client_auth = serializer.save()

        # Create empty profile if not exists
        ClientDetails.objects.get_or_create(client_profile=client_auth)

        return Response(
            {
                "message": "Registration successful.",
                "email": client_auth.email_address
            },
            status=status.HTTP_201_CREATED
        )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@throttle_classes([UserReadThrottle])
def get_client_by_email(request, email):
    try:
        client = ClientDetails.objects.get(client_profile__email_address=email)
    except ClientDetails.DoesNotExist:
        return Response(
            {"error": "Client not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = ClientSerializer(client, context={'request': request})
    return Response(serializer.data)

@api_view(['PATCH'])
@throttle_classes([ProfileWriteThrottle])
@parser_classes([MultiPartParser, FormParser])
def complete_profile_by_email(request, email):
    try:
        client = ClientDetails.objects.get(
            client_profile__email_address=email
        )
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

        # ✅ Move to next onboarding stage
        if (
            updated_client.first_name and
            updated_client.last_name and
            updated_client.date_of_birth
        ):
            updated_client.client_profile.is_profile_completed = "in-address"
            updated_client.client_profile.save()

        return Response(serializer.data)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['PATCH'])
@throttle_classes([ProfileWriteThrottle])
def set_default_address(request, address_id):
    """
    PATCH endpoint to set a selected address as default.
    Client is identified via query param ?email=<client_email>
    """
    client_email = request.query_params.get('email')
    if not client_email:
        return Response({"detail": "Client email is required."},
                        status=status.HTTP_400_BAD_REQUEST)
    
    try:
        client = ClientDetails.objects.get(client_profile__email_address=client_email)
    except ClientDetails.DoesNotExist:
        return Response({"detail": "Client not found."},
                        status=status.HTTP_404_NOT_FOUND)

    try:
        client_address = ClientAddress.objects.get(pk=address_id, client=client)
    except ClientAddress.DoesNotExist:
        return Response({"detail": "Address not found for this client."},
                        status=status.HTTP_404_NOT_FOUND)

    # Patch default
    client_address.is_default = True
    client_address.save()  # your model will unset previous defaults

    return Response({"detail": f"Address {client_address.address} is now default."},
                    status=status.HTTP_200_OK)


@api_view(['POST'])
@throttle_classes([ProfileWriteThrottle])
def add_residential_address(request, email):

    client = get_object_or_404(
        ClientDetails,
        client_profile__email_address=email
    )

    serializer = ClientAddressWriteSerializer(
        data=request.data,
        context={"client": client}
    )

    if not serializer.is_valid():
        return Response(serializer.errors, status=400)

    client_address = serializer.save()

    # ✅ Final onboarding stage
    client.client_profile.is_profile_completed = "completed"
    client.client_profile.save()

    return Response(
        {
            "message": "Address added successfully.",
            "data": ClientAddressSerializer(client_address).data
        },
        status=status.HTTP_201_CREATED
    )

@api_view(['GET'])
@throttle_classes([UserReadThrottle])
def client_auth_by_email(request, email):
    """
    GET: Fetch client auth details (without password)
    Example:
    /api/client-auth/thando@gmail.com/
    """

    client_auth = get_object_or_404(ClientAuth, email_address=email)

    serializer = ClientAuthReadSerializer(
        client_auth,
        context={'request': request}
    )

    return Response(serializer.data, status=status.HTTP_200_OK)

@api_view(["POST"])
@throttle_classes([ProfileWriteThrottle])
def submit_address_verification(request, client_address_id):
    # print("FILES RECEIVED:", request.FILES)
    # print("POST DATA:", request.data)
    
    try:
        client_address = ClientAddress.objects.get(id=client_address_id)
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
            {"message": "Verification submitted successfully.", "status": verification.status},
            status=status.HTTP_201_CREATED
        )

    print("SERIALIZER ERRORS:", serializer.errors)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@throttle_classes([ProfileWriteThrottle])
def register_device_token(request):
    print("FILES RECEIVED:", request.FILES)
    print("POST DATA:", request.data)   
    serializer = DeviceTokenWriteSerializer(data=request.data, context={'request': request})
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    token = serializer.validated_data["fcm_token"]

    # Remove duplicate tokens across all users
    DeviceToken.objects.filter(fcm_token=token).delete()

    device_token = serializer.save()

    return Response(
        {"message": "Device token registered successfully", "token_id": device_token.id},
        status=status.HTTP_201_CREATED
    )

@api_view(['POST'])
@throttle_classes([ProfileWriteThrottle])
def client_login(request):
    print("FILES RECEIVED:", request.FILES)
    print("POST DATA:", request.data)
    serializer = ClientLoginSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.validated_data['user']
        client_details = getattr(user, 'clientdetails', None)

        return Response({
            "email": user.email_address,
            "first_name": getattr(client_details, 'first_name', ''),
            "last_name": getattr(client_details, 'last_name', ''),
            "is_profile_completed": user.is_profile_completed,
        }, status=status.HTTP_200_OK)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



@api_view(['GET', 'POST', 'PUT', 'DELETE'])
@throttle_classes([UserReadThrottle])
def clientProfile_list(request,format=None):
    if request.method == 'DELETE':
        client_profile_id = request.data.get('id')
        try:
            client_profile = ClientAuth.objects.get(id=client_profile_id)
            client_profile.delete()
            return Response({'message': 'Client Profile deleted successfully.'}, status=204)
        except ClientAuth.DoesNotExist:
            return Response({'error': 'Client Profile not found.'}, status=404)

    if request.method == 'GET':
        client_profiles = ClientAuth.objects.all()
        serializer = ClientProfileSerializer(client_profiles, many=True)
        return Response({'Client Profiles': serializer.data})

@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@parser_classes([MultiPartParser, FormParser])
def client_list(request, format=None):
    if request.method == 'GET':
        clients = ClientDetails.objects.all()
        serializer = ClientSerializer(clients, many=True, context={'request': request})
        return Response(serializer.data)

    



@api_view(['GET'])
@throttle_classes([UserReadThrottle])
def address_list(request,format=None):

    if request.method == 'GET':
        addresses = Address.objects.all()
        serializer = AddressSerializer(addresses, many=True)
        return Response({'Addresses': serializer.data})

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
def client_address_list(request,format=None):
    if request.method == 'POST':
        serializer = ClientAddressSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({'message': 'Client Address created successfully.', 'data': serializer.data}, status=201)
        return Response({'error': 'Invalid data provided.', 'details': serializer.errors}, status=400)

    if request.method == 'PUT':
        serializer = ClientAddressSerializer(data=request.data)
        if serializer.is_valid():
            client_address = ClientAddress.objects.get(id=request.data.get('id'))
            serializer.update(client_address, request.data)
            return Response({'message': 'Client Address updated successfully.', 'data': serializer.data}, status=200)
        return Response({'error': 'Invalid data provided.', 'details': serializer.errors}, status=400)

    if request.method == 'GET':
        client_addresses = ClientAddress.objects.all()
        serializer = ClientAddressSerializer(client_addresses, many=True)
        return Response({'Client Addresses': serializer.data})

    if request.method == 'DELETE':
        client_address_id = request.data.get('id')
        try:
            client_address = ClientAddress.objects.get(id=client_address_id)
            client_address.delete()
            return Response({'message': 'Client Address deleted successfully.'}, status=204)
        except ClientAddress.DoesNotExist:
            return Response({'error': 'Client Address not found.'}, status=404)
        

@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@throttle_classes([UserReadThrottle])
# @permission_classes([IsAuthenticated])
def clientProfile_detail(request, email,format=None):
    try:
        client_profile = ClientAuth.objects.get(email_address=email)
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

    elif request.method == 'DELETE':
        client_profile.delete()
        return Response({'message': 'Client Profile deleted successfully.'}, status=status.HTTP_204_NO_CONTENT)

    return Response({'error': 'Method not allowed.'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

@api_view(['GET', 'PUT', 'DELETE'])
@throttle_classes([UserReadThrottle])
def client_detail(request, email,format=None):
    try:
        client = ClientDetails.objects.get(client_profile__email_address=email)
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

    elif request.method == 'DELETE':
        client.delete()
        return Response({'message': 'Client deleted successfully.'}, status=status.HTTP_204_NO_CONTENT)

@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@throttle_classes([UserReadThrottle])
# @permission_classes([IsAuthenticated])
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
def client_address_detail(request, email, format=None):
    # Fetch addresses for the client, default first
    client_addresses = ClientAddress.objects.filter(
        client__client_profile__email_address=email
    ).order_by('-is_default', 'id')  # default first, then by id

    if not client_addresses.exists():
        return Response({'error': 'Client Address not found.'}, status=status.HTTP_404_NOT_FOUND)

    serializer = ClientAddressSerializer(client_addresses, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)

    
    

@api_view(['GET', 'PUT'])
@throttle_classes([UserReadThrottle])
@parser_classes([MultiPartParser, FormParser])
# @permission_classes([IsAuthenticated])
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
def client_saved_addresses(request, email):
    try:
        client = ClientDetails.objects.get(client_profile__email_address=email)
    except ClientDetails.DoesNotExist:
        return Response({'error': 'Client not found.'}, status=status.HTTP_404_NOT_FOUND)

    client_addresses = ClientAddress.objects.filter(client=client).select_related('address')
    addresses = [ca.address for ca in client_addresses]

    # Inject clientaddress info into the address object dynamically
    for addr in addresses:
        ca = next((ca for ca in client_addresses if ca.address.id == addr.id), None)
        addr.clientaddress = ca

    serializer = AddressOnlySerializer(addresses, many=True)
    return Response({'addresses': serializer.data}, status=status.HTTP_200_OK)




@api_view(['GET'])
@throttle_classes([UserReadThrottle])
def client_default_address(request, email, format=None):
    """
    GET: Retrieve the client's address where is_default=True
    """
    try:
        default_address = ClientAddress.objects.get(
            client__client_profile__email_address=email,
            is_default=True
        )
    except ClientAddress.DoesNotExist:
        return Response({'error': 'No default address found.'}, status=status.HTTP_404_NOT_FOUND)

    serializer = ClientAddressNoDuplicatesSerializer(default_address)
    return Response({'Client Address': serializer.data}, status=status.HTTP_200_OK)





@api_view(['GET'])
@throttle_classes([UserReadThrottle])
def clients_by_addresses(request):

    # Get ids from query params
    ids_param = request.query_params.get('ids')
    if not ids_param:
        return Response({'error': 'Address IDs are required. Use ?ids=1,2,3'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        address_ids = [int(x) for x in ids_param.split(',')]
    except ValueError:
        return Response({'error': 'Invalid address IDs format.'}, status=status.HTTP_400_BAD_REQUEST)

    # Fetch client addresses for all given IDs
    client_addresses = ClientAddress.objects.filter(
        address__id__in=address_ids
    ).select_related("client", "client__client_profile")

    if not client_addresses.exists():
        return Response({'error': 'No clients found for these addresses.'}, status=status.HTTP_404_NOT_FOUND)

    # Deduplicate clients by email
    seen = set()
    unique_clients = []
    for ca in client_addresses:
        client = ca.client
        email = client.client_profile.email_address
        if email not in seen:
            seen.add(email)
            unique_clients.append(client)

    serializer = ClientSerializer(unique_clients, many=True, context={'request': request})
    return Response({'clients': serializer.data}, status=status.HTTP_200_OK)

@api_view(['GET'])
@throttle_classes([UserReadThrottle])
def clients_by_address(request, address_id):
    """
    GET: Fetch all clients linked to a specific address ID.
    """
    try:
        address = Address.objects.get(id=address_id)
    except Address.DoesNotExist:
        return Response({'error': 'Address not found.'}, status=status.HTTP_404_NOT_FOUND)

    # Fetch all client links to this address
    client_addresses = ClientAddress.objects.filter(address=address).select_related("client", "client__client_profile")

    if not client_addresses.exists():
        return Response({'error': 'No clients found for this address.'}, status=status.HTTP_404_NOT_FOUND)

    # Extract unique clients
    seen = set()
    unique_clients = []
    for ca in client_addresses:
        client = ca.client
        email = client.client_profile.email_address
        if email not in seen:
            seen.add(email)
            unique_clients.append(client)

    serializer = ClientSerializer(unique_clients, many=True, context={'request': request})
    return Response({'clients': serializer.data}, status=status.HTTP_200_OK)


