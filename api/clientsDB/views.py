import re
import secrets
from sqlite3 import IntegrityError

import requests
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
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
from api.bookings.models import Negotiation, OrderService, Session, Shipment
from api.clientsDB.services.address_verify_service import AIAddressVerificationClient
from api.clientsDB.services.client_history_model_helper import create_client_address_history
from api.clientsDB.services.client_ip_address_helper import get_client_ip, get_device_info
from api.clientsDB.services.client_login_token import  generate_email_login_tokenn
from api.clientsDB.services.client_otp_token import generate_email_verification_token
from api.clientsDB.services.email_mask_helper import mask_email
from api.clientsDB.services.jwt_client_authentication import ClientJWTAuthentication
from api.clientsDB.services.otp_service import create_client_otp,  hash_otp
from api.clientsDB.services.otp_tasks import OTP_EMAIL_VERIFICATION, OTP_LOGIN, OTP_PASSWORD_RESET, OTPCooldownError, send_account_deleted_email, send_client_otp_email, send_password_changed_email
from api.clientsDB.services.password_reset_token import generate_password_reset_token
from api.clientsDB.services.sa_phone_number_helper import normalize_sa_mobile
from api.serviceProvidersDB.models import ProviderQualification, ProviderService
from api.serviceProvidersDB.serializers import ChangePasswordSerializer, ProviderQualificationReadSerializer
from plug_backend.helpers.auth_helpers import get_client_auth, get_client_details
from plug_backend.throttles import AccountDeleteThrottle, AuthThrottle, ClientOTPThrottle, ClientRegistrationThrottle, ProfileWriteThrottle, RegisterThrottle, UserReadThrottle
from plug_backend.utils.client_jwt_helper import generate_client_tokens
from django.db.models import Q
from django.utils import timezone
from .models.models import ClientAddressHistory, ClientAuth, ClientDetails, Address, ClientAddress, ClientLoginHistory, ClientNotification, ClientOTP, ClientRegistrationHistory, DeviceToken 
from .serializers import AddressClaimSerializer, AddressOnlySerializer, AddressVerificationCreateSerializer, ClientAddressDeactivateSerializer, ClientAddressNoDuplicatesSerializer, AddressSerializer, ClientAddressSerializerr, ClientAddressWriteSerializer, ClientAuthReadSerializer, ClientLoginSerializer, ClientOTPVerifySerializer, ClientProfileAppUpdateSerializer, ClientProfileSerializer, ClientRegisterSerializer, ClientSavedAddressSerializer, ClientSerializer, ClientAddressSerializer, DefaultAddressSerializer, DeleteAccountSerializer, DeviceTokenWriteSerializer, HouseholdMemberSerializer, ResetPasswordWithOTPSerializer
from django.contrib.auth.hashers import check_password, make_password





