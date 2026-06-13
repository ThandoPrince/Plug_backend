from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from .models.models import AddressSuperUserVerification, ClientAuth, Address, ClientDetails, ClientAddress, ClientNotification, DeviceToken
import re
from django.db.models import Q
from django.contrib.auth.hashers import check_password
import phonenumbers
from datetime import date
from django.db import transaction

class ClientProfileSerializer(serializers.ModelSerializer):
    # Add 'profile_image' to fields if it exists in ClientAuth model

    class Meta:
        model = ClientAuth
        fields = ['email_address', 'mobile_number', 'password']
        extra_kwargs = {
            'password': {'write_only': True},
        }

    def create(self, validated_data):
        validated_data['password'] = make_password(validated_data['password'])
        return super().create(validated_data)

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)

        if password:
            instance.password = make_password(password)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance




class ClientAuthReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientAuth
        fields = [
            'id',
            'email_address',
            'mobile_number',
            'is_profile_completed',
        ]
    
class ClientRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        min_length=8,
        style={'input_type': 'password'}
    )
    mobile_number = serializers.CharField()

    class Meta:
        model = ClientAuth
        fields = ['email_address', 'mobile_number', 'password']
        extra_kwargs = {'password': {'write_only': True}}

    def validate_email_address(self, value):
        value = value.lower()
        if ClientAuth.objects.filter(email_address=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_mobile_number(self, value):
    # Remove spaces, dashes, brackets
        cleaned = re.sub(r'\D', '', value)

    # Must be exactly 10 digits
        if not re.fullmatch(r'\d{10}', cleaned):
            raise serializers.ValidationError(
                "Phone number must be exactly 10 digits."
            )

    # Must start with 0 (SA local format)
        if not cleaned.startswith('0'):
            raise serializers.ValidationError(
                "Phone number must start with 0."
            )

    # Convert to international format (+27)
        normalized = '+27' + cleaned[1:]

    # Validate properly using phonenumbers
        try:
            number = phonenumbers.parse(normalized)
            if not phonenumbers.is_valid_number(number):
                raise serializers.ValidationError("Enter a valid South African mobile number.")
        except phonenumbers.NumberParseException:
            raise serializers.ValidationError("Invalid phone number format.")

    # Ensure uniqueness
        if ClientAuth.objects.filter(mobile_number=normalized).exists():
            raise serializers.ValidationError(
                "A user with this mobile number already exists."
            )

        return normalized


    def validate_password(self, value):
        errors = []
        if not re.search(r'[A-Z]', value):
            errors.append("Password must contain at least one uppercase letter.")
        if not re.search(r'[a-z]', value):
            errors.append("Password must contain at least one lowercase letter.")
        if not re.search(r'\d', value):
            errors.append("Password must contain at least one digit.")
        if errors:
            raise serializers.ValidationError(errors)
        return value

    def create(self, validated_data):
        validated_data['password'] = make_password(validated_data['password'])
        return ClientAuth.objects.create(**validated_data)

class AddressSerializer(serializers.ModelSerializer):
    clients = serializers.SerializerMethodField()

    class Meta:
        model = Address
        fields = '__all__'

    def get_clients(self, obj):
        return ClientSerializer(obj.clients.all(), many=True).data
    
class ClientProfileSerializer(serializers.ModelSerializer):
    # Add 'profile_image' to fields if it exists in ClientAuth model

    class Meta:
        model = ClientAuth
        fields = ['email_address', 'mobile_number', 'password']
        extra_kwargs = {
            'password': {'write_only': True},
        }

    def create(self, validated_data):
        validated_data['password'] = make_password(validated_data['password'])
        return super().create(validated_data)

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)

        if password:
            instance.password = make_password(password)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance

class ClientSerializer(serializers.ModelSerializer):
    client_profile = ClientProfileSerializer()
    client_pp = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = ClientDetails
        fields = '__all__'

    def validate_date_of_birth(self, value):
        """Validate date_of_birth field if provided"""
        if value:
            if value > date.today():
                raise serializers.ValidationError("Date of birth cannot be in the future.")
            age = (date.today() - value).days // 365
            if age < 18:
                raise serializers.ValidationError("Client must be at least 18 years old.")
        return value

    def validate(self, data):
        # Validate DOB in nested updates (PATCH)
        dob = data.get('date_of_birth')
        if not dob and 'client_profile' in data:
            dob = data['client_profile'].get('date_of_birth')
        if dob:
            self.validate_date_of_birth(dob)
        return data

    def create(self, validated_data):
        profile_data = validated_data.pop('client_profile')
        email = profile_data['email_address']

        if ClientDetails.objects.filter(client_profile__email_address=email).exists():
            raise serializers.ValidationError({
                "client_profile": {
                    "email_address": "A profile with this email already exists and is linked to a client."
                }
            })

        profile_data['password'] = make_password(profile_data['password'])
        client_profile = ClientAuth.objects.create(**profile_data)
        validated_data['client_profile'] = client_profile

        client = ClientDetails.objects.create(**validated_data)
        return client

    def update(self, instance, validated_data):
        profile_data = validated_data.pop('client_profile', None)
        if profile_data:
            for attr, value in profile_data.items():
                if attr == 'password':
                    value = make_password(value)
                setattr(instance.client_profile, attr, value)
            instance.client_profile.save()

        if 'client_pp' in validated_data:
            instance.client_pp = validated_data.pop('client_pp')

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance
    
class AddressWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = '__all__'

class ClientAddressSerializer(serializers.ModelSerializer):
    client = ClientSerializer()
    address = AddressSerializer()

    class Meta:
        model = ClientAddress
        fields = '__all__'

class DeviceTokenWriteSerializer(serializers.ModelSerializer):

    push_token = serializers.CharField(
        source='fcm_token'
    )

    class Meta:
        model = DeviceToken
        fields = ['push_token']

    def create(self, validated_data):

        validated_data['client'] = self.context[
            'request'
        ].user

        return DeviceToken.objects.create(
            **validated_data
        )
    
class DeviceTokenReadSerializer(serializers.ModelSerializer):
    client_email = serializers.CharField(source='client.email_address', read_only=True)

    class Meta:
        model = DeviceToken
        fields = '__all__'

class AddressWriteSerializer(serializers.ModelSerializer):

    class Meta:
        model = Address
        fields = [
            'latitude',
            'longitude',
            'place_id',
            'street_number',
            'route',
            'locality',
            'administrative_area_level_1',
            'country',
            'postal_code',
        ]

    def validate(self, attrs):
        street_number = attrs.get('street_number')
        route = attrs.get('route')

        errors = {}

        if not street_number:
            errors['street_number'] = "Street number is required."

        if not route:
            errors['route'] = "Street name (route) is required."

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


class ClientAddressWriteSerializer(serializers.ModelSerializer):
    address = AddressWriteSerializer()

    class Meta:
        model = ClientAddress
        fields = [
            "address",
            "is_owner",
            "is_default",
            "address_type",
            "house_administrator"
        ]

    @transaction.atomic
    def create(self, validated_data):
        address_data = validated_data.pop("address")
        client = self.context["client"]

     
        building_type = address_data.get("building_type", "house")
        unit_number = address_data.get("unit_number")

        if building_type == "apartment" and not unit_number:
            raise serializers.ValidationError("Unit number is required for apartments.")
        if building_type == "house" and unit_number:
            raise serializers.ValidationError("Houses cannot have a unit number.")

   
        address, created = Address.objects.get_or_create(
            place_id=address_data.get("place_id"),
            unit_number=unit_number or "",
            defaults={
                "street_number": address_data.get("street_number"),
                "route": address_data.get("route"),
                "locality": address_data.get("locality"),
                "administrative_area_level_1": address_data.get("administrative_area_level_1"),
                "postal_code": address_data.get("postal_code"),
                "country": address_data.get("country"),
                "latitude": address_data.get("latitude"),
                "longitude": address_data.get("longitude"),
                "building_type": building_type,
            }
        )

    
        if not created and not address.place_id and address_data.get("place_id"):
            address.place_id = address_data["place_id"]
            address.save(update_fields=["place_id"])

 
        if ClientAddress.objects.filter(client=client, address=address).exists():
            raise serializers.ValidationError("You have already added this address.")

     
        client_address = ClientAddress.objects.create(
            client=client,
            address=address,
            **validated_data
        )

        return client_address
    

class AddressVerificationCreateSerializer(serializers.ModelSerializer):
    client_address = serializers.PrimaryKeyRelatedField(
        queryset=ClientAddress.objects.all()
    )

    class Meta:
        model = AddressSuperUserVerification
        fields = [
            "client_address",
            "proof_of_residence",
            "id_document",
        ]

    def validate(self, attrs):
        client_address = attrs["client_address"]

        if hasattr(client_address, "verification_request"):
            existing = client_address.verification_request

            if existing.status == "approved":
                raise serializers.ValidationError(
                    "This address has already been verified."
                )

            if existing.status == "pending":
                raise serializers.ValidationError(
                    "Verification request is already pending."
                )

  
        if not attrs.get("proof_of_residence") or not attrs.get("id_document"):
            raise serializers.ValidationError(
                "Both proof of residence and ID document must be uploaded."
            )

        return attrs

    def create(self, validated_data):
        return AddressSuperUserVerification.objects.create(**validated_data)

    
class ClientLoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(required=True)
    password = serializers.CharField(write_only=True, required=True, min_length=6)

    def validate(self, data):
        identifier = data.get("identifier")
        password = data.get("password")
        print("ALL USERS:")
        print(ClientAuth.objects.all().values("id", "email_address", "mobile_number"))

        user = ClientAuth.objects.filter(
            Q(email_address__iexact=identifier) |
            Q(mobile_number=identifier)
        ).first()

        if not user:
            print("LOGIN FAILED: USER NOT FOUND")
            raise serializers.ValidationError({
                "non_field_errors": ["Invalid email/mobile number or password."]
            })

        print("USER FOUND:", user.email_address)

        if not check_password(password, user.password):
            print("LOGIN FAILED: WRONG PASSWORD")
            raise serializers.ValidationError({
                "non_field_errors": ["Invalid email/mobile number or password."]
            })

        data["user"] = user
        return data
        



class ClientProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientAuth
        fields = ['mobile_number', 'password']
        extra_kwargs = {
            'password': {'write_only': True, 'required': False},
        }

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        if password:
            instance.password = make_password(password)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance

class ClientUpdateSerializer(serializers.ModelSerializer):
    client_profile = ClientProfileUpdateSerializer()

    class Meta:
        model = ClientDetails
        fields = ['first_name', 'last_name', 'client_profile']

    def update(self, instance, validated_data):
        profile_data = validated_data.pop('client_profile', {})

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        profile = instance.client_profile
        profile_serializer = ClientProfileUpdateSerializer(profile, data=profile_data, partial=True)
        if profile_serializer.is_valid(raise_exception=True):
            profile_serializer.save()

        return instance

class AddressOnlySerializer(serializers.ModelSerializer):
    address_type = serializers.CharField(source='clientaddress.address_type', read_only=True)
    is_owner = serializers.BooleanField(source='clientaddress.is_owner', read_only=True)

    class Meta:
        model = Address
        fields = [
            'id', 'latitude', 'longitude', 'place_id', 'street_number',
            'route', 'locality', 'administrative_area_level_1',
            'formatted_address', 'country', 'postal_code',
            'address_type', 'is_owner'
        ]

class AddressClaimSerializer(serializers.Serializer):
    street_number = serializers.CharField()
    route = serializers.CharField()
    locality = serializers.CharField()
    administrative_area_level_1 = serializers.CharField()
    postal_code = serializers.CharField()
    country = serializers.CharField()
    formatted_address = serializers.CharField()

    def validate(self, data):
        address = Address.objects.filter(
            street_number=data['street_number'],
            route=data['route'],
            locality=data['locality'],
            administrative_area_level_1=data['administrative_area_level_1'],
            postal_code=data['postal_code']
        ).first()

        if address:
            owners = ClientAddress.objects.filter(address=address, is_owner=True)
            if owners.exists():
                raise serializers.ValidationError({
                    "status": "pending_approval",
                    "message": "Address is owned. Approval needed."
                })
            else:
                raise serializers.ValidationError({
                    "status": "prompt_owner",
                    "message": "Address exists without an owner. Prompt to claim ownership."
                })

        return data
    
class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientNotification
        fields = ['id', 'title', 'message', 'is_read', 'created_at']

class DefaultAddressSerializer(serializers.ModelSerializer):
    address = AddressSerializer(read_only=True)  # <-- nest full Address
    is_default = serializers.SerializerMethodField()

    class Meta:
        model = ClientAddress
        fields = [
            "id",
            "client",
            "address",
            "is_owner",
            "house_administrator",
            "is_super_user",
            "address_type",
            "is_verified",
            "is_default",
        ]



class AddressNoDuplicateClientsSerializer(AddressSerializer):
    """
    Serializes Address but removes duplicate clients.
    """
    clients = serializers.SerializerMethodField()

    class Meta:
        model = Address
        fields = '__all__'

    def get_clients(self, obj):
        # Use a set to track unique email addresses
        seen = set()
        unique_clients = []
        for client in obj.clients.all():
            email = client.client_profile.email_address
            if email not in seen:
                seen.add(email)
                unique_clients.append(client)
        return ClientSerializer(unique_clients, many=True).data


class ClientAddressNoDuplicatesSerializer(serializers.ModelSerializer):
    address = AddressNoDuplicateClientsSerializer(read_only=True)
    is_default = serializers.BooleanField(read_only=True)  # <-- removed source

    class Meta:
        model = ClientAddress
        fields = [
            "id",
            "client",
            "address",
            "is_owner",
            "house_administrator",
            "is_super_user",
            "address_type",
            "is_verified",
            "is_default",
        ]