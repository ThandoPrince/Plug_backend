from rest_framework import serializers
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
import re
from rest_framework import serializers
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import CostOfServiceImage, DeviceToken, SPProfile
from .models import CostOfService, ProviderService, SPLiveLocation, SPProfile, ServiceCategory, ServiceProvider, ServiceGroup, Service, Address, SupportingDocument


class SPProfileWriteSerializer(serializers.ModelSerializer):
    email_address = serializers.EmailField()
    password = serializers.CharField(
        write_only=True,
        min_length=6,
        style={'input_type': 'password'}
    )

    class Meta:
        model = SPProfile
        fields = ["email_address", "password", "mobile_number"]

    def validate_email_address(self, value):
        email = value.lower().strip()

        try:
            validate_email(email)
        except DjangoValidationError:
            raise serializers.ValidationError("Enter a valid email address.")

        if SPProfile.objects.filter(email_address=email).exists():
            raise serializers.ValidationError(
                "An account with this email already exists."
            )

        return email

    def validate_password(self, value):
        if not re.search(r'[A-Z]', value):
            raise serializers.ValidationError(
                "Password must contain at least one uppercase letter."
            )

        if not re.search(r'[a-z]', value):
            raise serializers.ValidationError(
                "Password must contain at least one lowercase letter."
            )

        if not re.search(r'[!@#$%^&*(),.?\":{}|<>]', value):
            raise serializers.ValidationError(
                "Password must contain at least one special character."
            )

        return value

    def validate_mobile_number(self, value):

        raw_number = value.strip().replace(" ", "").replace("-", "")

        if not raw_number.isdigit() or len(raw_number) != 10:
            raise serializers.ValidationError(
                "Mobile number must be exactly 10 digits."
            )

        if raw_number in ["0000000000", "1234567890"]:
            raise serializers.ValidationError(
                "Please enter a valid mobile number."
            )

        normalized = raw_number
        if normalized.startswith("0"):
            normalized = f"+27{normalized[1:]}"

        if SPProfile.objects.filter(mobile_number=normalized).exists():
            raise serializers.ValidationError(
                "This mobile number is already registered."
            )

        return normalized

    @transaction.atomic
    def create(self, validated_data):
        password = validated_data.pop("password")

        # 🔒 Force lowercase email again for safety
        validated_data["email_address"] = validated_data["email_address"].lower()

        sp_profile = SPProfile(**validated_data)
        sp_profile.set_password(password)
        sp_profile.save()

        # Auto-create provider profile
        ServiceProvider.objects.create(
            sp_profile=sp_profile,
            full_name="",
            id_number="",
            dob="2000-01-01",
        )

        return sp_profile
    
class DeviceTokenWriteSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(write_only=True, required=True)
    push_token = serializers.CharField(write_only=True, required=True, source='fcm_token')

    class Meta:
        model = DeviceToken
        fields = '__all__'
        extra_kwargs = {
            'service_provider': {'read_only': True},
            'fcm_token': {'required': False},
        }

    def create(self, validated_data):
        email = validated_data.pop('email').strip().lower()

        try:
            service_provider = SPProfile.objects.get(email_address=email)
        except SPProfile.DoesNotExist:
            raise serializers.ValidationError({
                "email": "No service provider found with this email."
            })

        validated_data['service_provider'] = service_provider
        return super().create(validated_data)
    



class ServiceProviderPatchSerializer(serializers.ModelSerializer):
    # Ensure all fields are explicitly required
    full_name = serializers.CharField(required=True, allow_blank=False)
    id_number = serializers.CharField(required=True, min_length=13, max_length=13)
    dob = serializers.DateField(required=True)
    gender = serializers.CharField(required=True)
    sp_description = serializers.CharField(required=True)
    location = serializers.CharField(required=False)
    profile_image = serializers.ImageField(required=True)

    class Meta:
        model = ServiceProvider
        fields = [
            "full_name", "gender", "id_number", 
            "dob", "sp_description", "location", "profile_image",
        ]

    def validate_id_number(self, value):
        clean_id = str(value).strip()
        if not clean_id.isdigit() or len(clean_id) != 13:
            raise serializers.ValidationError("SA ID must be exactly 13 digits.")
        
        if ServiceProvider.objects.exclude(pk=self.instance.pk).filter(id_number=clean_id).exists():
            raise serializers.ValidationError("This ID number is already in use.")
        return clean_id

    def validate(self, data):
        """
        Cross-field validation: Compare ID number with Date of Birth.
        """
        id_num = data.get('id_number')
        dob = data.get('dob')

        if id_num and dob:
            # Extract YYMMDD from ID (first 6 digits)
            id_dob_part = id_num[:6]
            # Format DOB from input to YYMMDD
            expected_dob_part = dob.strftime('%y%m%d')

            if id_dob_part != expected_dob_part:
                raise serializers.ValidationError({
                    "id_number": f"ID number ({id_dob_part}...) does not match Date of Birth ({expected_dob_part})."
                })

        return data

    @transaction.atomic
    def update(self, instance, validated_data):
        return super().update(instance, validated_data)
    

class AddressWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = [
            "building_type", "unit_number", "street_number", "route",
            "locality", "administrative_area_level_1", "formatted_address",
            "country", "postal_code", "latitude", "longitude", "place_id",
        ]
        # We set these to allow blank so the conditional logic can handle the "Required" part
        extra_kwargs = {
            'unit_number': {'required': False, 'allow_blank': True},
        }

    def validate(self, data):
        building_type = data.get('building_type')
        unit_number = data.get('unit_number')

        # Logic: If building is apartment, unit_number cannot be empty
        if building_type == 'apartment' and not unit_number:
            raise serializers.ValidationError({
                "unit_number": "Unit number is required for apartments."
            })
        
        return data


class SupportingDocumentWriteSerializer(serializers.ModelSerializer):

    class Meta:
        model = SupportingDocument
        fields = ["id_type", "front_file", "back_file"]

    def validate(self, attrs):
        id_type = attrs.get("id_type")
        front = attrs.get("front_file")
        back = attrs.get("back_file")

        if id_type == "greenbook":
            if not front:
                raise serializers.ValidationError("Greenbook requires a front file.")
            if back:
                raise serializers.ValidationError("Greenbook does not require a back file.")

        if id_type == "card":
            if not front or not back:
                raise serializers.ValidationError("Card requires both front and back files.")

        return attrs
    
