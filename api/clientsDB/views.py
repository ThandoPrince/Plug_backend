from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny


# from rest_framework.permissions import IsAuthenticated
from .models.models import ClientAuth, ClientDetails, Address, ClientAddress, ClientNotification 
from .serializers import AddressClaimSerializer, AddressOnlySerializer, ClientAddressNoDuplicatesSerializer, AddressSerializer, ClientAddressWriteSerializer, ClientLoginSerializer, ClientProfileSerializer, ClientRegisterSerializer, ClientSerializer, ClientAddressSerializer, DefaultAddressSerializer

@api_view(['POST'])
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
@parser_classes([MultiPartParser, FormParser])
def complete_profile_by_email(request, email):
    try:
        client = ClientDetails.objects.get(client_profile__email_address=email)
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

        # Mark onboarding complete
        if (
            updated_client.first_name and
            updated_client.last_name and
            updated_client.date_of_birth
        ):
            updated_client.client_profile.is_profile_completed = True
            updated_client.client_profile.save()

        return Response(serializer.data)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
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
        print(serializer.errors)
        return Response(serializer.errors, status=400)
    client_address = serializer.save()

    return Response(
        {
            "message": "Address added successfully.",
            "data": ClientAddressSerializer(client_address).data
        },
        status=status.HTTP_201_CREATED
    )

@api_view(['POST'])
def client_login(request):
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

    # Return structured errors
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



@api_view(['GET', 'POST', 'PUT', 'DELETE'])
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
@parser_classes([MultiPartParser, FormParser])
def client_list(request, format=None):
    if request.method == 'GET':
        clients = ClientDetails.objects.all()
        serializer = ClientSerializer(clients, many=True, context={'request': request})
        return Response(serializer.data)

    



@api_view(['GET'])
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
        
@api_view(['GET', 'POST', 'PUT', 'DELETE'])
def client_address_list_emai(request,format=None):
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