@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def request_client_password_reset(request):

    try:
        email = request.data.get("email")
        mobile_number = request.data.get("mobile_number")

        if not email and not mobile_number:
            return Response(
                {"error": "Provide email or mobile_number"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if email:
            email = email.strip().lower()

        if mobile_number:
            mobile_number = normalize_sa_mobile(mobile_number)
            if not mobile_number:
                return Response(
                    {"error": "Invalid mobile number format"},
                    status=status.HTTP_400_BAD_REQUEST
                )

        query = Q()
        if email:
            query |= Q(email_address__iexact=email)
        if mobile_number:
            query |= Q(mobile_number=mobile_number)

        # Generic response used whenever we must not reveal whether an
        # account exists. Deliberately excludes otp_request_id /
        # verification_token — there's nothing to verify if we never
        # actually created a challenge.
        GENERIC_SENT_RESPONSE = {
            "success": True,
            "message": "If an account exists, a verification code has been sent.",
        }

        try:
            client = ClientAuth.objects.get(query)

        except ClientAuth.DoesNotExist:
            # Don't reveal that this account doesn't exist — same shape
            # as the success path below.
            return Response(GENERIC_SENT_RESPONSE, status=status.HTTP_200_OK)

        except ClientAuth.MultipleObjectsReturned:
            # This is a data-integrity problem on our side, not
            # per-caller information — fine to keep specific.
            return Response(
                {"error": "Multiple accounts found. Contact support."},
                status=status.HTTP_409_CONFLICT
            )

        if (
            client.account_locked_until and
            client.account_locked_until > timezone.now()
        ):
            # Also collapse this into the generic response. Revealing
            # "account locked" still confirms the account exists, just
            # via a different status code than 404 — same leak, different door.
            return Response(GENERIC_SENT_RESPONSE, status=status.HTTP_200_OK)

        try:
            otp_request, otp = create_client_otp(
                client=client,
                purpose=OTP_PASSWORD_RESET,
            )

        except OTPCooldownError:
            # Also collapse into the generic response — a cooldown message
            # (implying "you already requested one recently") still confirms
            # the account exists. The real OTP is still on its way to their
            # inbox from the earlier request, so this is safe to hide.
            return Response(GENERIC_SENT_RESPONSE, status=status.HTTP_200_OK)

        verification_token = generate_password_reset_token(client, otp_request)

        transaction.on_commit(
            lambda: send_client_otp_email.delay(
                client.email_address,
                otp,
                OTP_PASSWORD_RESET,
            )
        )

        return Response(
            {
                "success": True,
                "message": "A verification code has been sent to your email.",
                "data": {
                    "otp_request_id": str(otp_request.request_id),
                    "verification_token": verification_token,
                },
            },
            status=status.HTTP_200_OK,
        )

    except Exception:
        logger.exception("Unexpected error in request_client_password_reset")
        return Response(
            {"error": "Unable to process request at this time."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    

def password_complexity_errors(password: str) -> list:
    errors = []
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if len(password) > 128:
        errors.append("Password cannot exceed 128 characters.")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        errors.append("Password must contain at least one lowercase letter.")
    if not re.search(r"\d", password):
        errors.append("Password must contain at least one digit.")
    return errors
 
 
def _mask_email(email: str) -> str:
    try:
        local, domain = email.split("@", 1)
    except ValueError:
        return "your email"
    return f"{local[:1]}***@{domain}"




BLOCKING_SHIPMENT_STATUSES = {"in_transit", "arrived"}
TERMINAL_ORDER_STATUSES = {
    "cancelled",
    "declined",
    "rejected",
    "completed",
}

@api_view(["POST"])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([AccountDeleteThrottle])  
def delete_client_account(request):
    with transaction.atomic():
        client = ClientAuth.objects.select_for_update().get(pk=request.user.pk)

        serializer = DeleteAccountSerializer(
            data=request.data, context={"client": client}
        )
        serializer.is_valid(raise_exception=True)

        client_details = ClientDetails.objects.filter(
            client_profile=client
        ).select_for_update().first()

        # ---------------- BLOCKING CHECKS ----------------
        # ASSUMPTION: OrderService.client points to ClientDetails.
        # Confirm the real FK name/path before relying on this.
        active_orders = OrderService.objects.filter(
            client=client_details
        ).exclude(status__in=TERMINAL_ORDER_STATUSES)  # confirm exact values

        blocked_session = Session.objects.filter(
            shipment__service_ordered__order__client=client_details,
            session_status="in_session",
        ).exists()

        blocked_shipment = Shipment.objects.filter(
            service_ordered__order__client=client_details,
            shipment_status__in=BLOCKING_SHIPMENT_STATUSES,
        ).exists()

        if blocked_session or blocked_shipment:
            return Response(
                {
                    "error": (
                        "You can't delete your account while a booking is "
                        "in progress. Please wait for the current session "
                        "to finish. Or cancel bookings that are in transit or have arrived."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        # ---------------- CANCEL ACTIVE ORDERS ----------------
        for order in active_orders:
            order.invited_providers.clear()

            Negotiation.objects.filter(
                service_order=order
            ).exclude(
                status__in=["accepted", "rejected", "canceled", "expired"]
            ).update(status="canceled")

            # Delete uploaded order photos + files
            for pic in order.service_pictures.all():
                if pic.image:
                    pic.image.delete(save=False)
            order.service_pictures.all().delete()

            order.status = "cancelled"  # confirm exact terminal string
            order.save(update_fields=["status"])

        # ---------------- ADDRESSES ----------------
        client_addresses = ClientAddress.objects.filter(
            client=client_details, is_active=True
        )
        for ca in client_addresses:
            ClientAddressHistory.objects.create(
                client_address=ca,
                performed_by=client_details,
                action=ClientAddressHistory.ACTION_DEACTIVATED,
                reason="Account deletion",
            )
            # Delete sensitive verification files tied to this address
            verification = getattr(ca, "verification_request", None)
            if verification:
                for f in (
                    verification.proof_of_residence,
                    verification.id_document,
                    verification.liveness_video,
                ):
                    if f:
                        f.delete(save=False)

        client_addresses.update(is_active=False, is_default=False)

        # ---------------- ANONYMIZE CLIENT DETAILS ----------------
        if client_details:
            if client_details.client_pp and client_details.client_pp.name != "default.jpg":
                client_details.client_pp.delete(save=False)

            client_details.first_name = None
            client_details.last_name = None
            client_details.date_of_birth = None
            client_details.client_pp = "default.jpg"
            client_details.is_active = False
            client_details.save(update_fields=[
                "first_name", "last_name", "date_of_birth",
                "client_pp", "is_active",
            ])

        # ---------------- ANONYMIZE + LOCK CLIENT AUTH ----------------
        original_email = client.email_address

        client.email_address = f"deleted-{client.id}@deleted.invalid"
        client.mobile_number = None  # unique=True, null allowed — frees the number
        client.is_active = False
        client.mfa_enabled = False
        client.mfa_secret = None
        client.password = make_password(secrets.token_urlsafe(48))  # unusable
        client.session_version += 1  # kills every existing token everywhere
        client.deleted_at = timezone.now()
        client.save(update_fields=[
            "email_address", "mobile_number", "is_active",
            "mfa_enabled", "mfa_secret", "password",
            "session_version", "deleted_at",
        ])

        transaction.on_commit(
            lambda: send_account_deleted_email.delay(original_email)
        )

    return Response(
        {"message": "Your account has been deleted."},
        status=status.HTTP_200_OK,
    )
 
 
# ---------------------------------------------------------------------------
# Step 1: request a code
# ---------------------------------------------------------------------------
@api_view(["POST"])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([AuthThrottle])
def request_password_reset_otp(request):
    client = request.user
 
    if client.account_locked_until and client.account_locked_until > timezone.now():
        return Response(
            {"error": "Account is temporarily locked. Try again later."},
            status=status.HTTP_403_FORBIDDEN,
        )
 
    # ADAPT: only if ClientAuth tracks it.
    # if not client.email_verified:
    #     return Response({"error": "Email address is not verified."}, status=400)
 
    try:
        with transaction.atomic():
            otp_request, otp = create_client_otp(
                client=client,
                purpose=OTP_PASSWORD_RESET,
            )
            email_address = client.email_address
            transaction.on_commit(
                lambda: send_client_otp_email.delay(
                    email_address, otp, OTP_PASSWORD_RESET
                )
            )
    except OTPCooldownError as exc:
        return Response(
            {
                "error": "Please wait before requesting another code.",
                "retry_after": getattr(exc, "retry_after", None),  # ADAPT
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    except Exception:
        logger.exception("Unexpected error in request_password_reset_otp")
        return Response(
            {"error": "Unable to process request at this time."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
 
    return Response(
        {
            "success": True,
            "message": "A verification code has been sent to your email.",
            "data": {
                "otp_request_id": str(otp_request.request_id),
                "masked_email": _mask_email(client.email_address),
            },
        },
        status=status.HTTP_200_OK,
    )
 
 
# ---------------------------------------------------------------------------
# Step 2: verify the code and set the new password in one atomic call
# ---------------------------------------------------------------------------
@api_view(["POST"])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([ClientOTPThrottle])
def reset_password_with_otp(request):
    try:
        serializer = ResetPasswordWithOTPSerializer(
            data=request.data,
            context={"client": request.user},
        )

        serializer.is_valid(raise_exception=True)

        new_password = serializer.validated_data["new_password"]

        otp = str(request.data.get("otp") or "").strip()
        otp_request_id = request.data.get("otp_request_id")

        if not otp or not otp_request_id:
            return Response(
                {"error": "otp and otp_request_id are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            client = ClientAuth.objects.select_for_update().get(pk=request.user.pk)
            now = timezone.now()

            if client.account_locked_until and client.account_locked_until > now:
                return Response(
                    {"error": ["Account is temporarily locked. Try again later"]},
                    status=status.HTTP_403_FORBIDDEN,
                )

            try:
                otp_request = (
                    ClientOTP.objects.select_for_update()
                    .filter(
                        request_id=otp_request_id,
                        client_id=client.pk,
                        purpose="password_reset",
                    )
                    .first()
                )
            except (DjangoValidationError, ValueError):
                otp_request = None

            if otp_request is None:
                hash_otp("000000")
                return Response(
                    INVALID_OR_EXPIRED,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if otp_request.is_used or otp_request.is_verified:
                hash_otp("000000")
                return Response(
                    INVALID_OR_EXPIRED,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if now >= otp_request.expires_at:
                hash_otp("000000")
                return Response(
                    INVALID_OR_EXPIRED,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if otp_request.attempts >= otp_request.max_attempts:
                hash_otp("000000")
                return Response(
                    {
                        "success": False,
                        "message": "Too many invalid OTP attempts.",
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )

            if not secrets.compare_digest(
                hash_otp(otp),
                otp_request.otp_hash,
            ):
                otp_request.attempts += 1
                otp_request.save(update_fields=["attempts"])

                if otp_request.attempts >= otp_request.max_attempts:
                    return Response(
                        {
                            "success": False,
                            "message": "Too many invalid OTP attempts.",
                        },
                        status=status.HTTP_429_TOO_MANY_REQUESTS,
                    )

                return Response(
                    INVALID_OR_EXPIRED,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if check_password(new_password, client.password):
                return Response(
                    {
                        "error": [
                            "New password cannot be the same as the old password."
                        ]
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

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

            client.password = make_password(new_password)
            client.failed_login_attempts = 0
            client.password_changed_at = now
            client.session_version += 1

            client.save(
                update_fields=[
                    "password",
                    "failed_login_attempts",
                    "password_changed_at",
                    "session_version",
                ]
            )

            email_address = client.email_address

            transaction.on_commit(
                lambda: send_password_changed_email.delay(email_address)
            )

        tokens = generate_client_tokens(client)

        return Response(
            {
                "success": True,
                "message": "Password changed successfully.",
                "access": tokens["access"],
                "refresh": tokens["refresh"],
            },
            status=status.HTTP_200_OK,
        )

    except ValidationError as exc:
        return Response(
            exc.detail,
            status=status.HTTP_400_BAD_REQUEST,
        )

    except Exception:
        logger.exception("Unexpected error in reset_password_with_otp")
        return Response(
            {"error": "Unable to reset password at this time."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )



    

@api_view(["POST"])
@throttle_classes([ClientOTPThrottle])
@authentication_classes([])
@permission_classes([AllowAny])
def reset_client_password(request):

    try:
        new_password = request.data.get("new_password")
        otp = request.data.get("otp")

        if not new_password:
            return Response(
                {"error": "new_password is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not otp:
            return Response(
                {"error": "otp is required"},
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
            return Response({"error": errors}, status=status.HTTP_400_BAD_REQUEST)

        # --------------------------------------------------
        # EXTRACT + VALIDATE VERIFICATION TOKEN FROM HEADER
        # --------------------------------------------------
        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            hash_otp("000000")
            return Response(INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

        raw_verification_token = auth_header[len("Bearer "):].strip()

        try:
            validated_token = AccessToken(raw_verification_token)

        except TokenError:
            hash_otp("000000")
            return Response(INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

        if validated_token.get("purpose") != "password_reset":
            hash_otp("000000")
            return Response(INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

        token_client_id = validated_token.get("client_id")
        token_request_id = validated_token.get("request_id")

        if not token_client_id or not token_request_id:
            hash_otp("000000")
            return Response(INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():

            otp_request = (
                ClientOTP.objects
                .select_for_update()
                .select_related("client")
                .filter(
                    request_id=token_request_id,
                    client_id=token_client_id,
                    purpose="password_reset",
                )
                .first()
            )

            if otp_request is None:
                hash_otp("000000")
                return Response(INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            client = otp_request.client
            now = timezone.now()

            if client.account_locked_until and client.account_locked_until > now:
                remaining_minutes = int(
                    (client.account_locked_until - now).total_seconds() / 60
                )
                return Response(
                    {
                        "error": [
                            f"Account is temporarily locked. Try again later"
                        ]
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

            if otp_request.is_used or otp_request.is_verified:
                hash_otp("000000")
                return Response(INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            if now >= otp_request.expires_at:
                hash_otp("000000")
                return Response(INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            if otp_request.attempts >= otp_request.max_attempts:
                hash_otp("000000")
                return Response(
                    {"success": False, "message": "Too many invalid OTP attempts."},
                    status=status.HTTP_429_TOO_MANY_REQUESTS
                )

            submitted_hash = hash_otp(otp)
            otp_valid = secrets.compare_digest(submitted_hash, otp_request.otp_hash)

            if not otp_valid:
                otp_request.attempts += 1
                otp_request.save(update_fields=["attempts"])

                if otp_request.attempts >= otp_request.max_attempts:
                    return Response(
                        {"success": False, "message": "Too many invalid OTP attempts."},
                        status=status.HTTP_429_TOO_MANY_REQUESTS
                    )

                return Response(INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            # Defense in depth: confirm the OTP row's client actually
            # matches the token's claimed client_id.
            if str(client.id) != str(token_client_id):
                logger.error(
                    "Password reset OTP client mismatch: token=%s otp_row=%s",
                    token_client_id, client.id,
                )
                return Response(INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            # Prevent password reuse
            if check_password(new_password, client.password):
                return Response(
                    {"error": ["New password cannot be the same as the old password."]},
                    status=status.HTTP_400_BAD_REQUEST
                )

            otp_request.is_verified = True
            otp_request.is_used = True
            otp_request.verified_at = now
            otp_request.save(update_fields=["is_verified", "is_used", "verified_at"])

            client.password = make_password(new_password)
            client.failed_login_attempts = 0
            client.account_locked_until = None
            client.password_changed_at = now
            client.session_version += 1
            client.save(update_fields=[
                "password", "failed_login_attempts", "account_locked_until","password_changed_at", "session_version"
            ])

        return Response(
            {"success": True, "message": "Password reset successfully"},
            status=status.HTTP_200_OK
        )

    except Exception:
        logger.exception("Unexpected error in reset_client_password")
        return Response(
            {"error": "Unable to reset password at this time."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    

@api_view(["POST"])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([AuthThrottle])
def change_password(request):
    """
    Change the authenticated client's password.
    Operates ONLY on request.user, with no id taken from the payload (RLS).
    """
    with transaction.atomic():
        # Lock the row so two concurrent changes can't interleave.
        client = ClientAuth.objects.select_for_update().get(pk=request.user.pk)

        serializer = ChangePasswordSerializer(
            data=request.data,
            context={"client": client},
        )
        serializer.is_valid(raise_exception=True)

        client.password = make_password(serializer.validated_data["new_password"])
        client.password_changed_at = timezone.now()
        client.session_version += 1
        client.save(update_fields=["password", "password_changed_at", "session_version"])

        email_address = client.email_address
        transaction.on_commit(
            lambda: send_password_changed_email.delay(email_address)
        )

    # Old sessions are now rejected by the iat check. Issue a fresh pair so
    # THIS device stays logged in. Use the same helper your login view uses.
    tokens = generate_client_tokens(client)  # placeholder: adapt to your login code

    return Response(
        {
            "message": "Password changed successfully.",
            "access": tokens["access"],
            "refresh": tokens["refresh"],
        },
        status=status.HTTP_200_OK,
    )
    
@api_view(['POST'])
@throttle_classes([ClientRegistrationThrottle])
@permission_classes([AllowAny])
def register_client(request):

    ip_address = get_client_ip(request)
    user_agent = get_device_info(request)

    try:
        # --------------------------------------------------
        # NORMALIZE INPUT
        # --------------------------------------------------

        email = (
            request.data.get("email_address", "")
            .lower()
            .strip()
        )

        mobile = request.data.get("mobile_number")

        # --------------------------------------------------
        # DUPLICATE EMAIL
        # --------------------------------------------------

        if email and ClientAuth.objects.filter(
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
                    "message": "Invalid email address."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # --------------------------------------------------
        # SERIALIZER VALIDATION
        # --------------------------------------------------

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

        # Use serializer's validated/normalized values
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
        # Keep this check because of race conditions where
        # another request creates the account between the
        # first check and serializer.save().
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
                    "message": "Invalid email address."
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
                        "Invalid mobile number."
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
                    email_address=email,
                    is_profile_completed="in-email-verification",
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
                        purpose=OTP_EMAIL_VERIFICATION,
                    )
                except OTPCooldownError as e:
                    return Response(
                        {
                            "success": False,
                            "message": f"Please wait {e.retry_after} seconds before requesting another code.",
                        },
                        status=status.HTTP_429_TOO_MANY_REQUESTS,
                    )
                verification_token = generate_email_verification_token(client_auth, otp_request)

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
                        OTP_EMAIL_VERIFICATION,
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
                        "email": mask_email(client_auth.email_address),
                        "requires_email_verification": True,
                        "otp_request_id": str(
                            otp_request.request_id
                        ),
                        "verification_token": verification_token,
                    }
                },
                status=status.HTTP_201_CREATED
            )

        except IntegrityError:
            # This branch is now actually reachable: django.db.IntegrityError
            # is what Postgres/psycopg raises on a real constraint violation
            # (e.g. two concurrent requests racing past the pre-checks above).

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

    
    

INVALID_OR_EXPIRED = {
    "success": False,
    "message": "Invalid or expired verification code.",
}

INVALID_OR_EXPIRED_RESET = {
    "success": False,
    "message": "Invalid or expired verification code. Please go back to login.",
}

@api_view(["POST"])
@throttle_classes([ClientOTPThrottle])
@authentication_classes([]) 
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

    otp = serializer.validated_data["otp"]



    # --------------------------------------------------
    # EXTRACT + VALIDATE VERIFICATION TOKEN FROM HEADER
    # --------------------------------------------------

    auth_header = request.headers.get("Authorization", "")



    if not auth_header.startswith("Bearer "):


        hash_otp("000000")
        return Response(
            INVALID_OR_EXPIRED,
            status=status.HTTP_400_BAD_REQUEST,
        )

    raw_verification_token = auth_header[len("Bearer "):].strip()

  

    try:
        validated_token = AccessToken(raw_verification_token)


    except TokenError as e:


        hash_otp("000000")
        return Response(
            INVALID_OR_EXPIRED,
            status=status.HTTP_400_BAD_REQUEST,
        )

    if validated_token.get("purpose") != "email_verification":


        hash_otp("000000")
        return Response(
            INVALID_OR_EXPIRED,
            status=status.HTTP_400_BAD_REQUEST,
        )

    token_client_id = validated_token.get("client_id")
    token_id = validated_token.get("request_id")



    if not token_client_id or not token_id:


        hash_otp("000000")
        return Response(
            INVALID_OR_EXPIRED,
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:

     

        with transaction.atomic():

      

            otp_request = (
                ClientOTP.objects
                .select_for_update()
                .select_related("client")
                .filter(
                    request_id=token_id,
                    client_id=token_client_id,
                    purpose="email_verification",
                )
                .first()
            )

            if otp_request is None:
               

                return Response(
                    INVALID_OR_EXPIRED,
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
                    INVALID_OR_EXPIRED,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # --------------------------------------------------
            # EXPIRED
            # --------------------------------------------------

            if now >= otp_request.expires_at:


                return Response(
                    INVALID_OR_EXPIRED,
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
                    status=status.HTTP_400_BAD_REQUEST,
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
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                return Response(
                    INVALID_OR_EXPIRED,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # --------------------------------------------------
            # OTP VALID
            # --------------------------------------------------



            user = otp_request.client



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

     

            user.email_verified_at = now
            user.is_profile_completed = "in-details"

            user.save(
                update_fields=[
                    "email_verified_at",
                    "is_profile_completed"
                ]
            )

      

            tokens = generate_client_tokens(user)


        return Response(
            {
                "success": True,
                "message": "Email verified successfully.",
                "data": {
                    "id": user.id,

                    "is_profile_completed": (
                        user.is_profile_completed
                    ),
                    "access_token": tokens["access"],
                    "refresh_token": tokens["refresh"],
                },
            },
            status=status.HTTP_200_OK,
        )

    except Exception as e:



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



@api_view(["POST"])
@authentication_classes([])
@throttle_classes([ClientOTPThrottle])
@permission_classes([AllowAny])
def resend_client_otp(request):

    ip_address = get_client_ip(request)
    user_agent = get_device_info(request)

    try:
        # --------------------------------------------------
        # EXTRACT + VALIDATE VERIFICATION TOKEN FROM HEADER
        # --------------------------------------------------

        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            return Response(
                INVALID_OR_EXPIRED,
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_verification_token = auth_header[len("Bearer "):].strip()

        try:
            # Note: AccessToken() only validates the JWT's own signature/exp,
            # not the OTP row's expires_at — this is fine to decode even if
            # the OTP itself already expired, as long as the JWT hasn't.
            validated_token = AccessToken(raw_verification_token)
        except TokenError:
            return Response(
                INVALID_OR_EXPIRED,
                status=status.HTTP_400_BAD_REQUEST,
            )

        if validated_token.get("purpose") != "email_verification":
            return Response(
                INVALID_OR_EXPIRED,
                status=status.HTTP_400_BAD_REQUEST,
            )

        token_client_id = validated_token.get("client_id")

        if not token_client_id:
            return Response(
                INVALID_OR_EXPIRED_RESET,
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            client_auth = ClientAuth.objects.get(id=token_client_id)
        except ClientAuth.DoesNotExist:
            return Response(
                INVALID_OR_EXPIRED_RESET,
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --------------------------------------------------
        # DON'T RESEND IF ALREADY VERIFIED / COMPLETED
        # --------------------------------------------------
        # A stale-but-still-valid JWT shouldn't be able to spam new OTPs
        # for an account that already finished email verification.

        if client_auth.is_profile_completed != "in-email-verification":
            return Response(
                INVALID_OR_EXPIRED_RESET,
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --------------------------------------------------
        # CREATE + SEND NEW OTP
        # --------------------------------------------------

        try:
            with transaction.atomic():

                try:
                    otp_request, otp = create_client_otp(
                        client=client_auth,
                        purpose=OTP_EMAIL_VERIFICATION,
                    )
                except OTPCooldownError as e:
                    return Response(
                        {
                            "success": False,
                            "message": (
                                f"Please wait {e.retry_after} seconds "
                                "before requesting another code."
                            ),
                        },
                        status=status.HTTP_429_TOO_MANY_REQUESTS,
                    )

                verification_token = generate_email_verification_token(
                    client_auth, otp_request
                )

                transaction.on_commit(
                    lambda: send_client_otp_email.delay(
                        client_auth.email_address,
                        otp,
                        OTP_EMAIL_VERIFICATION,
                    )
                )

            return Response(
                {
                    "success": True,
                    "message": (
                        "A new verification code has been sent "
                        "to your email."
                    ),
                    "data": {
                        "id": client_auth.id,
                        "requires_email_verification": True,
                        "otp_request_id": str(otp_request.request_id),
                        "verification_token": verification_token,
                    },
                },
                status=status.HTTP_200_OK,
            )

        except Exception:
            logger.exception(
                "Resend client OTP failed for client_id=%s",
                token_client_id,
            )
            return Response(
                {
                    "success": False,
                    "message": (
                        "A server error occurred. "
                        "Please try again later."
                    ),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    except Exception:
        logger.exception("Unexpected error in resend_client_otp")
        return Response(
            {
                "success": False,
                "message": (
                    "A server error occurred. "
                    "Please try again later."
                ),
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )





@api_view(["POST"])
@authentication_classes([])
@throttle_classes([ClientOTPThrottle])
@permission_classes([AllowAny])
def resend_client_login_otp(request):

    ip_address = get_client_ip(request)
    user_agent = get_device_info(request)

    try:
        # --------------------------------------------------
        # EXTRACT + VALIDATE VERIFICATION TOKEN FROM HEADER
        # --------------------------------------------------

        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            return Response(
                INVALID_OR_EXPIRED,
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_verification_token = auth_header[len("Bearer "):].strip()

        try:
            # Note: AccessToken() only validates the JWT's own signature/exp,
            # not the OTP row's expires_at — this is fine to decode even if
            # the OTP itself already expired, as long as the JWT hasn't.
            validated_token = AccessToken(raw_verification_token)
        except TokenError:
            return Response(
                INVALID_OR_EXPIRED,
                status=status.HTTP_400_BAD_REQUEST,
            )

        if validated_token.get("purpose") != "login":
            return Response(
                INVALID_OR_EXPIRED,
                status=status.HTTP_400_BAD_REQUEST,
            )

        token_client_id = validated_token.get("client_id")

        if not token_client_id:
            return Response(
                INVALID_OR_EXPIRED_RESET,
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            client_auth = ClientAuth.objects.get(id=token_client_id)
        except ClientAuth.DoesNotExist:
            return Response(
                INVALID_OR_EXPIRED_RESET,
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --------------------------------------------------
        # DON'T RESEND IF ALREADY VERIFIED / COMPLETED
        # --------------------------------------------------
        # A stale-but-still-valid JWT shouldn't be able to spam new OTPs
        # for an account that already finished email verification.

        if client_auth.is_profile_completed == "is_blocked":
            return Response(
                INVALID_OR_EXPIRED_RESET,
                status=status.HTTP_400_BAD_REQUEST,
            )

        # --------------------------------------------------
        # CREATE + SEND NEW OTP
        # --------------------------------------------------

        try:
            with transaction.atomic():

                try:
                    otp_request, otp = create_client_otp(
                        client=client_auth,
                        purpose=OTP_LOGIN,
                    )
                except OTPCooldownError as e:
                    return Response(
                        {
                            "success": False,
                            "message": (
                                f"Please wait {e.retry_after} seconds "
                                "before requesting another code."
                            ),
                        },
                        status=status.HTTP_429_TOO_MANY_REQUESTS,
                    )

                verification_token = generate_email_login_tokenn(
                    client_auth, otp_request
                )

                transaction.on_commit(
                    lambda: send_client_otp_email.delay(
                        client_auth.email_address,
                        otp,
                        OTP_LOGIN,
                    )
                )

            return Response(
                {
                    "success": True,
                    "message": (
                        "A new verification code has been sent "
                        "to your email."
                    ),
                    "data": {
                        "id": client_auth.id,
                        "requires_email_verification": True,
                        "otp_request_id": str(otp_request.request_id),
                        "verification_token": verification_token,
                    },
                },
                status=status.HTTP_200_OK,
            )

        except Exception:
            logger.exception(
                "Resend client OTP failed for client_id=%s",
                token_client_id,
            )
            return Response(
                {
                    "success": False,
                    "message": (
                        "A server error occurred. "
                        "Please try again later."
                    ),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    except Exception:
        logger.exception("Unexpected error in resend_client_otp")
        return Response(
            {
                "success": False,
                "message": (
                    "A server error occurred. "
                    "Please try again later."
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





@api_view(["GET"])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([UserReadThrottle])
def get_provider_qualifications_client(request, provider_id, service_id):

    provider_service = get_object_or_404(
        ProviderService.objects.select_related(
            "provider",
            "provider__sp_profile",
        ),
        provider__sp_profile__id=provider_id,
        service_id=service_id,
        is_active=True,
    )

    qualifications = (
        ProviderQualification.objects.filter(
            provider_service=provider_service,
        )
        .order_by("-uploaded_at")
    )

    serializer = ProviderQualificationReadSerializer(
        qualifications,
        many=True,
        context={"request": request},
    )

    return Response(
        {
            "success": True,
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
                pass

        return Response(
            {"detail": "Logged out successfully"},
            status=status.HTTP_200_OK,
        )

    except Exception:
        
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
    


@api_view(["POST"])
@throttle_classes([AuthThrottle])
@permission_classes([AllowAny])
def client_login(request):

    ip_address = get_client_ip(request)
    user_agent = get_device_info(request)

    try:
        serializer = ClientLoginSerializer(
            data=request.data,
            context={"request": request},
        )

        if not serializer.is_valid():

            ClientLoginHistory.objects.create(
                client=None,
                successful=False,
                identifier=request.data.get("identifier"),
                user_agent=user_agent,
                ip_address=ip_address,
                device_name=request.data.get("device_name"),
            )

            return Response(
                {
                    "success": False,
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # =========================================
        # PASSWORD AUTHENTICATION SUCCESSFUL
        # =========================================

        user = serializer.validated_data["user"]

        if user.is_profile_completed == "in-email-verification":
            try:
                otp_request, otp = create_client_otp(
                    client=user,
                    purpose=OTP_EMAIL_VERIFICATION,
                )
            except OTPCooldownError as e:
                return Response(
                    {
                        "success": False,
                        "message": (
                            f"Please wait {e.retry_after} seconds "
                            "before requesting another code."
                        ),
                    },
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )

            verification_token = generate_email_verification_token(user, otp_request)

            transaction.on_commit(
                lambda: send_client_otp_email.delay(
                    user.email_address,
                    otp,
                    OTP_EMAIL_VERIFICATION,
                )
            )

            return Response(   # <-- this was missing
                {
                    "success": True,
                    "message": (
                        "Please verify your email to complete registration. "
                        "A verification code has been sent to your email."
                    ),
                    "data": {
                        "id": user.id,
                        "is_profile_completed": user.is_profile_completed,
                        "email": mask_email(user.email_address),
                        "requires_email_verification": True,
                        "otp_request_id": str(otp_request.request_id),
                        "verification_token": verification_token,
                    },
                },
                status=status.HTTP_200_OK,
            )
        # Password is correct, but this is NOT
        # yet a completed login.
        #
        # The client must complete OTP verification.

        try:
            otp_request, otp = create_client_otp(
                client=user,
                purpose=OTP_LOGIN,
            )

        except OTPCooldownError as e:
            return Response(
                {
                    "success": False,
                    "message": (
                        f"Please wait {e.retry_after} seconds "
                        "before requesting another code."
                    ),
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # =========================================
        # VERIFICATION SESSION
        # =========================================

        verification_token = generate_email_login_tokenn(
            user,
            otp_request,
        )

        # =========================================
        # SEND OTP AFTER TRANSACTION COMMIT
        # =========================================

        transaction.on_commit(
            lambda: send_client_otp_email.delay(
                user.email_address,
                otp,
                OTP_LOGIN,
            )
        )

        # =========================================
        # OTP PENDING RESPONSE
        # =========================================

        return Response(
            {
                "success": True,
                "message": (
                    "A verification code has been "
                    "sent to your email."
                ),
                "data": {
                    "id": user.id,
                    "is_profile_completed": user.is_profile_completed,
                    "requires_email_verification": True,
                    "otp_request_id": str(
                        otp_request.request_id
                    ),
                    "verification_token": verification_token,
                },
            },
            status=status.HTTP_200_OK,
        )

    except Exception:
        logger.exception(
            "Client login failed unexpectedly"
        )

        ClientLoginHistory.objects.create(
            client=None,
            successful=False,
            identifier=request.data.get("identifier"),
            user_agent=user_agent,
            ip_address=ip_address,
            device_name=request.data.get("device_name"),
        )

        return Response(
            {
                "success": False,
                "message": (
                    "Unable to process login at this time."
                ),
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )



    


@api_view(["POST"])
@throttle_classes([ClientOTPThrottle])
@authentication_classes([])
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

    otp = serializer.validated_data["otp"]

    # --------------------------------------------------
    # EXTRACT + VALIDATE VERIFICATION TOKEN FROM HEADER
    # --------------------------------------------------
    # This is the piece that was missing: the OTP was previously looked
    # up with no reference at all to who the caller is, so any "login"
    # OTP row could be matched against any caller. The token below is
    # the one issued at the password step, scoped to purpose="login"
    # plus a specific client_id/request_id, exactly like email
    # verification already does.

    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):

        hash_otp("000000")
        return Response(
            INVALID_OR_EXPIRED,
            status=status.HTTP_400_BAD_REQUEST,
        )

    raw_verification_token = auth_header[len("Bearer "):].strip()

    try:
        validated_token = AccessToken(raw_verification_token)

    except TokenError:

        hash_otp("000000")
        return Response(
            INVALID_OR_EXPIRED,
            status=status.HTTP_400_BAD_REQUEST,
        )

    if validated_token.get("purpose") != "login":

        hash_otp("000000")
        return Response(
            INVALID_OR_EXPIRED,
            status=status.HTTP_400_BAD_REQUEST,
        )

    token_client_id = validated_token.get("client_id")
    token_request_id = validated_token.get("request_id")

    if not token_client_id or not token_request_id:

        hash_otp("000000")
        return Response(
            INVALID_OR_EXPIRED,
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:

        with transaction.atomic():

            otp_request = (
                ClientOTP.objects
                .select_for_update()
                .select_related("client")
                .filter(
                    request_id=token_request_id,
                    client_id=token_client_id,
                    purpose="login",
                )
                .first()
            )

            # Don't reveal whether the request_id exists.
            if otp_request is None:

                hash_otp("000000")
                return Response(
                    INVALID_OR_EXPIRED,
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

                hash_otp("000000")
                return Response(
                    INVALID_OR_EXPIRED,
                    status=status.HTTP_400_BAD_REQUEST
                )

            # -----------------------------------------
            # OTP EXPIRED
            # -----------------------------------------

            if now >= otp_request.expires_at:

                hash_otp("000000")
                return Response(
                    INVALID_OR_EXPIRED,
                    status=status.HTTP_400_BAD_REQUEST
                )

            # -----------------------------------------
            # TOO MANY ATTEMPTS
            # -----------------------------------------

            if (
                otp_request.attempts
                >= otp_request.max_attempts
            ):

                hash_otp("000000")
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
                    INVALID_OR_EXPIRED,
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

            # Defense in depth: even though the token above was already
            # scoped to token_client_id, confirm the OTP row's client
            # actually matches it before we issue real session tokens.
            if str(user.id) != str(token_client_id):

                logger.error(
                    "Login OTP client mismatch: token=%s otp_row=%s",
                    token_client_id,
                    user.id,
                )

                return Response(
                    INVALID_OR_EXPIRED,
                    status=status.HTTP_400_BAD_REQUEST
                )

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




INVALID_REFRESH = {"detail": "Invalid or expired token."}
SESSION_EXPIRED = {"detail": "Session expired. Please log in again."}


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])  
def client_token_refresh(request):
    raw_refresh = request.data.get("refresh")
    if not raw_refresh:
        return Response(INVALID_REFRESH, status=status.HTTP_401_UNAUTHORIZED)

    try:
        refresh = RefreshToken(raw_refresh)  # verifies signature + expiry
    except TokenError:
        return Response(INVALID_REFRESH, status=status.HTTP_401_UNAUTHORIZED)

    if refresh.get("purpose") or refresh.get("user_type") != "client":
        return Response(INVALID_REFRESH, status=status.HTTP_401_UNAUTHORIZED)

    client = ClientAuth.objects.filter(pk=refresh.get("client_id")).first()
    if client is None:
        return Response(INVALID_REFRESH, status=status.HTTP_401_UNAUTHORIZED)

    if refresh.get("sv", 0) != client.session_version:
        return Response(SESSION_EXPIRED, status=status.HTTP_401_UNAUTHORIZED)

    # Optional: block locked or blocked accounts from refreshing
    if client.is_profile_completed == "is_blocked":
        return Response(SESSION_EXPIRED, status=status.HTTP_401_UNAUTHORIZED)

    # Keep your current behaviour. Access-only, matching the stock view
    # when ROTATE_REFRESH_TOKENS is False:
    return Response({"access": str(refresh.access_token)}, status=status.HTTP_200_OK)



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