class ProviderServiceCostPatchSerializer(serializers.Serializer):

    email = serializers.EmailField(write_only=True)
    service_id = serializers.IntegerField(write_only=True)

    base_price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        allow_null=True
    )
    negotiable = serializers.BooleanField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_base_price(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Base price cannot be negative.")
        return value

    def save(self):
        email = self.validated_data["email"]
        service_id = self.validated_data["service_id"]

        provider_service = ProviderService.objects.select_related(
            "provider", "cost_of_service"
        ).get(
            provider__sp_profile__email_address=email,
            service__service_id=service_id
        )

        # If cost already exists → update it
        if provider_service.cost_of_service:
            cost = provider_service.cost_of_service
            for field in ["base_price", "negotiable", "notes"]:
                if field in self.validated_data:
                    setattr(cost, field, self.validated_data[field])
            cost.save()
        else:
            # Create new cost object
            cost = CostOfService.objects.create(
                base_price=self.validated_data.get("base_price"),
                negotiable=self.validated_data.get("negotiable", True),
                notes=self.validated_data.get("notes")
            )
            provider_service.cost_of_service = cost
            provider_service.save()

        return provider_service


class SPAddressDocumentWriteSerializer(serializers.Serializer):
    email = serializers.EmailField(write_only=True)
    address = AddressWriteSerializer()
    id_type = serializers.ChoiceField(
        choices=[("greenbook", "Green Book"), ("card", "ID Card")],
        required=False
    )
    front_file = serializers.FileField(required=True)
    back_file = serializers.FileField(required=False, allow_null = True)

    def validate(self, attrs):
        id_type = attrs.get("id_type")
        front_file = attrs.get("front_file")
        back_file = attrs.get("back_file")

        if not id_type:
            raise serializers.ValidationError("ID type is required.")

        id_type = id_type.lower()

        if id_type == "greenbook":
            if not front_file:
                raise serializers.ValidationError("Greenbook requires a front file.")

        # If back_file is sent but empty, ignore it
            if back_file:
                if hasattr(back_file, "size") and back_file.size > 0:
                    raise serializers.ValidationError(
                    "Greenbook does not require a back file."
                )

        elif id_type == "card":
            if not front_file or not back_file:
                raise serializers.ValidationError(
                "Card requires both front and back files."
            )

        return attrs

    def create(self, validated_data):
        address_data = validated_data.pop("address")
        email = validated_data.pop("email")
        id_type = validated_data.pop("id_type", None)
        front_file = validated_data.pop("front_file", None)
        back_file = validated_data.pop("back_file")

        provider = ServiceProvider.objects.get(sp_profile__email_address=email)

        # Create Address
        address_obj = Address.objects.create(**address_data)
        provider.location = address_obj
        provider.save(update_fields=["location"])

        # Create Supporting Document if ID provided
        if id_type:
            SupportingDocument.objects.create(
                provider=provider,
                id_type=id_type.lower(),
                front_file=front_file,
                back_file=back_file
            )

        return provider

class CostOfServiceImageReadSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = CostOfServiceImage
        fields = [
            'id',
            'cost_of_service',
            'image',
            'image_url',
            'uploaded_at',
        ]

    def get_image_url(self, obj):
        request = self.context.get('request')
        if obj.image and request:
            return request.build_absolute_uri(obj.image.url)
        elif obj.image:
            return obj.image.url
        return None
    

class SPLoginSerializer(serializers.Serializer):
    email = serializers.EmailField(
        error_messages={"invalid": "Please enter a valid email address."}
    )
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")

        # 1. Check if user exists
        try:
            user = SPProfile.objects.get(email_address=email)
        except SPProfile.DoesNotExist:
            # Raising a non-field error for security (prevents email harvesting)
            # or keep it specific if that's your UX preference
            raise serializers.ValidationError({"email": "No account found with this email. Please register first."})

        # 2. Check Password
        if not check_password(password, user.password):
            raise serializers.ValidationError({"password": "The password you entered is incorrect."})

        # 3. Check Account Status
        if not user.is_active:
            raise serializers.ValidationError({"non_field_errors": "This account has been deactivated. Please contact support."})

        attrs["user"] = user
        return attrs
    


class ServiceWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ["service_name", "description", "service_group"]


class SPProfileReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = SPProfile
        # List all fields except password
        exclude = ['password']
        # OR, alternatively, explicitly include fields you want:
        # fields = ['id', 'email_address', 'mobile_number', 'is_profile_completed']
        read_only_fields = ['id', 'email_address', 'mobile_number', 'is_profile_completed']

class ServiceProviderSerializer(serializers.ModelSerializer):

    class Meta:
        model = ServiceProvider
        fields = [
            "rating",
            "full_name",
            "gender",
            "id_number",
            "sp_description",
            "dob",
            "is_active",
            "is_discoverable",
            "location",
            "services",
        ]
        read_only_fields = ["rating"]


class SPAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = Address
        fields = '__all__'

class ServiceCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceCategory
        fields = "__all__"
        


class ServiceGroupSerializer(serializers.ModelSerializer):
    category = ServiceCategorySerializer(read_only=True)
    class Meta:
        model = ServiceGroup
        fields = '__all__'

class ServiceReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        service_group = ServiceGroupSerializer
        fields = '__all__'  


class ServiceSerializer(serializers.ModelSerializer):
    service_group = ServiceGroupSerializer()
    active_provider_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Service
        fields = '__all__'  

    

    def create(self, validated_data):
        group_data = validated_data.pop('service_group')
        group, created = ServiceGroup.objects.get_or_create(
            group_id=group_data['group_id'],
            defaults={'name': group_data['name']}
        )
        return Service.objects.create(service_group=group, **validated_data)

class ServiceProviderReadSerializer(serializers.ModelSerializer):
    sp_profile = SPProfileReadSerializer()
    location = SPAddressSerializer()


    class Meta:
        model = ServiceProvider
        fields = '__all__'
class CostOfServiceReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = CostOfService
        fields = [
            "id",
            "base_price",
            "negotiable",
            "notes",
        ]

class ProviderSeviceSerializer(serializers.ModelSerializer):
    service = ServiceSerializer()
    provider = ServiceProviderReadSerializer()
    cost_of_service = CostOfServiceReadSerializer()
    class Meta:
        model = ProviderService
        
        
        fields = '__all__'

class ServiceProviderActiveSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceProvider
        fields = ["is_active"]

class CostOfServiceImageReadSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    class Meta:
        model = CostOfServiceImage
        fields = ['id', 'image', 'uploaded_at']

    def get_image(self, obj):
        request = self.context.get('request')
        if obj.image and hasattr(obj.image, 'url'):
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None
    
class CostOfServiceImageWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = CostOfServiceImage
        fields = ['cost_of_service', 'image']

    def validate(self, attrs):
        cost_of_service = attrs.get('cost_of_service')

        if not cost_of_service:
            raise serializers.ValidationError({
                "cost_of_service": "This field is required."
            })

        existing_count = CostOfServiceImage.objects.filter(
            cost_of_service=cost_of_service
        ).count()

        if existing_count >= 5:
            raise serializers.ValidationError(
                "Maximum of 5 images allowed per service."
            )

        return attrs

class ServiceProviderWriteSerializer(serializers.ModelSerializer):
    sp_profile = SPProfileReadSerializer()
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

