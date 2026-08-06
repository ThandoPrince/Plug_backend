from rest_framework import serializers
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
import re
from django.utils.html import strip_tags
from django.db.models import Q
from django.db import models
from rest_framework import serializers
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from datetime import date, timedelta
from api.clientsDB.services.client_ip_address_helper import get_client_ip
from api.clientsDB.services.sa_phone_number_helper import normalize_sa_mobile
from api.serviceProvidersDB.services.sa_id_validator import SouthAfricanIDValidator
from .models import CostOfServiceImage, DeviceToken, ProviderQualification, ProviderServiceAffidavit, SPProfile
from .models import CostOfService, ProviderService, SPLiveLocation, SPProfile, ServiceCategory, ServiceProvider, ServiceGroup, Service, Address, SupportingDocument


def validate_file_type(file_obj, allowed_extensions):
    """Validate uploaded file extension against allowed types."""
    if not file_obj:
        return

    filename = getattr(file_obj, 'name', None)
    if not filename:
        return

    filename = filename.lower()
    if not any(filename.endswith(ext) for ext in allowed_extensions):
        raise serializers.ValidationError(
            f"Invalid file type. Supported types: {', '.join(allowed_extensions)}"
        )


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
                "An account with these credentials already exists."
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
    push_token = serializers.CharField(
        write_only=True,
        required=True,
        source="fcm_token",
    )

    class Meta:
        model = DeviceToken
        fields = "__all__"
        extra_kwargs = {
            "service_provider": {"read_only": True},
            "fcm_token": {"required": False},
        }

    def create(self, validated_data):
        email = validated_data.pop("email").strip().lower()

        try:
            service_provider = SPProfile.objects.get(email_address=email)
        except SPProfile.DoesNotExist:
            raise serializers.ValidationError({
                "email": "No service provider found with this email."
            })

        token = validated_data["fcm_token"]

        # Remove this token from any other provider
        DeviceToken.objects.exclude(
            service_provider=service_provider
        ).filter(
            fcm_token=token
        ).delete()

        device_token, _ = DeviceToken.objects.update_or_create(
            service_provider=service_provider,
            defaults={
                **validated_data,
                "fcm_token": token,
            },
        )

        return device_token




