from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from .models import ClientAuth, Address, ClientDetails, ClientAddress, ClientNotification

class ClientProfileSerializer(serializers.ModelSerializer):
    # Add profile_image if you have it on ClientAuth model
    class Meta:
        model = ClientAuth
        fields = ['email_address', 'mobile_number', 'password']  # add 'profile_image' here if exists
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

class AddressSerializer(serializers.ModelSerializer):
    clients = serializers.SerializerMethodField()

    class Meta:
        model = Address
        fields = '__all__'

    def get_clients(self, obj):
        return ClientSerializer(obj.clients.all(), many=True).data

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
        profile_data = validated_data.pop('client_profile', None)

        if profile_data:
            for attr, value in profile_data.items():
                if attr == 'password':
                    value = make_password(value)
                setattr(instance.client_profile, attr, value)
            instance.client_profile.save()

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


class ClientAddressSerializer(serializers.ModelSerializer):
    client = ClientSerializer()
    address = AddressSerializer()
   

    class Meta:
        model = ClientAddress
        fields = '__all__'


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