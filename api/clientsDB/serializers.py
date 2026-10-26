from disposable_email_domains import blocklist
from django.core.files.storage import default_storage
from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from api.clientsDB.services.client_ip_address_helper import get_client_ip
from api.clientsDB.services.sa_phone_number_helper import normalize_sa_mobile
from api.serviceProvidersDB.services.sa_id_validator import SouthAfricanIDValidator
from .models.models import AddressSuperUserVerification, ClientAuth, Address, ClientDetails, ClientAddress, ClientLoginHistory, ClientNotification, DeviceToken
import re
from PIL import Image, UnidentifiedImageError
from django.db.models import Q
from django.contrib.auth.hashers import check_password
import phonenumbers
from datetime import date, timedelta
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


    


class ClientOTPVerifySerializer(serializers.Serializer):
    

    otp = serializers.CharField(
        required=True,
        min_length=6,
        max_length=6,
        trim_whitespace=True,
        write_only=True
    )

    def validate_otp(self, value):
        if not value.isdigit():
            raise serializers.ValidationError(
                "Invalid OTP."
            )

        return value

    
    

class ClientProfileBookingSerializer(serializers.ModelSerializer):
    

    class Meta:
        model = ClientAuth
        fields = ['id']
        




class ClientAuthReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientAuth
        fields = [
            'id',
            'email_address',
            'mobile_number',
            'is_profile_completed',
        ]

class DeleteAccountSerializer(serializers.Serializer):
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    confirmation = serializers.CharField(write_only=True)

    def validate_confirmation(self, value):
        if value.strip().upper() != "DELETE":
            raise serializers.ValidationError('Type "DELETE" to confirm.')
        return value

    def validate(self, attrs):
        client = self.context["client"]
        if not check_password(attrs["password"], client.password):
            raise serializers.ValidationError({"password": "Incorrect password."})
        return attrs


