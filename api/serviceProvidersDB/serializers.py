from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from .models import CostOfService, ProviderService, SPLiveLocation, SPProfile, ServiceProvider, ServiceGroup, Service, Address



class SPProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = SPProfile
        fields = '__all__'
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        validated_data['password'] = make_password(validated_data['password'])
        return super().create(validated_data)


class SPAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = '__all__'


        


class ServiceGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceGroup
        fields = '__all__'


class ServiceSerializer(serializers.ModelSerializer):
    service_group = ServiceGroupSerializer()
    provider_count = serializers.SerializerMethodField()
    active_provider_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Service
        fields = '__all__'  

    def get_provider_count(self, obj):
        return obj.providers.count()

    def create(self, validated_data):
        group_data = validated_data.pop('service_group')
        group, created = ServiceGroup.objects.get_or_create(
            group_id=group_data['group_id'],
            defaults={'name': group_data['name']}
        )
        return Service.objects.create(service_group=group, **validated_data)

class ServiceProviderReadSerializer(serializers.ModelSerializer):
    sp_profile = SPProfileSerializer()
    location = SPAddressSerializer()
    services = ServiceSerializer(many=True)

    class Meta:
        model = ServiceProvider
        fields = '__all__'

class ProviderSeviceSerializer(serializers.ModelSerializer):
    service = ServiceSerializer()
    provider = ServiceProviderReadSerializer()
    class Meta:
        model = ProviderService
        
        
        fields = '__all__'

class ServiceProviderWriteSerializer(serializers.ModelSerializer):
    sp_profile = SPProfileSerializer()
    location = SPAddressSerializer()
    services = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Service.objects.all(), required=False
    )
    profile_image = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = ServiceProvider
        fields = '__all__'

    def create(self, validated_data):
        profile_data = validated_data.pop('sp_profile')
        location_data = validated_data.pop('location')
        services_data = validated_data.pop('services', [])
        profile_image = validated_data.pop('profile_image', None)

        email = profile_data['email_address']
        if SPProfile.objects.filter(email_address=email).exists():
            raise serializers.ValidationError({
                "sp_profile": {
                    "email_address": "A profile with this email already exists."
                }
            })

        profile_data['password'] = make_password(profile_data['password'])
        sp_profile = SPProfile.objects.create(**profile_data)
        location = Address.objects.create(**location_data)

        service_provider = ServiceProvider.objects.create(
            sp_profile=sp_profile,
            location=location,
            profile_image=profile_image,
            **validated_data
        )

        if services_data:
            service_provider.services.set(services_data)

        return service_provider
    


class CostOfServiceSerializer(serializers.ModelSerializer):
    service = ServiceSerializer(read_only=True)
    service_id = serializers.PrimaryKeyRelatedField(
        queryset=Service.objects.all(), write_only=True, source='service'
    )
    provider = ServiceProviderReadSerializer(read_only=True)

    class Meta:
        model = CostOfService
        fields = [
            'id',
            'service',        # nested (read-only)
            'service_id',     # write-only field to set relation
            'provider',       # nested (read-only)
            'base_price',
            'negotiable',
            'notes',
        ]
        read_only_fields = ['provider']

    def validate(self, data):
        provider = self.context['request'].user.serviceprovider
        service = data.get('service')
        if service not in provider.services.all():
            raise serializers.ValidationError("You can only set costs for services linked to you.")
        base_price = data.get('base_price')
        if base_price is not None and base_price <= 0:
            raise serializers.ValidationError("Base price must be positive.")
        return data

    def create(self, validated_data):
        validated_data['provider'] = self.context['request'].user.serviceprovider
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('provider', None)
        return super().update(instance, validated_data)
    

class SPLiveLocationSerializer(serializers.ModelSerializer):


    class Meta:
        model = SPLiveLocation
        fields = '__all__'

class SPLiveLocationUpdateSerializer(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)

