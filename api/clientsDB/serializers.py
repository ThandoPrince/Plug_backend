from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from .models.models import ClientAuth, Address, ClientDetails, ClientAddress, ClientNotification
import re
import phonenumbers

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
        # Clean input
        cleaned = re.sub(r'[\s\-\(\)]', '', value)

        # Try parsing with phonenumbers
        try:
            if not cleaned.startswith('+'):
                # Assume South Africa (+27) if no country code
                cleaned = '+27' + cleaned.lstrip('0')
            number = phonenumbers.parse(cleaned)
            if not phonenumbers.is_valid_number(number):
                raise serializers.ValidationError("Enter a valid phone number.")
            normalized = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException:
            raise serializers.ValidationError("Enter a valid phone number with optional country code.")

        # Ensure uniqueness
        if ClientAuth.objects.filter(mobile_number=normalized).exists():
            raise serializers.ValidationError("A user with this mobile number already exists.")

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
    # Handle nested client_profile updates
        profile_data = validated_data.pop('client_profile', None)
        if profile_data:
            for attr, value in profile_data.items():
                if attr == 'password':
                    value = make_password(value)
                setattr(instance.client_profile, attr, value)
            instance.client_profile.save()

    # Handle image upload separately
        if 'client_pp' in validated_data:
            instance.client_pp = validated_data.pop('client_pp')

    # Handle other fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        request = self.context.get('request')
        if request and instance.client_pp:
            rep['client_pp'] = request.build_absolute_uri(instance.client_pp.url)
        return rep
    
class AddressWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = [
            'street_number',
            'route',
            'locality',
            'administrative_area_level_1',
            'country',
            'postal_code',
            'latitude',
            'longitude'
        ]

class ClientAddressSerializer(serializers.ModelSerializer):
    client = ClientSerializer()
    address = AddressSerializer()

    class Meta:
        model = ClientAddress
        fields = '__all__'

class ClientAddressWriteSerializer(serializers.ModelSerializer):
    address = AddressWriteSerializer()  # Nested write serializer

    class Meta:
        model = ClientAddress
        fields = [
            'address',
            'is_owner',
            'is_default',
            'address_type',
        ]

    def create(self, validated_data):
        # Extract nested address data
        address_data = validated_data.pop('address')
        client = self.context.get('client')  # Pass client in serializer context

        # Create or reuse Address
        address, _ = Address.objects.get_or_create(**address_data)

        # Create ClientAddress linking client and address
        client_address = ClientAddress.objects.create(
            client=client,
            address=address,
            **validated_data
        )
        return client_address

    def update(self, instance, validated_data):
        # Handle nested address updates
        address_data = validated_data.pop('address', None)
        if address_data:
            for attr, value in address_data.items():
                setattr(instance.address, attr, value)
            instance.address.save()

        # Update ClientAddress fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance



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