class ServiceProviderPatchSerializer(serializers.ModelSerializer):

    full_name = serializers.CharField(required=True, allow_blank=False, max_length=120)
    id_number = serializers.CharField(required=True, min_length=13, max_length=13)
    dob = serializers.DateField(required=True)
    gender = serializers.CharField(required=True)
    sp_description = serializers.CharField(required=True, max_length=1000)
    location = serializers.CharField(required=False, allow_blank=True)
    profile_image = serializers.ImageField(required=True)

    class Meta:
        model = ServiceProvider
        fields = [
            "full_name",
            "gender",
            "id_number",
            "dob",
            "sp_description",
            "location",
            "profile_image",
        ]

    # -------------------------
    # SECURITY VALIDATION
    # -------------------------

    def _sanitize_text(self, value: str) -> str:
        """
        Removes HTML tags and trims dangerous input patterns.
        """
        if not value:
            return value

        value = value.strip()

        # Remove HTML tags
        value = strip_tags(value)

        # Block script-like patterns
        blocked_patterns = [
            r"<script.*?>",
            r"javascript:",
            r"onerror=",
            r"onload=",
        ]

        for pattern in blocked_patterns:
            if re.search(pattern, value, re.IGNORECASE):
                raise serializers.ValidationError("Invalid characters detected in input.")

        return value

    def validate_full_name(self, value):
        value = self._sanitize_text(value)

        # Only allow letters, spaces, apostrophes, hyphens
        if not re.match(r"^[a-zA-Z\s'\-]+$", value):
            raise serializers.ValidationError(
                "Full name contains invalid characters."
            )

        if len(value) < 2:
            raise serializers.ValidationError("Full name is too short.")

        return value

    def validate_sp_description(self, value):
        value = self._sanitize_text(value)

        # Prevent extremely long or spammy payloads
        if len(value.split()) > 300:
            raise serializers.ValidationError("Description is too long.")

        return value

    def validate_profile_image(self, image):
        """
        Protect against malicious uploads.
        """
        if not image:
            raise serializers.ValidationError("Image is required.")

        # File size limit (5MB example)
        if image.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("Image too large (max 5MB).")

        # MIME type validation
        valid_types = ["image/jpeg", "image/png", "image/webp"]
        if hasattr(image, "content_type") and image.content_type not in valid_types:
            raise serializers.ValidationError("Unsupported image type.")

        # Basic filename sanity check
        if ".." in image.name or "/" in image.name:
            raise serializers.ValidationError("Invalid file name.")

        return image

    # -------------------------
    # CROSS FIELD VALIDATION
    # -------------------------

    def validate_id_number(self, value):
        clean_id = str(value).strip()

        if not clean_id.isdigit() or len(clean_id) != 13:
            raise serializers.ValidationError("SA ID must be exactly 13 digits.")

        if ServiceProvider.objects.exclude(pk=self.instance.pk).filter(id_number=clean_id).exists():
            raise serializers.ValidationError("This ID number is already in use.")

        return clean_id

    def validate(self, attrs):

        attrs = super().validate(attrs)

        id_number = attrs.get("id_number")
        dob = attrs.get("dob")
        gender = attrs.get("gender")

        if not id_number:
            return attrs

        result = SouthAfricanIDValidator.validate(id_number)

        if not result["valid"]:
            raise serializers.ValidationError({
                "id_number": result["message"]
            })

        # DOB check
        if dob and dob != result["dob"]:
            raise serializers.ValidationError({
                "dob": "Date of birth does not match the South African ID number."
            })

        # Gender check
        if gender:
            gender_map = {
                "m": "Male",
                "male": "Male",
                "f": "Female",
                "female": "Female",
            }

            submitted_gender = gender_map.get(
                gender.strip().lower(),
                gender.strip().title()
            )

            if submitted_gender != result["gender"]:
                raise serializers.ValidationError({
                    "gender": "Gender does not match the South African ID number."
                })

        # Minimum age
        if dob:
            today = date.today()

            age = (
                today.year
                - dob.year
                - ((today.month, today.day) < (dob.month, dob.day))
            )

            if age < 18:
                raise serializers.ValidationError({
                    "dob": "You must be at least 18 years old to register."
                })

        return attrs

    @transaction.atomic
    def update(self, instance, validated_data):
        return super().update(instance, validated_data)
    

class ServiceProviderProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceProvider
        fields = [
            "profile_image",
            "sp_description",
        ]

    def validate_profile_image(self, value):
        if value is None:
            return value

        allowed_types = {
            "image/jpeg",
            "image/png",
            "image/webp",
        }

        if value.content_type not in allowed_types:
            raise serializers.ValidationError(
                "Only JPEG, PNG and WEBP images are allowed."
            )

        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError(
                "Image size must not exceed 5 MB."
            )

        return value

    def validate_sp_description(self, value):
        if value is None:
            return value

        value = value.strip()

        if not value:
            return ""

        if len(value) > 255:
            raise serializers.ValidationError(
                "Description cannot exceed 255 characters."
            )

        # Remove HTML tags
        value = strip_tags(value)

        # Reject control characters
        if re.search(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", value):
            raise serializers.ValidationError(
                "Description contains invalid characters."
            )

        return value

class ProviderServiceAffidavitSerializer(serializers.ModelSerializer):

    class Meta:
        model = ProviderServiceAffidavit
        fields = [
            "affidavit",
        ]

    def validate_affidavit(self, file):

        if not file:
            raise serializers.ValidationError(
                "Please upload an affidavit."
            )

        # Max 10 MB
        if file.size > 10 * 1024 * 1024:
            raise serializers.ValidationError(
                "Affidavit must not exceed 10MB."
            )

        allowed = [
            "application/pdf",
            "image/jpeg",
            "image/png",
        ]

        if (
            hasattr(file, "content_type")
            and file.content_type not in allowed
        ):
            raise serializers.ValidationError(
                "Only PDF, JPG and PNG files are allowed."
            )

        return file
    


class ProviderQualificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProviderQualification
        fields = (
            "document_type",
            "title",
            "issuing_body",
            "issue_date",
            "expiry_date",
            "document",
        )

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Title is required.")
        return value

    def validate_issue_date(self, value):
        if value and value > timezone.localdate():
            raise serializers.ValidationError(
                "Issue date cannot be in the future."
            )
        return value

    def validate(self, attrs):
        issue_date = attrs.get("issue_date")
        expiry_date = attrs.get("expiry_date")

        if (
            issue_date
            and expiry_date
            and expiry_date < issue_date
        ):
            raise serializers.ValidationError(
                {
                    "expiry_date": (
                        "Expiry date cannot be before the issue date."
                    )
                }
            )

        return attrs

    def validate_document(self, value):
        max_size = 10 * 1024 * 1024  # 10MB

        if value.size > max_size:
            raise serializers.ValidationError(
                "Document must be smaller than 10MB."
            )

        allowed_extensions = {
            ".pdf",
            ".jpg",
            ".jpeg",
            ".png",
            ".doc",
            ".docx",
        }

        import os

        extension = os.path.splitext(value.name)[1].lower()

        if extension not in allowed_extensions:
            raise serializers.ValidationError(
                "Only PDF, Word documents and images are allowed."
            )

        return value
    

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
    address = AddressWriteSerializer()

    id_type = serializers.ChoiceField(
        choices=[
            ("greenbook", "Green Book"),
            ("card", "ID Card"),
        ],
        required=False,
    )

    front_file = serializers.FileField(required=True)
    back_file = serializers.FileField(required=False, allow_null=True)
    liveness_video = serializers.FileField(required=False, allow_null=True)

    def validate(self, attrs):
        id_type = attrs.get("id_type")
        front_file = attrs.get("front_file")
        back_file = attrs.get("back_file")
        liveness_video = attrs.get("liveness_video")

        if not id_type:
            raise serializers.ValidationError("ID type is required.")

        id_type = id_type.lower()

        validate_file_type(front_file, [".jpg", ".jpeg", ".png"])
        validate_file_type(back_file, [".jpg", ".jpeg", ".png"])
        validate_file_type(liveness_video, [".mp4", ".mov", ".avi"])

        if id_type == "greenbook":
            if not front_file:
                raise serializers.ValidationError(
                    "Green Book requires a front file."
                )

            if back_file and back_file.size > 0:
                raise serializers.ValidationError(
                    "Green Book does not require a back file."
                )

        elif id_type == "card":
            if not front_file or not back_file:
                raise serializers.ValidationError(
                    "ID Card requires both front and back files."
                )

        if not liveness_video:
            raise serializers.ValidationError(
                "A liveness video is required."
            )

        if liveness_video.size > 25 * 1024 * 1024:
            raise serializers.ValidationError(
                "Liveness video must be less than 10MB."
            )

        if liveness_video.size < 50 * 1024:
            raise serializers.ValidationError(
                "Liveness video is too small or invalid."
            )

        return attrs

    def create(self, validated_data):
        address_data = validated_data.pop("address")

        id_type = validated_data.pop("id_type")
        front_file = validated_data.pop("front_file")
        back_file = validated_data.pop("back_file", None)
        liveness_video = validated_data.pop("liveness_video")

        sp_profile = validated_data.pop("sp_profile")

        provider = ServiceProvider.objects.select_related(
            "sp_profile"
        ).get(
            sp_profile=sp_profile,
        )

        address = Address.objects.create(**address_data)

        provider.location = address
        provider.save(update_fields=["location"])

        document = SupportingDocument.objects.create(
            provider=provider,
            id_type=id_type.lower(),
            front_file=front_file,
            back_file=back_file,
            liveness_video=liveness_video,
            verification_status="processing",
        )

        return {
            "provider": provider,
            "document": document,
        }

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

    identifier = serializers.CharField(required=True, max_length=100)
    password = serializers.CharField(write_only=True, required=True, min_length=6)

    def validate(self, data):

        request = self.context.get("request")

        # -------------------------------------------------
        # 1. RAW INPUT
        # -------------------------------------------------
        raw_identifier = data.get("identifier", "").strip()
        password = data.get("password")

        if not raw_identifier:
            raise serializers.ValidationError({
                "non_field_errors": ["Invalid credentials."]
            })

        # -------------------------------------------------
        # 2. IDENTITY TYPE DETECTION
        # -------------------------------------------------
        is_email = re.match(
            r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
            raw_identifier
        ) is not None

        normalized_phone = None

        if not is_email:
            normalized_phone = normalize_sa_mobile(raw_identifier)

        # -------------------------------------------------
        # 3. BUILD SAFE QUERY
        # -------------------------------------------------
        query = Q()

        if is_email:
            query = Q(email_address__iexact=raw_identifier)

        elif normalized_phone:
            query = Q(mobile_number=normalized_phone)

        else:
            raise serializers.ValidationError({
                "non_field_errors": ["Invalid credentials."]
            })

        user = SPProfile.objects.filter(query).first()

        # -------------------------------------------------
        # 4. GENERIC FAILURE
        # -------------------------------------------------
        if not user:
            raise serializers.ValidationError({
                "non_field_errors": ["Invalid credentials."]
            })

        now = timezone.now()

        # -------------------------------------------------
        # 5. ACCOUNT LOCK CHECK
        # -------------------------------------------------
        if (
            user.account_locked_until and
            user.account_locked_until > now
        ):

            remaining_minutes = max(
                1,
                int(
                    (user.account_locked_until - now).total_seconds() / 60
                )
            )

            raise serializers.ValidationError({
                "non_field_errors": [
                    f"Account temporarily locked. Try again in {remaining_minutes} minute(s)."
                ]
            })

        # -------------------------------------------------
        # 6. ACCOUNT STATUS
        # -------------------------------------------------
        if not user.is_active:
            raise serializers.ValidationError({
                "non_field_errors": [
                    "This account has been deactivated. Please contact support."
                ]
            })

        # -------------------------------------------------
        # 7. PASSWORD CHECK
        # -------------------------------------------------
        if not check_password(password, user.password):

            user.failed_login_attempts = (
                user.failed_login_attempts or 0
            ) + 1

            user.total_failed_login_attempts = (
                user.total_failed_login_attempts or 0
            ) + 1

            attempts = user.failed_login_attempts

            if attempts >= 15:
                lock_duration = timedelta(hours=24)

            elif attempts >= 10:
                lock_duration = timedelta(hours=1)

            elif attempts >= 5:
                lock_duration = timedelta(minutes=15)

            else:
                lock_duration = None

            if lock_duration:
                user.account_locked_until = now + lock_duration

            user.save(update_fields=[
                "failed_login_attempts",
                "total_failed_login_attempts",
                "account_locked_until",
            ])

            raise serializers.ValidationError({
                "non_field_errors": ["Invalid credentials."]
            })

        # -------------------------------------------------
        # 8. SUCCESS RESET
        # -------------------------------------------------
        user.failed_login_attempts = 0
        user.account_locked_until = None
        user.last_login_at = now

        if request:
            user.last_login_ip = get_client_ip(request)

        user.save(update_fields=[
            "failed_login_attempts",
            "account_locked_until",
            "last_login_at",
            "last_login_ip",
        ])

        data["user"] = user
        return data

class ServiceWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = ["service_name", "description", "service_group"]

class SPProfileMyReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = SPProfile
        # List all fields except password
        exclude = ['password', 'mfa_enabled','mfa_secret','failed_login_attempts','total_failed_login_attempts','account_locked_until','updated_at','date_created','last_login_at','last_login_ip']
        # OR, alternatively, explicitly include fields you want:
        # fields = ['id', 'email_address', 'mobile_number', 'is_profile_completed']
        read_only_fields = ['id', 'email_address', 'mobile_number', 'is_profile_completed','id']


class SPProfileReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = SPProfile
        # List all fields except password
        exclude = ['password']
        # OR, alternatively, explicitly include fields you want:
        # fields = ['id', 'email_address', 'mobile_number', 'is_profile_completed']
        read_only_fields = ['id', 'email_address', 'mobile_number', 'is_profile_completed','id']

class ClientSPProfileReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = SPProfile
        # List all fields except password
        exclude = ['password', 'email_address', 'mobile_number','failed_login_attempts','mfa_secret','mfa_enabled','total_failed_login_attempts','account_locked_until','last_login_at','last_login_ip']
        # OR, alternatively, explicitly include fields you want:
        # fields = ['id', 'email_address', 'mobile_number', 'is_profile_completed']
        read_only_fields = [ 'is_profile_completed', 'id']

class ServiceProviderSerializer(serializers.ModelSerializer):

    sp_profile = SPProfileReadSerializer()

    class Meta:
        model = ServiceProvider
        fields = '__all__'
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

class ClientServiceSerializer(serializers.ModelSerializer):
    
    

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





class SPCostOfServiceImageReadSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = CostOfServiceImage
        fields = [
            "id",
            "image_url",
            "uploaded_at",
        ]

    def get_image_url(self, obj):
        request = self.context.get("request")

        if obj.image:
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url

        return None

class ProviderQualificationReadSerializer(serializers.ModelSerializer):
    document_url = serializers.SerializerMethodField()

    class Meta:
        model = ProviderQualification
        fields = [
            "id",
            "provider_service",
            "document_type",
            "title",
            "issuing_body",
            "issue_date",
            "expiry_date",
            "document_url",
            "uploaded_at",
        ]

    def get_document_url(self, obj):
        request = self.context.get("request")

        if obj.document:
            return request.build_absolute_uri(obj.document.url)

        return None

class ServiceProviderReadSerializer(serializers.ModelSerializer):
    sp_profile = SPProfileMyReadSerializer()
  

    class Meta:
        model = ServiceProvider
        exclude = ['id_number']


class SPProfileLiveLocationSerializer(serializers.ModelSerializer):

    class Meta:
        model = SPLiveLocation
        fields = [
            "suburb",
            "city",
            "province",
            "updated_at",
        ]

class ServiceProviderMyReadSerializer(serializers.ModelSerializer):
    sp_profile = SPProfileMyReadSerializer()
    live_location = SPProfileLiveLocationSerializer(
        read_only=True,
    )
    location = SPAddressSerializer(read_only=True)

  

    class Meta:
        model = ServiceProvider
        exclude = ['id_number']









class ClientServiceProviderReadSerializer(serializers.ModelSerializer):
    sp_profile = ClientSPProfileReadSerializer()

    class Meta:
        model = ServiceProvider
        exclude = ['id_number']
class CostOfServiceReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = CostOfService
        fields = [
            "id",
            "base_price",
            "negotiable",
            "notes",
        ]

class SPProviderSeviceSerializer(serializers.ModelSerializer):
    service = ServiceSerializer()
    provider = ServiceProviderReadSerializer()
    cost_of_service = CostOfServiceReadSerializer()
    completed_orders = serializers.IntegerField(read_only=True)
    average_rating = serializers.FloatField(read_only=True)
    class Meta:
        model = ProviderService
        fields = '__all__'

class UpdateCostOfServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = CostOfService
        fields = [
            "base_price",
            "notes",
        ]

    def validate_base_price(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError(
                "Base price cannot be negative."
            )
        return value

class DeleteProviderQualificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProviderQualification
        fields = ("id",)

class CostOfServiceImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = CostOfServiceImage
        fields = [
            "id",
            "image",
            "uploaded_at",
        ]
        read_only_fields = [
            "id",
            "uploaded_at",
        ]

    def validate_image(self, value):
        max_size = 10 * 1024 * 1024  # 10MB

        if value.size > max_size:
            raise serializers.ValidationError(
                "Image must not exceed 10MB."
            )

        return value

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
    # Read-only field to catch the calculated distance from our query annotation
    distance_km = serializers.FloatField(read_only=True, required=False)
    
    # Optional: Pulling explicit provider profile fields to save extra Flutter API hits
    provider_name = serializers.CharField(source='provider.full_name', read_only=True)
    is_verified = serializers.BooleanField(source='provider.is_verified', read_only=True)

    class Meta:
        model = SPLiveLocation
        fields = '__all__'

class SPLiveLocationUpdateSerializer(serializers.Serializer):
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)