class ResetPasswordWithOTPSerializer(serializers.Serializer):
    new_password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
        min_length=8,
        max_length=128,
    )

 

    def validate_new_password(self, value):
        errors = []

        if len(value) < 8:
            errors.append(
                "Password must be at least 8 characters."
            )

        if not re.search(r"[A-Z]", value):
            errors.append(
                "Password must contain at least one uppercase letter."
            )

        if not re.search(r"[a-z]", value):
            errors.append(
                "Password must contain at least one lowercase letter."
            )

        if not re.search(r"\d", value):
            errors.append(
                "Password must contain at least one digit."
            )

        if errors:
            raise serializers.ValidationError(errors)

        return value

    def validate(self, attrs):
        client = self.context["client"]

        new_password = attrs["new_password"]
     

        

        if check_password(new_password, client.password):
            raise serializers.ValidationError({
                "new_password":
                    "New password must be different from your current password."
            })

        # Prevent email local-part from being used in the password
        local_part = client.email_address.split("@")[0].lower()

        if len(local_part) >= 4 and local_part in new_password.lower():
            raise serializers.ValidationError({
                "new_password":
                    "Password must not contain your email address."
            })

        # Django password validators
        try:
            validate_password(
                new_password,
                user=client,
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError({
                "new_password": list(exc.messages)
            })

        return attrs

    
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
            raise serializers.ValidationError("This email address is invalid.")

        domain = value.rsplit('@', 1)[-1]
        if domain in blocklist:
            raise serializers.ValidationError(
                "This email address is invalid."
            )
        return value

    def validate_mobile_number(self, value):

        normalized = normalize_sa_mobile(value)

        if not normalized:
            raise serializers.ValidationError(
                "Enter a valid South African mobile number."
            )

        try:
            number = phonenumbers.parse(
                normalized,
                None
            )

            if not phonenumbers.is_valid_number(number):
                raise serializers.ValidationError(
                    "Enter a valid South African mobile number."
                )

        except phonenumbers.NumberParseException:
            raise serializers.ValidationError(
                "Invalid phone number format."
            )

        if ClientAuth.objects.filter(
            mobile_number=normalized
        ).exists():
            raise serializers.ValidationError(
                "Enter a valid South African mobile number."
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

class ClientSavedAddressSerializer(serializers.ModelSerializer):
    

    class Meta:
        model = Address
        fields = '__all__'

 
class AddressSerializer(serializers.ModelSerializer):


    class Meta:
        model = Address
        fields = '__all__'


    
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
    
class ClientBookingReadSerializer(serializers.ModelSerializer):
    client_profile = ClientProfileBookingSerializer(read_only=True)  # Lock nested profiles from modifications here
    client_pp = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = ClientDetails
        fields  = [
            'first_name', 
            'last_name', 
            'date_of_birth', 
            'client_profile', 
            'rating', 
            'client_pp'
        ]

class ClientSerializer(serializers.ModelSerializer):
    client_profile = ClientProfileSerializer(read_only=True)
    client_pp = serializers.ImageField(required=False, allow_null=True)

    MAX_PP_BYTES = 5 * 1024 * 1024
    ALLOWED_PP_TYPES = {"image/jpeg", "image/png", "image/webp"}
    NULL_STRINGS = {"null", "none", ""}
    CANNOT_CLEAR = ("first_name", "last_name", "date_of_birth")

    class Meta:
        model = ClientDetails
 
        fields = [
            "client_ID",
            "client_profile",
            "first_name",
            "last_name",
            "date_of_birth",
            "client_pp",
     
        ]
        read_only_fields = ["id", "client_profile"]

    def to_internal_value(self, data):
        # Plain dict, NOT data.copy(): copying a QueryDict deep-copies
        # uploaded files, which fails for large temp-file uploads.
        cleaned = {key: data.get(key) for key in data.keys()}

        for field in ("date_of_birth", "client_pp"):
            value = cleaned.get(field)
            if isinstance(value, str) and value.strip().lower() in self.NULL_STRINGS:
                cleaned[field] = None

        return super().to_internal_value(cleaned)

    def validate_date_of_birth(self, value):
        if value is None:
            return value

        today = timezone.localdate()

        if value > today:
            raise serializers.ValidationError("Date of birth cannot be in the future.")

        age = today.year - value.year - ((today.month, today.day) < (value.month, value.day))

        if age < 18:
            raise serializers.ValidationError("Client must be at least 18 years or older.")
        if age > 120:
            raise serializers.ValidationError("Please enter a valid date of birth.")

        return value

    def validate_client_pp(self, value):
        if value is None:
            return value

        if value.size > self.MAX_PP_BYTES:
            raise serializers.ValidationError("Profile photo must be 5 MB or smaller.")

        # DRF's ImageField has already decoded the file with Pillow, so
        # content_type reflects the real format, not the filename.
        if getattr(value, "content_type", None) not in self.ALLOWED_PP_TYPES:
            raise serializers.ValidationError("Use a JPEG, PNG or WebP image.")

        return value

    def validate(self, attrs):
        # Once a required field has a value, it can be changed but not cleared.
        if self.instance is not None:
            for field in self.CANNOT_CLEAR:
                if field in attrs and not attrs[field] and getattr(self.instance, field, None):
                    raise serializers.ValidationError({field: "This field cannot be cleared."})
        return attrs

    def update(self, instance, validated_data):
        old_name = instance.client_pp.name if instance.client_pp else None

        instance = super().update(instance, validated_data)

        # Delete the replaced photo after the transaction commits, so a
        # rollback never leaves the row pointing at a deleted file.
        if "client_pp" in validated_data and old_name:
            new_name = instance.client_pp.name if instance.client_pp else None
            if new_name != old_name:
                transaction.on_commit(lambda: default_storage.delete(old_name))

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
    # Map the incoming JSON key 'push_token' to the database column 'fcm_token'
    push_token = serializers.CharField(source='fcm_token', max_length=512)

    class Meta:
        model = DeviceToken
        fields = [
            'push_token', 
            'device_type', 
            'device_name', 
            'os_version', 
            'app_version', 
            'provider'
        ]

    def validate(self, attrs):
        # Fallback to defaults if provider or device_type aren't explicitly passed
        if 'provider' not in attrs:
            attrs['provider'] = 'firebase'
        return attrs
    
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


from rest_framework import serializers
from django.db import transaction

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

    # -------------------------------------------------
    # CLEAN VALIDATION LAYER (NO DB SIDE EFFECTS)
    # -------------------------------------------------
    def validate(self, attrs):
        address_data = attrs.get("address", {})
        building_type = address_data.get("building_type", "house")
        unit_number = address_data.get("unit_number")

        if unit_number:
            unit_number = str(unit_number).strip()

        errors = {}

        # ---- Business rules
        if building_type == "apartment" and not unit_number:
            errors["unit_number"] = ["Unit number is required for apartments."]

        if building_type == "house" and unit_number:
            errors["unit_number"] = ["Houses cannot have a unit number."]

        if errors:
            raise serializers.ValidationError({"address": errors})

        attrs["address"]["unit_number"] = unit_number or ""
        return attrs

    # -------------------------------------------------
    # CREATE LAYER (DB OPERATIONS ONLY)
    # -------------------------------------------------
    @transaction.atomic
    def create(self, validated_data):
        address_data = validated_data.pop("address")
        client = self.context["client"]

        unit_number = address_data.get("unit_number") or ""

        address = Address.objects.filter(
            place_id=address_data.get("place_id"),
            unit_number=unit_number
        ).first()

        if not address:
            address = Address.objects.create(
                place_id=address_data.get("place_id"),
                street_number=address_data.get("street_number"),
                route=address_data.get("route"),
                locality=address_data.get("locality"),
                administrative_area_level_1=address_data.get("administrative_area_level_1"),
                postal_code=address_data.get("postal_code"),
                country=address_data.get("country"),
                latitude=address_data.get("latitude"),
                longitude=address_data.get("longitude"),
                building_type=address_data.get("building_type", "house"),
                unit_number=unit_number,
            )

        # ---- Duplicate prevention (STRUCTURED ERROR)
        if ClientAddress.objects.filter(client=client, address=address).exists():
            raise serializers.ValidationError({
                "non_field_errors": [
                    "You have already added this address."
                ]
            })

        return ClientAddress.objects.create(
            client=client,
            address=address,
            **validated_data
        )





class ClientAddressDeactivateSerializer(serializers.ModelSerializer):

    class Meta:
        model = ClientAddress
        fields = ["id"]

    def validate(self, attrs):
        client_address = self.instance

        if client_address.is_default:
            raise serializers.ValidationError(
                "The default address cannot be deactivated."
            )

        if not client_address.is_active:
            raise serializers.ValidationError(
                "This address is already inactive."
            )

        return attrs

    def update(self, instance, validated_data):
        instance.is_active = False
        instance.is_super_user = False
        instance.save(
            update_fields=["is_active", "is_super_user"]
        )
        return instance
    

class ClientAddressSerializerr(serializers.ModelSerializer):
    
    # Lift the verification state from the Address object up to the root ClientAddress map
    is_verified = serializers.ReadOnlyField(source='address.is_verified')

    class Meta:
        model = ClientAddress
        fields = '__all__'
    

class AddressVerificationCreateSerializer(serializers.ModelSerializer):

    client_address = serializers.PrimaryKeyRelatedField(
        queryset=ClientAddress.objects.all()
    )

    class Meta:
        model = AddressSuperUserVerification
        fields = [
            "client_address",
            "id_number",
            "proof_of_residence",
            "id_document",
            "liveness_video",
        ]

    def validate(self, attrs):
        errors = {}

        client_address = attrs.get("client_address")
        id_number = attrs.get("id_number")

        # -------------------------------------------------
        # CLIENT ADDRESS VALIDATION
        # -------------------------------------------------
        if not client_address:
            errors["client_address"] = [
                "Client address is required."
            ]

        # -------------------------------------------------
        # SOUTH AFRICAN ID NUMBER VALIDATION
        # -------------------------------------------------
        id_validation = None

        if not id_number:
            errors["id_number"] = [
                "ID number is required."
            ]
        else:
            id_number = str(id_number).strip()

            id_validation = SouthAfricanIDValidator.validate(
                id_number
            )

            if not id_validation["valid"]:
                errors["id_number"] = [
                    id_validation["message"]
                ]

        # -------------------------------------------------
        # DATE OF BIRTH VALIDATION
        # -------------------------------------------------
        if (
            client_address
            and id_validation
            and id_validation["valid"]
        ):
            client = client_address.client
            client_dob = client.date_of_birth
            id_dob = id_validation["dob"]

            if not client_dob:
                errors["id_number"] = [
                    "Your date of birth is not available on your profile. "
                    "Please update your profile before completing verification."
                ]

            elif client_dob != id_dob:
                errors["id_number"] = [
                    "The date of birth on your ID number does not match "
                    "the date of birth on your profile."
                ]

        # -------------------------------------------------
        # EXISTING VERIFICATION
        # -------------------------------------------------
        if client_address:
            existing = getattr(
                client_address,
                "verification_request",
                None,
            )

            if existing:
                if (
                    existing.status
                    == AddressSuperUserVerification.STATUS_APPROVED
                ):
                    errors["client_address"] = [
                        "This address has already been verified."
                    ]

                # Pending/rejected submissions can be resubmitted.

        # -------------------------------------------------
        # REQUIRED FILE VALIDATION
        # -------------------------------------------------
        if not attrs.get("proof_of_residence"):
            errors["proof_of_residence"] = [
                "Proof of residence document is required."
            ]

        if not attrs.get("id_document"):
            errors["id_document"] = [
                "ID document is required."
            ]

        if not attrs.get("liveness_video"):
            errors["liveness_video"] = [
                "Liveness video is required."
            ]

        # -------------------------------------------------
        # RETURN VALIDATION ERRORS
        # -------------------------------------------------
        if errors:
            raise serializers.ValidationError(errors)

        # Store cleaned ID number.
        attrs["id_number"] = id_number

        return attrs

    def create(self, validated_data):
        client_address = validated_data["client_address"]

        existing = getattr(
            client_address,
            "verification_request",
            None,
        )

        # -------------------------------------------------
        # EXISTING VERIFICATION
        # -------------------------------------------------
        if existing:
            existing.id_number = validated_data["id_number"]

            existing.proof_of_residence = (
                validated_data["proof_of_residence"]
            )

            existing.id_document = (
                validated_data["id_document"]
            )

            existing.liveness_video = (
                validated_data["liveness_video"]
            )

            existing.status = (
                AddressSuperUserVerification.STATUS_PENDING
            )

            existing.reviewed_at = None
            existing.admin_notes = None
            existing.submitted_at = timezone.now()

            existing.save()

            return existing

        # -------------------------------------------------
        # FIRST SUBMISSION
        # -------------------------------------------------
        return AddressSuperUserVerification.objects.create(
            **validated_data
        )
        
    
class ClientLoginSerializer(serializers.Serializer):

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
        is_email = re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", raw_identifier) is not None
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
            # Prevent invalid identity injection
            raise serializers.ValidationError({
                "non_field_errors": ["Invalid credentials."]
            })

        user = ClientAuth.objects.filter(query).first()

        # -------------------------------------------------
        # 4. GENERIC FAILURE (NO ENUMERATION)
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
                int((user.account_locked_until - now).total_seconds() / 60)
            )

            raise serializers.ValidationError({
                "non_field_errors": [
                    f"Account temporarily locked. Try again in {remaining_minutes} minute(s)."
                ]
            })

        # -------------------------------------------------
        # 6. PASSWORD CHECK
        # -------------------------------------------------
        if not check_password(password, user.password):

            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            user.total_failed_login_attempts = (user.total_failed_login_attempts or 0) + 1

            attempts = user.failed_login_attempts
            MAX_ATTEMPTS = 5

            remaining_attempts = max(0, MAX_ATTEMPTS - attempts)

            # Progressive lock strategy
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
                "account_locked_until"
            ])

            raise serializers.ValidationError({
                "non_field_errors": ["Invalid credentials."],
                
            })

        # -------------------------------------------------
        # 7. SUCCESS STATE RESET
        # -------------------------------------------------
        user.failed_login_attempts = 0
        user.account_locked_until = None
        user.last_login_at = timezone.now()

        if request:
            user.last_login_ip = get_client_ip(request)

        user.save(update_fields=[
            "failed_login_attempts",
            "account_locked_until",
            "last_login_at",
            "last_login_ip"
        ])

        data["user"] = user
        return data
    