@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
def client_address_detail(request, email, format=None):
    client_addresses = ClientAddress.objects.filter(client__client_profile__email_address=email)

    if not client_addresses.exists():
        return Response({'error': 'Client Address not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = ClientAddressSerializer(client_addresses, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    elif request.method in ['PUT', 'PATCH']:
        partial = request.method == 'PATCH'
        responses = []
        errors = []
        
        for instance in client_addresses:
            serializer = ClientAddressSerializer(instance, data=request.data, partial=partial)
            if serializer.is_valid():
                serializer.save()
                responses.append(serializer.data)
            else:
                errors.append({
                    'id': instance.id,
                    'errors': serializer.errors
                })

        if errors:
            return Response({
                'message': 'Some updates failed.',
                'updated': responses,
                'failed': errors
            }, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'message': 'Client Address(es) updated successfully.',
            'data': responses
        }, status=status.HTTP_200_OK)

    elif request.method == 'DELETE':
        deleted_count = client_addresses.delete()[0]
        return Response({
            'message': f'{deleted_count} Client Address(es) deleted successfully.'
        }, status=status.HTTP_204_NO_CONTENT)

@api_view(['GET', 'PUT'])
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
def get_client_coordinates(request, email):
    """
    Returns a list of coordinates (latitude, longitude) for the given client's addresses.
    """
    try:
        client_auth = ClientAuth.objects.get(email_address=email)
        client_details = ClientDetails.objects.get(client_profile=client_auth)
    except (ClientAuth.DoesNotExist, ClientDetails.DoesNotExist):
        return Response({"detail": "Client not found."}, status=status.HTTP_404_NOT_FOUND)

    # Get all related ClientAddress entries
    client_addresses = ClientAddress.objects.filter(client=client_details).select_related('address')

    if not client_addresses.exists():
        return Response({"detail": "No addresses found for this client."}, status=status.HTTP_404_NOT_FOUND)

    coordinates = []
    for ca in client_addresses:
        addr = ca.address
        if addr.latitude is not None and addr.longitude is not None:
            coordinates.append({
                "address_id": addr.id,
                "latitude": float(addr.latitude),
                "longitude": float(addr.longitude),
                "formatted_address": addr.formatted_address
            })

    return Response(coordinates, status=status.HTTP_200_OK)

@api_view(['GET'])
def get_client_coordinates_by_address_and_email(request):
    address_id = request.query_params.get('address_id')
    email = request.query_params.get('email')

    if not address_id or not email:
        return Response({"error": "Both address_id and email parameters are required."},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        clients = ClientDetails.objects.filter(
            location_id=address_id,
            client_profile__email_address=email
        ).select_related('location', 'client_profile')

        coordinates = []
        for client in clients:
            if client.location and client.location.latitude is not None and client.location.longitude is not None:
                coordinates.append({
                    "client_email": client.client_profile.email_address,
                    "latitude": float(client.location.latitude),
                    "longitude": float(client.location.longitude)
                })

        return Response(coordinates, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    

@api_view(['POST'])
# @permission_classes([IsAuthenticated])
def claim_address(request):
    serializer = AddressClaimSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    user = request.user
    client = getattr(user, "clientdetails", None)
    if not client:
        return Response({"error": "Only clients can claim addresses."}, status=403)

    address = Address.objects.filter(
        street_number=data['street_number'],
        route=data['route'],
        locality=data['locality'],
        administrative_area_level_1=data['administrative_area_level_1'],
        postal_code=data['postal_code'],
        country=data['country'],
    ).first()

    if address:
        owner_link = ClientAddress.objects.filter(address=address, is_owner=True).first()

        # Already linked?
        if ClientAddress.objects.filter(client=client, address=address).exists():
            return Response({"message": "You're already linked to this address."})

        if owner_link:
            # Link client to address as non-owner
            ClientAddress.objects.create(client=client, address=address, is_owner=False, is_verified=False)

            # Notify current owner
            ClientNotification.objects.create(
                recipient=owner_link.client.user,
                title="Address Claim Attempt",
                message=f"{client.client_profile.first_name} wants to use your address ({address.formatted_address}). Please review and approve in your app.",
            )

            return Response({
                "status": "pending_owner_verification",
                "message": "Address added, but it's not verified yet. The current owner has been notified.",
                "address_id": address.id
            }, status=202)

        else:
            # No owner — ask if client wants to claim ownership
            ClientAddress.objects.create(client=client, address=address, is_owner=False, is_verified=False)
            return Response({
                "status": "no_owner",
                "message": "Address has no owner. You may use it now, but it's unverified. Would you like to become the owner?",
                "address_id": address.id
            }, status=200)

    # Create new address and ask user if they want to own it
    new_address = Address.objects.create(**data)
    ClientAddress.objects.create(client=client, address=new_address, is_owner=False, is_verified=False)

    return Response({
        "status": "new_address",
        "message": "Address created and linked to you, but not verified. Would you like to become the owner?",
        "address_id": new_address.id
    }, status=201)



@api_view(['POST'])
# @permission_classes([IsAuthenticated])
def approve_address_request(request):
    address_id = request.data.get('address_id')
    client_id = request.data.get('client_id')
    approve = request.data.get('approve')  # true / false

    if address_id is None or client_id is None or approve is None:
        return Response({"error": "address_id, client_id, and approve are required."}, status=400)

    try:
        address = Address.objects.get(id=address_id)
        owner_link = ClientAddress.objects.get(address=address, is_owner=True)
    except (Address.DoesNotExist, ClientAddress.DoesNotExist):
        return Response({"error": "Invalid address or owner not found."}, status=404)

    if owner_link.client.user != request.user:
        return Response({"error": "Only the current owner can approve or reject."}, status=403)

    try:
        target_link = ClientAddress.objects.get(address=address, client_id=client_id)
    except ClientAddress.DoesNotExist:
        return Response({"error": "Requested client not linked to this address."}, status=404)

    if approve:
        target_link.is_verified = True
        target_link.save()
        return Response({"message": "Client successfully verified for this address."})
    else:
        target_link.delete()
        return Response({"message": "Client's address request has been rejected and removed."})


@api_view(['POST'])
# @permission_classes([IsAuthenticated])
def become_address_owner(request, address_id):
    user = request.user
    client = getattr(user, "clientdetails", None)
    if not client:
        return Response({"error": "Only clients can own addresses."}, status=403)

    try:
        client_address = ClientAddress.objects.get(client=client, address_id=address_id)
    except ClientAddress.DoesNotExist:
        return Response({"error": "You're not linked to this address."}, status=404)

    # Prevent if someone else already owns this address
    existing_owner = ClientAddress.objects.filter(address_id=address_id, is_owner=True).exclude(client=client).first()
    if existing_owner:
        return Response({"error": "Address already has an owner."}, status=400)

    # Upgrade to ownership
    client_address.is_owner = True
    client_address.is_verified = True
    client_address.save()

    return Response({
        "status": "ownership_confirmed",
        "message": "You are now the verified owner of this address.",
        "address_id": address_id
    }, status=200)


# @api_view(['POST'])
# def set_default_address(request, client_email):
#     try:
#         client = ClientDetails.objects.get(client_profile__email_address=client_email)
#     except ClientDetails.DoesNotExist:
#         return Response({'error': 'Client not found'}, status=status.HTTP_404_NOT_FOUND)

#     client_address_id = request.data.get('client_address_id')
#     if not client_address_id:
#         return Response({'error': 'client_address_id is required'}, status=status.HTTP_400_BAD_REQUEST)

#     try:
#         client_address = ClientAddress.objects.get(id=client_address_id, client=client)
#     except ClientAddress.DoesNotExist:
#         return Response({'error': 'ClientAddress not found for this client'}, status=status.HTTP_404_NOT_FOUND)

#     client.default_address = client_address
#     client.save()

#     return Response({'message': 'Default address updated successfully'}, status=status.HTTP_200_OK)







@api_view(['GET'])
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


@api_view(['PATCH'])
def set_default_address(request, email, address_id):
    """
    PATCH: Set one address as default (unsets previous default automatically).
    """
    client = get_object_or_404(ClientDetails, client_profile__email_address=email)
    address = get_object_or_404(ClientAddress, id=address_id, client=client)

    # Unset previous defaults
    ClientAddress.objects.filter(client=client, is_default=True).exclude(id=address.id).update(is_default=False)

    # Set the chosen one as default
    address.is_default = True
    address.save()

    serializer = DefaultAddressSerializer(address)
    return Response(serializer.data, status=status.HTTP_200_OK)



@api_view(['GET'])
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


