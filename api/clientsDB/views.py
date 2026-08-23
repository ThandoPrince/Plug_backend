import re
import secrets
from sqlite3 import IntegrityError
import requests
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
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
from api.clientsDB.services.address_verify_service import AIAddressVerificationClient
from api.clientsDB.services.client_history_model_helper import create_client_address_history
from api.clientsDB.services.client_ip_address_helper import get_client_ip, get_device_info
from api.clientsDB.services.jwt_client_authentication import ClientJWTAuthentication
from api.clientsDB.services.otp_service import create_client_otp, create_login_otp, hash_otp
from api.clientsDB.services.otp_tasks import OTPCooldownError, send_client_login_otp_email, send_client_otp_email
from api.clientsDB.services.sa_phone_number_helper import normalize_sa_mobile
from plug_backend.helpers.auth_helpers import get_client_auth, get_client_details
from plug_backend.throttles import AuthThrottle, ClientOTPThrottle, ClientRegistrationThrottle, ProfileWriteThrottle, RegisterThrottle, UserReadThrottle
from plug_backend.utils.client_jwt_helper import generate_client_tokens
from django.db.models import Q
from django.utils import timezone
from .models.models import ClientAddressHistory, ClientAuth, ClientDetails, Address, ClientAddress, ClientLoginHistory, ClientNotification, ClientOTP, ClientRegistrationHistory, DeviceToken 
from .serializers import AddressClaimSerializer, AddressOnlySerializer, AddressVerificationCreateSerializer, ClientAddressDeactivateSerializer, ClientAddressNoDuplicatesSerializer, AddressSerializer, ClientAddressSerializerr, ClientAddressWriteSerializer, ClientAuthReadSerializer, ClientLoginSerializer, ClientOTPVerifySerializer, ClientProfileAppUpdateSerializer, ClientProfileSerializer, ClientRegisterSerializer, ClientSavedAddressSerializer, ClientSerializer, ClientAddressSerializer, DefaultAddressSerializer, DeviceTokenWriteSerializer, HouseholdMemberSerializer
from django.contrib.auth.hashers import check_password, make_password


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def reset_client_password(request):

    try:
        email = request.data.get("email")
        mobile_number = request.data.get("mobile_number")
        new_password = request.data.get("new_password")

        # ------------------------
        # Basic validation
        # ------------------------
        if not new_password:
            return Response(
                {"error": "new_password is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not email and not mobile_number:
            return Response(
                {"error": "Provide email or mobile_number"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ------------------------
        # Normalize inputs
        # ------------------------
        if email:
            email = email.strip().lower()

        if mobile_number:
            mobile_number = normalize_sa_mobile(mobile_number)

            if not mobile_number:
                return Response(
                    {"error": "Invalid mobile number format"},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # ------------------------
        # Password complexity rules
        # ------------------------
        errors = []

        if len(new_password) < 8:
            errors.append("Password must be at least 8 characters.")

        if not re.search(r'[A-Z]', new_password):
            errors.append("Password must contain at least one uppercase letter.")

        if not re.search(r'[a-z]', new_password):
            errors.append("Password must contain at least one lowercase letter.")

        if not re.search(r'\d', new_password):
            errors.append("Password must contain at least one digit.")

        if errors:
            return Response(
                {"error": errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ------------------------
        # Safe lookup (strict)
        # ------------------------
        query = Q()

        if email:
            query |= Q(email_address__iexact=email)

        if mobile_number:
            query |= Q(mobile_number=mobile_number)

        try:
            client = ClientAuth.objects.get(query)

        except ClientAuth.DoesNotExist:
            return Response(
                {"error": "Client not found"},
                status=status.HTTP_404_NOT_FOUND
            )

        except ClientAuth.MultipleObjectsReturned:
            return Response(
                {"error": "Multiple accounts found. Contact support."},
                status=status.HTTP_409_CONFLICT
            )

        # ------------------------
        # BLOCK: account locked
        # ------------------------
        if (
            client.account_locked_until and
            client.account_locked_until > timezone.now()
        ):
            remaining_minutes = int(
                (client.account_locked_until - timezone.now())
                .total_seconds() / 60
            )

            return Response(
                {
                    "error": [
                        f"Account is temporarily locked. Try again in {remaining_minutes} minute(s)."
                    ]
                },
                status=status.HTTP_403_FORBIDDEN
            )

        # ------------------------
        # Prevent password reuse
        # ------------------------
        if check_password(new_password, client.password):
            return Response(
                {
                    "error": [
                        "New password cannot be the same as the old password."
                    ]
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # ------------------------
        # Update password
        # ------------------------
        client.password = make_password(new_password)

        client.failed_login_attempts = 0
        client.account_locked_until = None

        client.save(update_fields=[
            "password",
            "failed_login_attempts",
            "account_locked_until"
        ])

        return Response(
            {"message": "Password reset successfully"},
            status=status.HTTP_200_OK
        )

    except Exception:
        logger.exception("Unexpected error in reset_client_password")

        return Response(
            {
                "error": "Unable to reset password at this time."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


    
@api_view(['POST'])
@throttle_classes([ClientRegistrationThrottle])
@permission_classes([AllowAny])
def register_client(request):

    ip_address = get_client_ip(request)
    user_agent = get_device_info(request)

    try:
        serializer = ClientRegisterSerializer(
            data=request.data
        )

        if not serializer.is_valid():

            return Response(
                {
                    "success": False,
                    "errors": serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        email = (
            serializer.validated_data["email_address"]
            .lower()
            .strip()
        )

        mobile = serializer.validated_data[
            "mobile_number"
        ]

        # --------------------------------------------------
        # DUPLICATE EMAIL
        # --------------------------------------------------

        if ClientAuth.objects.filter(
            email_address=email
        ).exists():

            ClientRegistrationHistory.objects.create(
                email=email,
                mobile_number=mobile,
                successful=False,
                ip_address=ip_address,
                user_agent=user_agent,
                error_message="Email already exists"
            )

            return Response(
                {
                    "success": False,
                    "message": (
                        "A user with this email "
                        "already exists."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # --------------------------------------------------
        # DUPLICATE MOBILE
        # --------------------------------------------------

        if ClientAuth.objects.filter(
            mobile_number=mobile
        ).exists():

            ClientRegistrationHistory.objects.create(
                email=email,
                mobile_number=mobile,
                successful=False,
                ip_address=ip_address,
                user_agent=user_agent,
                error_message="Mobile already exists"
            )

            return Response(
                {
                    "success": False,
                    "message": (
                        "A user with this mobile "
                        "number already exists."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # --------------------------------------------------
        # CREATE ACCOUNT
        # --------------------------------------------------

        try:

            with transaction.atomic():

                client_auth = serializer.save(
                    email_address=email
                )

                ClientDetails.objects.get_or_create(
                    client_profile=client_auth
                )

                # --------------------------------------------------
                # CREATE EMAIL VERIFICATION OTP
                # --------------------------------------------------

                try:
                    otp_request, otp = create_client_otp(
                        client=client_auth,
                        purpose="email_verification"
                    )
                except OTPCooldownError as e:
                    return Response(
                        {
                            "success": False,
                            "message": f"Please wait {e.retry_after} seconds before requesting another code.",
                        },
                        status=status.HTTP_429_TOO_MANY_REQUESTS,
                    )

                # --------------------------------------------------
                # REGISTRATION HISTORY
                #
                # This means the account was successfully created.
                # It does NOT mean the email has been verified.
                # --------------------------------------------------

                ClientRegistrationHistory.objects.create(
                    email=email,
                    mobile_number=mobile,
                    successful=True,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    device_name=request.data.get(
                        "device_name"
                    )
                )

                # --------------------------------------------------
                # SEND OTP ONLY AFTER COMMIT
                # --------------------------------------------------

                transaction.on_commit(
                    lambda: send_client_otp_email.delay(
                        client_auth.email_address,
                        otp,
                        "email_verification",
                    )
                )

            return Response(
                {
                    "success": True,
                    "message": (
                        "Registration successful. "
                        "A verification code has been "
                        "sent to your email."
                    ),
                    "data": {
                        "id": client_auth.id,
                        "email": client_auth.email_address,
                        "mobile_number": (
                            client_auth.mobile_number
                        ),
                        "requires_email_verification": True,
                        "otp_request_id": str(
                            otp_request.request_id
                        ),
                    }
                },
                status=status.HTTP_201_CREATED
            )

        except IntegrityError:

            ClientRegistrationHistory.objects.create(
                email=email,
                mobile_number=mobile,
                successful=False,
                ip_address=ip_address,
                user_agent=user_agent,
                error_message="Integrity error"
            )

            return Response(
                {
                    "success": False,
                    "message": (
                        "Email is invalid or "
                        "mobile number is invalid."
                    )
                },
                status=status.HTTP_409_CONFLICT
            )

        except Exception:

            ClientRegistrationHistory.objects.create(
                email=email,
                mobile_number=mobile,
                successful=False,
                ip_address=ip_address,
                user_agent=user_agent,
                error_message="Server exception"
            )

            logger.exception(
                "Client registration failed"
            )

            return Response(
                {
                    "success": False,
                    "message": (
                        "A server error occurred. "
                        "Please try again later."
                    )
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    except Exception:

        ClientRegistrationHistory.objects.create(
            email=request.data.get("email_address"),
            mobile_number=request.data.get("mobile_number"),
            successful=False,
            ip_address=ip_address,
            user_agent=user_agent,
            error_message="Unexpected error"
        )

        logger.exception(
            "Unexpected error in register_client"
        )

        return Response(
            {
                "success": False,
                "message": (
                    "A server error occurred. "
                    "Please try again later."
                )
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    

@api_view(["POST"])
@throttle_classes([ClientOTPThrottle])
@permission_classes([AllowAny])
def verify_client_email(request):

    ip_address = get_client_ip(request)
    user_agent = get_device_info(request)

    serializer = ClientOTPVerifySerializer(
        data=request.data
    )

    if not serializer.is_valid():

        return Response(
            {
                "success": False,
                "errors": serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    if otp_request is None:
        hash_otp("000000")  # burn comparable time to a real verification attempt
        return Response(
        {
            "success": False,
            "message": "Invalid or expired verification code.",
        },
        status=status.HTTP_400_BAD_REQUEST,
    )

    request_id = serializer.validated_data["request_id"]
    otp = serializer.validated_data["otp"]

    try:

        with transaction.atomic():

            # Lock the OTP row so two simultaneous
            # verification requests cannot consume it.
            otp_request = (
                ClientOTP.objects
                .select_for_update()
                .select_related("client")
                .filter(
                    request_id=request_id,
                    purpose="email_verification",
                )
                .first()
            )

            # Do not reveal whether a request ID exists.
            if otp_request is None:

                return Response(
                    {
                        "success": False,
                        "message": (
                            "Invalid or expired verification code."
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            now = timezone.now()

            # --------------------------------------------------
            # ALREADY USED / VERIFIED
            # --------------------------------------------------

            if (
                otp_request.is_used
                or otp_request.is_verified
            ):

                return Response(
                    {
                        "success": False,
                        "message": (
                            "Invalid or expired verification code."
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # --------------------------------------------------
            # EXPIRED
            # --------------------------------------------------

            if now >= otp_request.expires_at:

                return Response(
                    {
                        "success": False,
                        "message": (
                            "Invalid or expired verification code."
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # --------------------------------------------------
            # MAXIMUM ATTEMPTS
            # --------------------------------------------------

            if (
                otp_request.attempts
                >= otp_request.max_attempts
            ):

                return Response(
                    {
                        "success": False,
                        "message": (
                            "Too many invalid verification "
                            "code attempts."
                        ),
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )

            # --------------------------------------------------
            # VERIFY OTP
            # --------------------------------------------------

            submitted_hash = hash_otp(otp)

            otp_valid = secrets.compare_digest(
                submitted_hash,
                otp_request.otp_hash,
            )

            if not otp_valid:

                otp_request.attempts += 1

                otp_request.save(
                    update_fields=["attempts"]
                )

                if (
                    otp_request.attempts
                    >= otp_request.max_attempts
                ):

                    return Response(
                        {
                            "success": False,
                            "message": (
                                "Too many invalid "
                                "verification code attempts."
                            ),
                        },
                        status=(
                            status.HTTP_429_TOO_MANY_REQUESTS
                        ),
                    )

                return Response(
                    {
                        "success": False,
                        "message": (
                            "Invalid or expired "
                            "verification code."
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # --------------------------------------------------
            # OTP VALID
            # --------------------------------------------------

            user = otp_request.client

            # Mark OTP as consumed.
            otp_request.is_verified = True
            otp_request.is_used = True
            otp_request.verified_at = now

            otp_request.save(
                update_fields=[
                    "is_verified",
                    "is_used",
                    "verified_at",
                ]
            )

            # --------------------------------------------------
            # VERIFY EMAIL
            # --------------------------------------------------

            user.email_verified_at = now

            user.save(
                update_fields=[
                    "email_verified_at",
                ]
            )

            # --------------------------------------------------
            # GENERATE JWT ONLY AFTER EMAIL VERIFICATION
            # --------------------------------------------------

            tokens = generate_client_tokens(user)

        return Response(
            {
                "success": True,
                "message": "Email verified successfully.",
                "data": {
                    "id": user.id,
                    "email": user.email_address,
                    "mobile_number": user.mobile_number,
                    "is_profile_completed": (
                        user.is_profile_completed
                    ),
                    "access_token": tokens["access"],
                    "refresh_token": tokens["refresh"],
                },
            },
            status=status.HTTP_200_OK,
        )

    except Exception:

        logger.exception(
            "Client email verification failed unexpectedly"
        )

        return Response(
            {
                "success": False,
                "message": (
                    "Unable to verify your email at this time."
                ),
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    


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

        serializer = ClientSerializer(
            client,
            context={'request': request}
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )

    except ClientDetails.DoesNotExist:
        return Response(
            {"error": "Client not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
        logger.exception("Unexpected error in get_my_profile")

        return Response(
            {"error": "Unable to retrieve profile at this time."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    

def _user_has_access(user, address_obj):
    """
    RLS rule:
    Only a user who is an active super user on this address
    may view the household members.
    """
    return ClientAddress.objects.filter(
        client__client_profile=user,
        address=address_obj.address,
        is_active=True,
        is_super_user=True,
    ).exists()


@api_view(["GET"])
@authentication_classes([ClientJWTAuthentication])
@throttle_classes([UserReadThrottle])
@permission_classes([IsAuthenticated])
def get_household_members(request, client_address_id):
    try:
        selected = ClientAddress.objects.select_related(
            "address",
            "client",
        ).get(
            id=client_address_id,
            is_active=True,
        )
    except ClientAddress.DoesNotExist:
        return Response(
            {
                "success": False,
                "message": "Address membership not found.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    if not _user_has_access(request.user, selected):
        return Response(
            {
                "success": False,
                "message": "You do not have permission to view this address.",
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    members = (
        ClientAddress.objects.select_related(
            "client",
            "client__client_profile",
        )
        .filter(
            address=selected.address,
            is_active=True,
        )
        .exclude(
            client__client_profile=request.user,
        )
        .order_by(
            "-is_owner",
            "-house_administrator",
            "client__first_name",
        )
    )

    serializer = HouseholdMemberSerializer(
        members,
        many=True,
        context={"request": request},
    )

    return Response(
        {
            "success": True,
            "count": members.count(),
            "data": serializer.data,
        },
        status=status.HTTP_200_OK,
    )







    
@api_view(['POST'])
@throttle_classes([AuthThrottle])
@parser_classes([MultiPartParser, FormParser])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def client_logout(request):
    try:
        refresh_token = request.data.get("refresh")

        if refresh_token:
            try:
                token = RefreshToken(refresh_token)
                token.blacklist()
            except TokenError:
                # 🔥 IMPORTANT: already invalid → treat as success
                pass

        return Response(
            {"detail": "Logged out successfully"},
            status=status.HTTP_200_OK,
        )

    except Exception:
        # NEVER expose internal errors
        return Response(
            {"detail": "Logged out successfully"},
            status=status.HTTP_200_OK,
        )

@api_view(['PATCH'])
@throttle_classes([ProfileWriteThrottle])
@parser_classes([MultiPartParser, FormParser])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def complete_profile(request):

    try:
        # Enforce strict ownership profile isolation (RLS)
        client = get_object_or_404(
            ClientDetails,
            client_profile=request.user
        )

        serializer = ClientSerializer(
            client,
            data=request.data,
            partial=True,
            context={'request': request}
        )

        if serializer.is_valid():
            updated_client = serializer.save()

            # lifecycle state tracking
            if (
                updated_client.first_name and
                updated_client.last_name and
                updated_client.date_of_birth
            ):
                updated_client.client_profile.is_profile_completed = "in-address"
                updated_client.client_profile.save(update_fields=["is_profile_completed"])

            return Response({
                "success": True,
                "data": serializer.data,
                "profile_status": updated_client.client_profile.is_profile_completed,
            })

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST
        )

    except ClientDetails.DoesNotExist:
        # keep frontend unchanged → same shape, just safe fallback
        return Response(
            {
                "success": False,
                "message": "Client not found"
            },
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
      
        logger.exception("Error in complete_profile")

        return Response(
            {
                "success": False,
                "message": "Unexpected server error"
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
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
        with transaction.atomic():

            # lock the selected address row
            client_address = ClientAddress.objects.select_for_update().get(
                pk=address_id,
                client=client
            )

            # unset previous default
            ClientAddress.objects.filter(
                client=client,
                is_default=True
            ).update(is_default=False)

            # set new default
            client_address.is_default = True
            client_address.save(update_fields=["is_default"])

        return Response(
            {
                "success": True,
                "detail": f"Address {client_address.address} is now default."
            },
            status=status.HTTP_200_OK
        )

    except ClientAddress.DoesNotExist:
        return Response(
            {"detail": "Address not found for this client."},
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
        logger.exception("Error setting default address")

        return Response(
            {
                "success": False,
                "detail": "Unable to update default address."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )




from rest_framework.exceptions import ValidationError


@api_view(['POST'])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def a_add_residential_address(request):

    try:
        client = get_object_or_404(
            ClientDetails,
            client_profile=request.user
        )

        serializer = ClientAddressWriteSerializer(
            data=request.data,
            context={"client": client}
        )

        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "message": "Address validation failed.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            with transaction.atomic():
                client_address = serializer.save()

        except ValidationError as exc:
            return Response(
                {
                    "success": False,
                    "message": "Address validation failed.",
                    "errors": exc.detail,
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                "success": True,
                "message": "Address added successfully.",
                "data": ClientAddressSerializerr(
                    client_address
                ).data,
            },
            status=status.HTTP_201_CREATED
        )

    except Exception:
        logger.exception("Error adding residential address")

        return Response(
            {
                "success": False,
                "message": "Unable to add address at this time."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def add_residential_address(request):

    try:
        client = get_object_or_404(
            ClientDetails,
            client_profile=request.user
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

        with transaction.atomic():

            client_address = serializer.save()

            client.client_profile.is_profile_completed = "completed"
            client.client_profile.save(
                update_fields=["is_profile_completed"]
            )

        return Response(
            {
                "success": True,
                "message": "Address added successfully.",
                "data": ClientAddressSerializerr(client_address).data,
                "profile_status": client.client_profile.is_profile_completed,
            },
            status=status.HTTP_201_CREATED
        )

    except Exception:
        logger.exception("Error adding residential address")

        return Response(
            {
                "success": False,
                "message": "Unable to add address at this time."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["POST"])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def super_user_deactivate_client_address(request, address_id):

    try:
        # ==========================================
        # GET AUTHENTICATED CLIENT
        # ==========================================
        super_user = get_object_or_404(
            ClientDetails,
            client_profile=request.user
        )

        # ==========================================
        # GET TARGET CLIENT ADDRESS
        # ==========================================
        client_address = get_object_or_404(
            ClientAddress.objects.select_related(
                "client",
                "address",
            ),
            id=address_id,
        )

        # ==========================================
        # VERIFY SUPER USER ACCESS
        # ==========================================
        has_super_user_access = ClientAddress.objects.filter(
            client=super_user,
            address=client_address.address,
            is_active=True,
            is_super_user=True,
        ).exists()

        if not has_super_user_access:
            return Response(
                {
                    "success": False,
                    "message": (
                        "You do not have super-user permission "
                        "for this address."
                    ),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

       

        # ==========================================
        # CHECK CURRENT STATUS
        # ==========================================
        if not client_address.is_active:
            return Response(
                {
                    "success": False,
                    "message": "This household member is already inactive.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ==========================================
        # DEACTIVATE + HISTORY
        # ==========================================
        with transaction.atomic():

            client_address.is_active = False
            client_address.is_activatable = False

            client_address.save(
                update_fields=[
                    "is_active",
                    "is_activatable",
                ]
            )

            history = create_client_address_history(
                client_address=client_address,
                action=ClientAddressHistory.ACTION_DEACTIVATED,
                performed_by=super_user,
                reason="Deactivated by super user.",
                metadata={
                    "performed_by_role": "super_user",
                    "previous_is_active": True,
                    "new_is_active": False,
                    "previous_is_activatable": True,
                    "new_is_activatable": False,
                },
            )

        # ==========================================
        # RESPONSE
        # ==========================================
        return Response(
            {
                "success": True,
                "message": (
                    "Household member deactivated successfully."
                ),
                "data": {
                    "client_address": ClientAddressSerializerr(
                        client_address
                    ).data,
                    "history_id": history.id,
                },
            },
            status=status.HTTP_200_OK,
        )

    except Exception:
        logger.exception(
            "Error deactivating household member by super user"
        )

        return Response(
            {
                "success": False,
                "message": (
                    "Unable to deactivate household member "
                    "at this time."
                ),
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    

@api_view(["POST"])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def deactivate_client_address(request, address_id):

    try:
        client = get_object_or_404(
            ClientDetails,
            client_profile=request.user
        )

        client_address = get_object_or_404(
            ClientAddress,
            id=address_id,
            client=client
        )

        serializer = ClientAddressDeactivateSerializer(
            instance=client_address,
            data={},
            context={"client": client}
        )

        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "message": "Unable to deactivate address.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            client_address = serializer.save()

        return Response(
            {
                "success": True,
                "message": "Address deactivated successfully.",
                "data": ClientAddressSerializerr(
                    client_address
                ).data,
            },
            status=status.HTTP_200_OK
        )

    except Exception:
        logger.exception("Error deactivating client address")

        return Response(
            {
                "success": False,
                "message": "Unable to deactivate address at this time."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    

@api_view(['GET'])
@throttle_classes([AuthThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def get_my_auth(request):

    try:
        serializer = ClientAuthReadSerializer(
            request.user,
            context={"request": request}
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )

    except Exception:
        logger.exception("Error in get_my_auth")

        return Response(
            {
                "error": "Unable to retrieve authentication data."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    




@api_view(["POST"])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([ProfileWriteThrottle])
def submit_address_verification(request, client_address_id):

    try:
        client = get_client_details(request)
        client_auth = get_client_auth(request)
        
        customer_id = str(client_auth.id)

        client_address = ClientAddress.objects.get(
            id=client_address_id,
            client=client
        )

        proof_of_residence = request.FILES.get("proof_of_residence")
        id_document = request.FILES.get("id_document")
        liveness_video = request.FILES.get("liveness_video")
        id_number = request.data.get("id_number")

        serializer = AddressVerificationCreateSerializer(
            data={
                "client_address": client_address.id,
                "id_number": id_number,
                "proof_of_residence": proof_of_residence,
                "id_document": id_document,
                "liveness_video": liveness_video,
            },
            context={"request": request},
        )

        if not serializer.is_valid():
            logger.error(
                "Address verification serializer errors: %s",
                serializer.errors,
            )

            return Response(
                {
                    "success": False,
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # -------------------------------------------------
        # SAVE / RESET VERIFICATION
        # -------------------------------------------------
        with transaction.atomic():
            verification = serializer.save()

        # Use the validated value rather than the raw request value.
        validated_id_number = serializer.validated_data["id_number"]

        # -------------------------------------------------
        # WAIT FOR AI VERIFICATION
        # -------------------------------------------------
        try:
            ai_result = AIAddressVerificationClient.verify_address(
    customer_id=customer_id,
    client=client,
    id_number=validated_id_number,
    id_document=id_document,
    liveness_video=liveness_video,
    proof_of_residence=proof_of_residence,
)

        except requests.HTTPError as exc:
            # -------------------------------------------------
            # AI SERVER RESPONDED WITH HTTP ERROR
            # -------------------------------------------------
            detail = None

            try:
                response_data = exc.response.json()

                detail = (
                    response_data.get("detail")
                    or response_data.get("message")
                    or response_data.get("error")
                )

            except Exception:
                pass

            note = detail or "Address verification failed."

            logger.warning(
                "AI address verification rejected request for "
                "client_address %s: %s",
                client_address.id,
                note,
            )

            verification.reject(note=note)

            return Response(
                {
                    "success": False,
                    "message": note,
                    "status": verification.status,
                },
                status=status.HTTP_200_OK,
            )

        except requests.RequestException:
            # -------------------------------------------------
            # AI SERVER DID NOT RESPOND
            # -------------------------------------------------
            logger.exception(
                "AI address verification service unreachable "
                "for client_address %s",
                client_address.id,
            )

            # Keep it pending. We don't know whether the user
            # passed or failed verification.
            return Response(
                {
                    "success": True,
                    "message": (
                        "Verification submitted successfully. "
                        "AI verification is pending."
                    ),
                    "status": verification.status,
                },
                status=status.HTTP_202_ACCEPTED,
            )

        # -------------------------------------------------
        # AI RESPONDED SUCCESSFULLY
        # -------------------------------------------------
        verification_status = ai_result.get("verification_status")

        logger.info(
            "AI address verification response for client_address %s: %s",
            client_address.id,
            ai_result,
        )

        # -------------------------------------------------
        # VERIFIED
        # -------------------------------------------------
        if verification_status == "verified":

            verification.approve()

            return Response(
                {
                    "success": True,
                    "message": (
                        ai_result.get("message")
                        or "Address verification successful."
                    ),
                    "status": verification.status,
                },
                status=status.HTTP_200_OK,
            )

        # -------------------------------------------------
        # REJECTED / FAILED
        # -------------------------------------------------
        verification.reject(
            note=(
                ai_result.get("message")
                or ai_result.get("detail")
                or "Address verification failed."
            )
        )

        return Response(
            {
                "success": False,
                "message": (
                    ai_result.get("message")
                    or ai_result.get("detail")
                    or "Address verification failed."
                ),
                "status": verification.status,
            },
            status=status.HTTP_200_OK,
        )

    except ClientAddress.DoesNotExist:
        return Response(
            {
                "success": False,
                "message": "Client address not found.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    except Exception:
        logger.exception(
            "Error submitting address verification"
        )

        return Response(
            {
                "success": False,
                "message": (
                    "Unable to submit verification at this time."
                ),
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    



@api_view(['POST'])
@throttle_classes([AuthThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def register_device_token(request):

    try:
        # RLS enforcement (keeps your pattern consistent)
        get_object_or_404(ClientDetails, client_profile=request.user)

        serializer = DeviceTokenWriteSerializer(
            data=request.data,
            context={'request': request}
        )

        serializer.is_valid(raise_exception=True)

        token = serializer.validated_data["fcm_token"]
        ip_address = get_client_ip(request)

        with transaction.atomic():

            # Deduplication Step 1
            DeviceToken.objects.filter(
                fcm_token=token
            ).exclude(
                client=request.user
            ).delete()

            # Deduplication Step 2
            device_token, created = DeviceToken.objects.update_or_create(
                client=request.user,
                fcm_token=token,
                defaults={
                    "device_type": serializer.validated_data.get("device_type"),
                    "device_name": serializer.validated_data.get("device_name"),
                    "os_version": serializer.validated_data.get("os_version"),
                    "app_version": serializer.validated_data.get("app_version"),
                    "provider": serializer.validated_data.get("provider", "firebase"),
                    "ip_address": ip_address,
                }
            )

        return Response(
            {
                "success": True,
                "message": (
                    "Device token registered successfully"
                    if created else
                    "Device token updated successfully"
                ),
                "token_id": device_token.id,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    except Exception:
        logger.exception("Error registering device token")

        return Response(
            {
                "success": False,
                "message": "Unable to register device token at this time."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    


@api_view(['POST'])
@throttle_classes([AuthThrottle])
@permission_classes([AllowAny])
def client_login(request):

    ip_address = get_client_ip(request)
    user_agent = get_device_info(request)

    try:
        serializer = ClientLoginSerializer(
            data=request.data,
            context={"request": request}
        )

        if serializer.is_valid():

            user = serializer.validated_data["user"]

            # -----------------------------------------
            # PASSWORD AUTHENTICATION SUCCESSFUL
            # -----------------------------------------
            #
            # This is NOT yet a successful login.
            # OTP verification is still required.
            #

# In client_login(request), replacing the current otp_request, otp = create_login_otp(client=user) call:
            try:
                otp_request, otp = create_login_otp(client=user)
            except OTPCooldownError as e:
                return Response(
                    {
                        "success": False,
                        "message": f"Please wait {e.retry_after} seconds before requesting another code.",
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )

            # Only send the email after the OTP transaction
            # has successfully committed.
            transaction.on_commit(
                lambda: send_client_login_otp_email.delay(
                    user.email_address,
                    otp,
                )
            )

            return Response(
                {
                    "success": True,
                    "message": (
                        "A verification code has been "
                        "sent to your email."
                    ),
                    "data": {
                        "requires_otp": True,
                        "otp_request_id": str(
                            otp_request.request_id
                        ),
                    }
                },
                status=status.HTTP_200_OK
            )

        # -----------------------------------------
        # PASSWORD AUTHENTICATION FAILED
        # -----------------------------------------

        ClientLoginHistory.objects.create(
            client=None,
            successful=False,
            identifier=request.data.get("email"),
            user_agent=user_agent,
            ip_address=ip_address,
            device_name=request.data.get("device_name")
        )

        return Response(
            {
                "success": False,
                "errors": serializer.errors
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    except Exception:
        logger.exception(
            "Client login failed unexpectedly"
        )

        ClientLoginHistory.objects.create(
            client=None,
            successful=False,
            identifier=request.data.get("email"),
            user_agent=user_agent,
            ip_address=ip_address,
            device_name=request.data.get("device_name")
        )

        return Response(
            {
                "success": False,
                "message": (
                    "Unable to process login at this time."
                )
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )





@api_view(["POST"])
@throttle_classes([ClientOTPThrottle])
@permission_classes([AllowAny])
def verify_client_login_otp(request):

    ip_address = get_client_ip(request)
    user_agent = get_device_info(request)

    serializer = ClientOTPVerifySerializer(
        data=request.data
    )

    if not serializer.is_valid():

        return Response(
            {
                "success": False,
                "errors": serializer.errors
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    if otp_request is None:
        hash_otp("000000")  # burn comparable time to a real verification attempt
        return Response(
        {
            "success": False,
            "message": "Invalid or expired verification code.",
        },
        status=status.HTTP_400_BAD_REQUEST,
    )

    request_id = serializer.validated_data["request_id"]
    otp = serializer.validated_data["otp"]

    try:

        with transaction.atomic():

            otp_request = (
                ClientOTP.objects
                .select_for_update()
                .select_related("client")
                .filter(
                    request_id=request_id,
                    purpose="login",
                )
                .first()
            )

            # Don't reveal whether the request_id exists.
            if otp_request is None:

                return Response(
                    {
                        "success": False,
                        "message": (
                            "Invalid or expired OTP."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            now = timezone.now()

            # -----------------------------------------
            # OTP ALREADY USED
            # -----------------------------------------

            if (
                otp_request.is_used
                or otp_request.is_verified
            ):

                return Response(
                    {
                        "success": False,
                        "message": (
                            "Invalid or expired OTP."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # -----------------------------------------
            # OTP EXPIRED
            # -----------------------------------------

            if now >= otp_request.expires_at:

                return Response(
                    {
                        "success": False,
                        "message": (
                            "Invalid or expired OTP."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # -----------------------------------------
            # TOO MANY ATTEMPTS
            # -----------------------------------------

            if (
                otp_request.attempts
                >= otp_request.max_attempts
            ):

                return Response(
                    {
                        "success": False,
                        "message": (
                            "Too many invalid OTP attempts."
                        )
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS
                )

            # -----------------------------------------
            # CONSTANT-TIME OTP COMPARISON
            # -----------------------------------------

            submitted_hash = hash_otp(otp)

            otp_valid = secrets.compare_digest(
                submitted_hash,
                otp_request.otp_hash
            )

            if not otp_valid:

                otp_request.attempts += 1

                otp_request.save(
                    update_fields=["attempts"]
                )

                if (
                    otp_request.attempts
                    >= otp_request.max_attempts
                ):
                    return Response(
                        {
                            "success": False,
                            "message": (
                                "Too many invalid "
                                "OTP attempts."
                            )
                        },
                        status=(
                            status.HTTP_429_TOO_MANY_REQUESTS
                        )
                    )

                return Response(
                    {
                        "success": False,
                        "message": (
                            "Invalid or expired OTP."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # -----------------------------------------
            # OTP SUCCESSFULLY VERIFIED
            # -----------------------------------------

            otp_request.is_verified = True
            otp_request.is_used = True
            otp_request.verified_at = now

            otp_request.save(
                update_fields=[
                    "is_verified",
                    "is_used",
                    "verified_at",
                ]
            )

            user = otp_request.client

            # -----------------------------------------
            # UPDATE LOGIN INFORMATION
            # -----------------------------------------

            user.last_login_at = now
            user.last_login_ip = ip_address

            user.failed_login_attempts = 0

            user.save(
                update_fields=[
                    "last_login_at",
                    "last_login_ip",
                    "failed_login_attempts",
                ]
            )

            # -----------------------------------------
            # LOG ACTUAL SUCCESSFUL LOGIN
            # -----------------------------------------

            ClientLoginHistory.objects.create(
                client=user,
                successful=True,
                identifier=user.email_address,
                user_agent=user_agent,
                ip_address=ip_address,
                device_name=request.data.get(
                    "device_name"
                )
            )

            # -----------------------------------------
            # JWT IS GENERATED ONLY HERE
            # -----------------------------------------

            tokens = generate_client_tokens(user)

        return Response(
            {
                "success": True,
                "message": "Login successful.",
                "data": {
                    "id": user.id,
                    "is_profile_completed": (
                        user.is_profile_completed
                    ),
                    "access_token": tokens["access"],
                    "refresh_token": tokens["refresh"],
                }
            },
            status=status.HTTP_200_OK
        )

    except Exception:

        logger.exception(
            "Client login OTP verification failed "
            "unexpectedly"
        )

        return Response(
            {
                "success": False,
                "message": (
                    "Unable to process OTP verification "
                    "at this time."
                )
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )





# @api_view(['GET'])
# @throttle_classes([UserReadThrottle])
# @authentication_classes([ClientJWTAuthentication])
# @permission_classes([IsAuthenticated])
# def address_list(request,format=None):

#     if request.method == 'PUT':
#         serializer = AddressSerializer(data=request.data)
#         if serializer.is_valid():
#             address = Address.objects.get(id=request.data.get('id'))
#             serializer.update(address, request.data)
#             return Response(serializer.data, status=200)
#         return Response(serializer.errors, status=400)

#     if request.method == 'DELETE':
#         address_id = request.data.get('id')
#         try:
#             address = Address.objects.get(id=address_id)
#             address.delete()
#             return Response({'message': 'Address deleted successfully.'}, status=204)
#         except Address.DoesNotExist:
#             return Response({'error': 'Address not found.'}, status=404)

# @api_view(['GET'])
# @throttle_classes([UserReadThrottle])
# @authentication_classes([ClientJWTAuthentication])
# @permission_classes([IsAuthenticated])
# def client_address_list(request,format=None):
#     if request.method == 'POST':
#         serializer = ClientAddressSerializer(data=request.data)
#         if serializer.is_valid():
#             serializer.save()
#             return Response({'message': 'Client Address created successfully.', 'data': serializer.data}, status=201)
#         return Response({'error': 'Invalid data provided.', 'details': serializer.errors}, status=400)

        

# @api_view(['GET', 'PUT', 'PATCH'])
# @authentication_classes([ClientJWTAuthentication])
# @permission_classes([IsAuthenticated])
# @throttle_classes([UserReadThrottle])
# def clientProfile_detail(request, format=None):
#     try:
#         client_profile = get_client_details(request)
#     except ClientAuth.DoesNotExist:
#         return Response({'error': 'Client Profile not found.'}, status=status.HTTP_404_NOT_FOUND)

#     if request.method == 'GET':
#         serializer = ClientProfileSerializer(client_profile)
#         return Response(serializer.data, status=status.HTTP_200_OK)

#     elif request.method in ['PUT', 'PATCH']:
#         data = request.data.copy()
#         if 'email_address' in data and data['email_address'] != client_profile.email_address:
#             return Response({'error': 'You cannot update the email address.'}, status=status.HTTP_400_BAD_REQUEST)

#         partial = request.method == 'PATCH'
#         serializer = ClientProfileSerializer(client_profile, data=data, partial=partial)
#         if serializer.is_valid():
#             serializer.save()
#             return Response({'message': 'Client Profile updated successfully.', 'data': serializer.data}, status=status.HTTP_200_OK)
#         return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def client_detail(request, format=None):

    try:
        client = get_client_details(request)

        serializer = ClientSerializer(
            client,
            context={'request': request}
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )

    except ClientDetails.DoesNotExist:
        return Response(
            {'error': 'Client not found.'},
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
        logger.exception("Error fetching client detail")

        return Response(
            {'error': 'Unexpected server error.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    



@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def address_detail(request, id, format=None):

    try:
        client = get_client_details(request)

        address = Address.objects.get(
            id=id,
            clientaddress__client=client  # 🔒 RLS enforcement
        )

        serializer = ClientSavedAddressSerializer(address)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )

    except Address.DoesNotExist:
        return Response(
            {'error': 'Address not found.'},
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
        logger.exception("Error fetching address detail")

        return Response(
            {'error': 'Unexpected server error.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
    
    
@api_view(["PATCH"])
@throttle_classes([RegisterThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def update_client_profile(request):
    client = get_client_details(request)

    serializer = ClientProfileAppUpdateSerializer(
        client,
        data=request.data,
        partial=True,
    )

    if serializer.is_valid():
        serializer.save()

        return Response(
            {
                "success": True,
                "message": "Profile updated successfully.",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    return Response(
        {
            "success": False,
            "errors": serializer.errors,
        },
        status=status.HTTP_400_BAD_REQUEST,
    )

    

@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def client_address_detail(request, client_id, format=None):

    try:
        # 🔒 RLS: enforce ownership explicitly
        client = ClientDetails.objects.get(
            client_profile__id=client_id,
            client_profile=request.user
        )

        client_addresses = (
            ClientAddress.objects
            .select_related('address')
            .filter(client=client, is_active=True)
            .order_by('-is_default', 'id')
        )

        serializer = ClientAddressSerializer(
            client_addresses,
            many=True
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )

    except ClientDetails.DoesNotExist:
        return Response(
            {'error': 'Client not found or access denied.'},
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
        logger.exception("Error fetching client addresses")

        return Response(
            {'error': 'Unexpected server error.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
    

# @api_view(['GET'])
# @throttle_classes([UserReadThrottle])
# @authentication_classes([ClientJWTAuthentication])
# @permission_classes([IsAuthenticated])
# @parser_classes([MultiPartParser, FormParser])
# def client_profile_me(request):
#     try:
#         client = ClientDetails.objects.get(client_profile=request.user)
#     except ClientDetails.DoesNotExist:
#         return Response({'error': 'Client profile not found'}, status=status.HTTP_404_NOT_FOUND)

#     if request.method == 'GET':
#         serializer = ClientSerializer(client, context={'request': request})
#         return Response(serializer.data)


    
@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def client_saved_addresses(request, client_id):

    try:
        client = ClientDetails.objects.get(
            id=client_id,
            client_profile=request.user
        )

    except ClientDetails.DoesNotExist:
        return Response(
            {'error': 'Client not found or access denied.'},
            status=status.HTTP_404_NOT_FOUND
        )

    client_addresses = (
        ClientAddress.objects
        .select_related('address')
        .filter(client=client)
    )

    # ⚠️ no model mutation
    address_data = [ca.address for ca in client_addresses]

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

        default_address = (
            ClientAddress.objects
            .filter(client=client, is_default=True)
            .select_related('address')
            .first()
        )

        if not default_address:
            return Response(
                {"error": "No default address found."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = ClientAddressNoDuplicatesSerializer(default_address)

        return Response(
            {"client_address": serializer.data},
            status=status.HTTP_200_OK
        )

    except Exception:
        logger.exception("Error fetching default address")

        return Response(
            {"error": "Unexpected server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
    
@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def clients_by_addresses(request):

    try:
        client = get_client_details(request)

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
                if x.strip()
            ]

        except ValueError:
            return Response(
                {"error": "Invalid address IDs format."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # safety cap (prevents abuse)
        if len(address_ids) > 50:
            return Response(
                {"error": "Too many address IDs requested."},
                status=status.HTTP_400_BAD_REQUEST
            )

        client_addresses = (
            ClientAddress.objects
            .filter(client=client, address_id__in=address_ids)
            .select_related("address")
        )

        serializer = ClientAddressSerializer(
            client_addresses,
            many=True,
            context={"request": request}
        )

        return Response(
            {"addresses": serializer.data},
            status=status.HTTP_200_OK
        )

    except Exception:
        logger.exception("Error fetching client addresses by IDs")

        return Response(
            {"error": "Unexpected server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
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