class ClientViewSerializer(serializers.ModelSerializer): 

    class Meta:
        model = ClientDetails
        fields = ['first_name', 'last_name', 'client_pp']

class HouseholdMemberSerializer(serializers.ModelSerializer):
    client = ClientViewSerializer()

    class Meta:
        model = ClientAddress
        fields =  '__all__'
    
    
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




class ClientProfileSecurityMixin:
    MAX_PP_BYTES = 5 * 1024 * 1024
    ALLOWED_PP_FORMATS = {"JPEG", "PNG", "WEBP"}
    NULL_STRINGS = {"null", "none", ""}
    CANNOT_CLEAR = ("first_name", "last_name", "date_of_birth")

    def to_internal_value(self, data):
        # Avoid deep-copying QueryDict objects containing uploaded files.
        cleaned = {key: data.get(key) for key in data.keys()}

        for field in ("date_of_birth", "client_pp"):
            value = cleaned.get(field)

            if isinstance(value, str) and value.strip().lower() in self.NULL_STRINGS:
                cleaned[field] = None

        return super().to_internal_value(cleaned)

    def validate_date_of_birth(self, value):
        if value is None:
            return value

        today = timezone.localdate()

        if value > today:
            raise serializers.ValidationError(
                "Date of birth cannot be in the future."
            )

        age = (
            today.year
            - value.year
            - ((today.month, today.day) < (value.month, value.day))
        )

        if age < 18:
            raise serializers.ValidationError(
                "You must be at least 18 years old to use Plug."
            )

        if age > 120:
            raise serializers.ValidationError(
                "Please enter a valid date of birth."
            )

        return value

    def validate_client_pp(self, value):
        if value is None:
            return value

        if value.size > self.MAX_PP_BYTES:
            raise serializers.ValidationError(
                "Profile photo must be 5 MB or smaller."
            )

        # Check the decoded image format, not just the supplied MIME type
        # or filename extension.
        try:
            value.seek(0)

            with Image.open(value) as image:
                image_format = image.format
                image.verify()

            value.seek(0)

        except (UnidentifiedImageError, OSError, ValueError):
            raise serializers.ValidationError(
                "Upload a valid JPEG, PNG or WebP image."
            )

        if image_format not in self.ALLOWED_PP_FORMATS:
            raise serializers.ValidationError(
                "Use a JPEG, PNG or WebP image."
            )

        return value

    def validate(self, attrs):
        if self.instance is not None:
            for field in self.CANNOT_CLEAR:
                if (
                    field in attrs
                    and not attrs[field]
                    and getattr(self.instance, field, None)
                ):
                    raise serializers.ValidationError({
                        field: "This field cannot be cleared."
                    })

        return attrs

    def update(self, instance, validated_data):
        old_name = (
            instance.client_pp.name
            if instance.client_pp
            else None
        )

        instance = super().update(instance, validated_data)

        # Delete the old file only after the database transaction commits.
        if "client_pp" in validated_data and old_name:
            new_name = (
                instance.client_pp.name
                if instance.client_pp
                else None
            )

            if new_name != old_name:
                transaction.on_commit(
                    lambda: default_storage.delete(old_name)
                )

        return instance



    

class ClientProfileAppUpdateSerializer(
    ClientProfileSecurityMixin,
    serializers.ModelSerializer,
):
    class Meta:
        model = ClientDetails
        fields = [
            "first_name",
            "last_name",
            "date_of_birth",
            "client_pp",
            "last_updated",
        ]

        read_only_fields = ["last_updated"]

    


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
    address_type = serializers.CharField(
        source="clientaddress.address_type",
        read_only=True,
    )
    is_owner = serializers.BooleanField(
        source="clientaddress.is_owner",
        read_only=True,
    )
    formatted_address = serializers.SerializerMethodField()

    class Meta:
        model = Address
        fields = [
            "id",
            "latitude",
            "longitude",
            "place_id",
            "is_verified",
            "street_number",
            "route",
            "locality",
            "administrative_area_level_1",
            "formatted_address",
            "country",
            "postal_code",
            "address_type",
            "is_owner",
        ]

    def get_formatted_address(self, obj):
        return ", ".join(
            filter(
                None,
                [
                    obj.route,
                    obj.locality,
                    obj.administrative_area_level_1,
                ],
            )
        )

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