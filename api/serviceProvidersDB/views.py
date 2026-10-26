import re
from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
import json
import os
import secrets
import time
from django.db.models import Q, Count
from django.db.models import (
    Case, Count, ExpressionWrapper, F, FloatField, IntegerField,
    OuterRef, Q, Subquery, Value, When,
)
from django.db.models.functions import Cast, Coalesce, Greatest, Least
from django.db.models.functions import ACos, Cos, Radians, Sin

from rest_framework_simplejwt.tokens import AccessToken, RefreshToken
from tokenize import TokenError
from unittest import result
from django.db import DatabaseError, transaction, OperationalError
from django.db import IntegrityError, transaction
from django.forms import ValidationError
from django.shortcuts import get_object_or_404
from django.core.files.storage import default_storage
from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
import logging
from django.db.models.functions import ACos, Cast, Cos, Radians, Sin
from django.db.models import F, Avg, Count, Q, ExpressionWrapper, FloatField, ObjectDoesNotExist, OuterRef, Prefetch, Subquery
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from api.bookings.models import Negotiation, OrderService, Session, Shipment
from api.bookings.utils.choices import ACTIVE_ORDER_STATUSES
from api.clientsDB.models.models import ClientAddress, ClientDetails, DeviceToken
from api.clientsDB.serializers import ClientOTPVerifySerializer
from api.clientsDB.services.client_ip_address_helper import get_client_ip, get_device_info
from api.clientsDB.services.jwt_client_authentication import ClientJWTAuthentication

from api.clientsDB.services.otp_service import hash_otp
from api.clientsDB.services.otp_tasks import OTP_EMAIL_VERIFICATION, OTP_LOGIN, OTP_PASSWORD_RESET, OTPCooldownError
from api.clientsDB.services.sa_phone_number_helper import normalize_sa_mobile
from api.clientsDB.views import BLOCKING_SHIPMENT_STATUSES, INVALID_REFRESH, SESSION_EXPIRED, TERMINAL_ORDER_STATUSES, _mask_email
from api.serviceProvidersDB.services.affidavit_hash_calcultor import calculate_sha256
from api.serviceProvidersDB.services.affidavit_verification_service import AIKYCClient
from api.serviceProvidersDB.services.generate_sp_password_reset_token import generate_sp_password_reset_token
from api.serviceProvidersDB.services.kyc_verification_service import KYCService
from api.serviceProvidersDB.services.otp_utils import create_sp_otp
from api.serviceProvidersDB.services.service_validator import validate_service_submission
from api.serviceProvidersDB.services.sp_jwt_authentication import SPJWTAuthentication
from api.serviceProvidersDB.services.sp_otp_service import generate_sp_email_verification_token, generate_sp_login_token
from api.serviceProvidersDB.services.sp_otp_task import send_sp_account_deleted_email, send_sp_otp_email, send_sp_password_changed_email
from api.serviceProvidersDB.services.sp_profile_flow import PS, advance_profile_status, require_profile_status
from plug_backend import settings
from plug_backend.helpers.auth_helpers import get_service_provider, get_sp_profile
from plug_backend.throttles import AccountDeleteThrottle, AuthThrottle, ClientOTPThrottle, HeavyReadThrottle, LiveLocationReadThrottle, LiveLocationWriteThrottle, ProfileWriteThrottle, RegisterThrottle, UploadThrottle, UserReadThrottle
from plug_backend.utils.sp_jwt_helper import generate_sp_tokens
from .models import SPOTP, CostOfService, CostOfServiceImage, ProviderLoginHistory, ProviderQualification, ProviderRegistrationHistory, ProviderService, ProviderServiceAffidavit, ProviderServiceHistory, SPLiveLocation, SPLocationHistory, SPProfile, ServiceGroup, Service, ServiceProvider, Address, SupportingDocument
from .serializers import (
    ClientSPProfileReadSerializer,
    ClientServiceProviderReadSerializer,
    CostOfServiceImageReadSerializer,
    CostOfServiceImageSerializer,
    CostOfServiceImageWriteSerializer,
    CostOfServiceSerializer,
    DeleteSPAccountSerializer,
    DeviceTokenWriteSerializer,
    ProviderQualificationReadSerializer,
    ProviderQualificationSerializer,
    ProviderServiceAffidavitSerializer,
    ProviderSeviceSerializer,
    ResetSPPasswordWithOTPSerializer,
    SPAddressDocumentWriteSerializer,
    SPChangePasswordSerializer,
    SPCostOfServiceImageReadSerializer,
    SPLiveLocationSerializer,
    SPLoginSerializer,
    SPProfileReadSerializer,
    SPProfileWriteSerializer,
    SPProviderSeviceSerializer,
    ServiceGroupSerializer,
    ServiceProviderMyReadSerializer,
    ServiceProviderPatchSerializer,
    
    ServiceProviderProfileSerializer,
    ServiceProviderReadSerializer,
    ServiceProviderSerializer,
    ServiceProviderWriteSerializer,
    ServiceReadSerializer,
    ServiceSerializer,
    SPAddressSerializer,
    ServiceWriteSerializer,
    UpdateCostOfServiceSerializer
)
from rest_framework.exceptions import ValidationError

logger = logging.getLogger(__name__)  ##do not remove





@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def sp_token_refresh(request):
    raw_refresh = request.data.get("refresh")
    if not raw_refresh:
        return Response(INVALID_REFRESH, status=status.HTTP_401_UNAUTHORIZED)

    try:
        refresh = RefreshToken(raw_refresh)
    except TokenError:
        return Response(INVALID_REFRESH, status=status.HTTP_401_UNAUTHORIZED)

    if refresh.get("purpose") or refresh.get("user_type") != "service_provider":
        return Response(INVALID_REFRESH, status=status.HTTP_401_UNAUTHORIZED)

    sp = SPProfile.objects.filter(pk=refresh.get("sp_id")).first()
    if sp is None:
        return Response(INVALID_REFRESH, status=status.HTTP_401_UNAUTHORIZED)

    if refresh.get("sv", 0) != sp.session_version:
        return Response(SESSION_EXPIRED, status=status.HTTP_401_UNAUTHORIZED)

    if not sp.is_active:
        return Response(SESSION_EXPIRED, status=status.HTTP_401_UNAUTHORIZED)

    return Response({"access": str(refresh.access_token)}, status=status.HTTP_200_OK)

@api_view(["POST"])
@throttle_classes([AuthThrottle])
@permission_classes([AllowAny])
def sp_login(request):
    ip_address = get_client_ip(request)
    user_agent = get_device_info(request)
    # Flutter sends "identifier", so read that first, with "email" as a fallback
    identifier = request.data.get("identifier") or request.data.get("email")
    device_name = request.data.get("device_name")

    try:
        serializer = SPLoginSerializer(
            data=request.data,
            context={"request": request},
        )

        if not serializer.is_valid():
            ProviderLoginHistory.objects.create(
                service_provider=None,
                successful=False,
                identifier=identifier,
                user_agent=user_agent,
                ip_address=ip_address,
                device_name=device_name,
            )

            return Response(
                {"success": False, "errors": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # =========================================
        # PASSWORD AUTHENTICATION SUCCESSFUL
        # =========================================

        sp = serializer.validated_data["user"]
        login_method = serializer.validated_data["login_method"]

        # Block login via mobile number until the number itself is verified.
        # Email login is unaffected.
        if login_method == "mobile_number" and not sp.is_number_verified:

            ProviderLoginHistory.objects.create(
                service_provider=sp,
                successful=False,
                identifier=identifier,
                user_agent=user_agent,
                ip_address=ip_address,
                device_name=device_name,
            )

            return Response(
                {
                    "success": False,
                    "message": (
                        "This mobile number has not been verified yet. "
                        "Please verify your number or log in with your email."
                    ),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # Password is correct, but this is NOT yet a completed login.
        # Unverified accounts get an email-verification OTP and token;
        # everyone else gets a login OTP and token.
        needs_email_verification = (
            sp.is_profile_completed == "in-email-verification"
        )
        otp_purpose = (
            OTP_EMAIL_VERIFICATION if needs_email_verification else OTP_LOGIN
        )

        try:
            otp_request, otp = create_sp_otp(
                service_provider=sp,
                purpose=otp_purpose,
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

        if needs_email_verification:
            verification_token = generate_sp_email_verification_token(
                sp, otp_request
            )
            message = (
                "Please verify your email to complete registration. "
                "A verification code has been sent to your email."
            )
        else:
            verification_token = generate_sp_login_token(sp, otp_request)
            message = "A verification code has been sent to your email."

        transaction.on_commit(
            lambda: send_sp_otp_email.delay(
                sp.email_address,
                otp,
                otp_purpose,
            )
        )

        return Response(
            {
                "success": True,
                "message": message,
                "data": {
                    "id": sp.id,
                    "is_profile_completed": sp.is_profile_completed,
                    "requires_email_verification": needs_email_verification,
                    "otp_request_id": str(otp_request.request_id),
                    "verification_token": verification_token,
                },
            },
            status=status.HTTP_200_OK,
        )

    except Exception:
        logger.exception("SP login failed unexpectedly")

        ProviderLoginHistory.objects.create(
            service_provider=None,
            successful=False,
            identifier=identifier,
            user_agent=user_agent,
            ip_address=ip_address,
            device_name=device_name,
        )

        return Response(
            {"success": False, "message": "Unable to process login at this time."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )



@api_view(["POST"])
@throttle_classes([ClientOTPThrottle])
@authentication_classes([])
@permission_classes([AllowAny])
def verify_sp_login_otp(request):

    ip_address = get_client_ip(request)
    user_agent = get_device_info(request)

    serializer = ClientOTPVerifySerializer(data=request.data)

    if not serializer.is_valid():
        return Response(
            {"success": False, "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    otp = serializer.validated_data["otp"]

    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        hash_otp("000000")
        return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

    raw_verification_token = auth_header[len("Bearer "):].strip()

    try:
        validated_token = AccessToken(raw_verification_token)
    except TokenError:
        hash_otp("000000")
        return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

    if validated_token.get("purpose") != "login":
        hash_otp("000000")
        return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

    token_sp_id = validated_token.get("sp_id")
    token_request_id = validated_token.get("request_id")

    if not token_sp_id or not token_request_id:
        hash_otp("000000")
        return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

    try:
        with transaction.atomic():

            otp_request = (
                SPOTP.objects
                .select_for_update()
                .select_related("service_provider")
                .filter(
                    request_id=token_request_id,
                    service_provider_id=token_sp_id,
                    purpose="login",
                )
                .first()
            )

            if otp_request is None:
                hash_otp("000000")
                return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            now = timezone.now()

            if otp_request.is_used or otp_request.is_verified:
                hash_otp("000000")
                return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            if now >= otp_request.expires_at:
                hash_otp("000000")
                return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            if otp_request.attempts >= otp_request.max_attempts:
                hash_otp("000000")
                return Response(
                    {"success": False, "message": "Too many invalid OTP attempts."},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )

            sp = otp_request.service_provider

            # Demo bypass: only activates if both settings are explicitly
            # configured AND match. Unset/missing settings => always False.
            demo_bypass_email = getattr(settings, "DEMO_BYPASS_EMAIL", None)
            demo_bypass_otp = getattr(settings, "DEMO_BYPASS_OTP", None)

            demo_bypass = bool(
    demo_bypass_email
    and demo_bypass_otp
    and sp.email_address == demo_bypass_email
    and str(otp) == str(demo_bypass_otp)
)

            submitted_hash = hash_otp(otp)
            otp_valid = demo_bypass or secrets.compare_digest(submitted_hash, otp_request.otp_hash)

            if demo_bypass:
                logger.warning(
                    "Demo OTP bypass used for sp_id=%s request_id=%s",
                    sp.id, token_request_id,
                )

            if not otp_valid:
                otp_request.attempts += 1
                otp_request.save(update_fields=["attempts"])

                if otp_request.attempts >= otp_request.max_attempts:
                    return Response(
                        {"success": False, "message": "Too many invalid OTP attempts."},
                        status=status.HTTP_429_TOO_MANY_REQUESTS,
                    )

                return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            otp_request.is_verified = True
            otp_request.is_used = True
            otp_request.verified_at = now
            otp_request.save(update_fields=["is_verified", "is_used", "verified_at"])

            if str(sp.id) != str(token_sp_id):
                logger.error(
                    "Login OTP SP mismatch: token=%s otp_row=%s",
                    token_sp_id, sp.id,
                )
                return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            sp.last_login_at = now
            sp.last_login_ip = ip_address
            sp.failed_login_attempts = 0
            sp.save(update_fields=["last_login_at", "last_login_ip", "failed_login_attempts"])

            ProviderLoginHistory.objects.create(
                service_provider=sp,
                successful=True,
                identifier=sp.email_address,
                user_agent=user_agent,
                ip_address=ip_address,
                device_name=request.data.get("device_name"),
            )

            tokens = generate_sp_tokens(sp)

        return Response(
            {
                "success": True,
                "message": "Login successful.",
                "data": {
                    "id": sp.id,
                    "is_profile_completed": sp.is_profile_completed,
                    "access_token": tokens["access"],
                    "refresh_token": tokens["refresh"],
                },
            },
            status=status.HTTP_200_OK,
        )

    except Exception:
        logger.exception("SP login OTP verification failed unexpectedly")
        return Response(
            {"success": False, "message": "Unable to process OTP verification at this time."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )



@api_view(["POST"])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def sp_update_profile(request):
    # print("FILES RECEIVED:", request.FILES)
    # print("POST DATA:", request.data)

    try:
        service_provider = ServiceProvider.objects.get(
            sp_profile=request.user
        )
    except ServiceProvider.DoesNotExist:
        return Response(
            {
                "success": False,
                "message": "Service provider not found.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    serializer = ServiceProviderProfileSerializer(
        service_provider,
        data=request.data,
        partial=True,
    )

    if not serializer.is_valid():
        return Response(
            {
                "success": False,
                "message": "Validation failed.",
                "errors": serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    serializer.save()  # updated_at is automatically updated

    return Response(
        {
            "success": True,
            "message": "Profile updated successfully.",
            "data": {
                "profile_image": (
                    request.build_absolute_uri(
                        service_provider.profile_image.url
                    )
                    if service_provider.profile_image
                    else None
                ),
                "sp_description": service_provider.sp_description,
                "updated_at": service_provider.updated_at,
            },
        },
        status=status.HTTP_200_OK,
    )




VERIFIED_STATUSES = {"verified", "approved", "success"}


@api_view(["POST"])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@require_profile_status(PS.ADDRESS)
def sp_add_address_document(request):
    ip = get_client_ip(request)
    sp_profile = get_sp_profile(request)

    # Defense in depth: no KYC before the email is verified.
    if sp_profile.email_verified_at is None:
        logger.warning(
            "profile_flow event=status_rejected view=sp_add_address_document "
            "sp=%s reason=email_not_verified ip=%s",
            sp_profile.pk, ip,
        )
        return Response(
            {
                "success": False,
                "message": "Please verify your email first.",
                "current_status": sp_profile.is_profile_completed,
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    address_raw = request.data.get("address")
    if not address_raw:
        return Response(
            {"success": False, "message": "Address data missing"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        address_dict = json.loads(address_raw)
    except (json.JSONDecodeError, TypeError):
        return Response(
            {"success": False, "message": "Invalid address format"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    clean_data = {
        "address": address_dict,
        "id_type": request.data.get("id_type"),
        "front_file": request.FILES.get("front_file"),
        "back_file": request.FILES.get("back_file"),
        "liveness_video": request.FILES.get("liveness_video"),
    }

    liveness = clean_data["liveness_video"]
    logger.debug(
        "profile_flow view=sp_add_address_document sp=%s liveness_received=%s size=%s type=%s",
        sp_profile.pk,
        bool(liveness),
        getattr(liveness, "size", None),
        getattr(liveness, "content_type", None),
    )

    serializer = SPAddressDocumentWriteSerializer(data=clean_data)

    if not serializer.is_valid():
        # Field names only; error text can echo submitted values.
        logger.info(
            "profile_flow event=validation_failed view=sp_add_address_document "
            "sp=%s fields=%s ip=%s",
            sp_profile.pk, list(serializer.errors.keys()), ip,
        )
        return Response(
            {
                "success": False,
                "message": "Please check the submitted information.",
                "errors": serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    def save_temp(file_obj, filename):
        if not file_obj:
            return None
        path = f"temp/{filename}"
        full_path = os.path.join(settings.MEDIA_ROOT, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        file_obj.seek(0)
        with open(full_path, "wb") as dest:
            for chunk in file_obj.chunks():
                dest.write(chunk)
        file_obj.seek(0)
        return full_path

    front_path = back_path = liveness_path = None
    kyc_error = None
    conflict = False

    try:
        with transaction.atomic():
            front_path = save_temp(clean_data["front_file"], f"{sp_profile.pk}_front.jpg")
            back_path = save_temp(clean_data["back_file"], f"{sp_profile.pk}_back.jpg")
            liveness_path = save_temp(clean_data["liveness_video"], f"{sp_profile.pk}_liveness.mp4")

            result = serializer.save(sp_profile=sp_profile)
            service_provider = result["provider"]
            document = result["document"]

            ai_result = KYCService.verify_with_ai(
                customer_id=sp_profile.pk,
                full_name=service_provider.full_name,
                front_path=front_path,
                back_path=back_path,
                selfie_path=liveness_path,
            )

            if not isinstance(ai_result, dict):
                # No verdict to record, so rolling back is correct here.
                raise ValidationError(
                    {"kyc": "Invalid response from AI verification service."}
                )

            api_failed = ai_result.get("success") is False
            verification_status = (ai_result.get("verification_status") or "").lower()
            face_meta = ai_result.get("face_meta") or {}

            logger.info(
                "profile_flow event=kyc_result view=sp_add_address_document "
                "sp=%s api_failed=%s status=%s score=%s",
                sp_profile.pk, api_failed, verification_status,
                ai_result.get("face_match_score"),
            )

            if api_failed or verification_status not in VERIFIED_STATUSES:
                document.ai_response = ai_result
                document.verification_status = "rejected"
                document.verification_score = ai_result.get("face_match_score")
                document.risk_level = (
                    "high" if api_failed else ai_result.get("risk_level", "high")
                )
                document.save(update_fields=[
                    "ai_response", "verification_status",
                    "verification_score", "risk_level",
                ])

                # Not raised: leaving the block normally commits the
                # rejected record. The status stays "in-address".
                kyc_error = {
                    "type": face_meta.get("error_type") or ai_result.get("reason"),
                    "message": (
                        face_meta.get("message")
                        or ai_result.get("message")
                        or "Identity verification failed."
                    ),
                    "details": face_meta.get("details") or ai_result.get("reason"),
                    "score": ai_result.get("face_match_score"),
                }
            else:
                document.ai_response = ai_result
                document.verification_status = "verified"
                document.verification_score = ai_result.get("face_match_score", 0)
                document.risk_level = ai_result.get("risk_level", "low")
                document.save(update_fields=[
                    "ai_response", "verification_status",
                    "verification_score", "risk_level",
                ])

                # in-address -> in-services, only once.
                if not advance_profile_status(sp_profile, PS.ADDRESS):
                    conflict = True
                    transaction.set_rollback(True)

        if conflict:
            logger.warning(
                "profile_flow event=advance_conflict view=sp_add_address_document sp=%s ip=%s",
                sp_profile.pk, ip,
            )
            return Response(
                {"success": False, "message": "This step was already completed."},
                status=status.HTTP_409_CONFLICT,
            )

        if kyc_error:
            logger.warning(
                "profile_flow event=kyc_rejected view=sp_add_address_document "
                "sp=%s type=%s ip=%s",
                sp_profile.pk, kyc_error.get("type"), ip,
            )
            return Response(
                {
                    "success": False,
                    "message": "KYC verification failed.",
                    "errors": {"kyc": kyc_error},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "success": True,
                "message": "Registration completed successfully.",
                "provider_id": service_provider.sp_profile_id,
                "profile_status": sp_profile.is_profile_completed,
                "ai_result": ai_result,
            },
            status=status.HTTP_201_CREATED,
        )

    except ValidationError as e:
        logger.warning(
            "profile_flow event=kyc_invalid_response view=sp_add_address_document sp=%s ip=%s",
            sp_profile.pk, ip,
        )
        return Response(
            {"success": False, "message": "KYC verification failed.", "errors": e.detail},
            status=status.HTTP_400_BAD_REQUEST,
        )

    except Exception:
        logger.exception(
            "profile_flow event=unexpected_error view=sp_add_address_document sp=%s ip=%s",
            sp_profile.pk, ip,
        )
        return Response(
            {"success": False, "message": "Unable to complete registration at this time."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    finally:
        for path in [front_path, back_path, liveness_path]:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                logger.warning("Failed to delete temp file for sp=%s", sp_profile.pk)
                

SP_INVALID_OR_EXPIRED = {
    "success": False,
    "message": "Invalid or expired verification code.",
}


@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([RegisterThrottle])
def sp_register(request):

    email = request.data.get("email_address")
    mobile = request.data.get("mobile_number")

    ip_address = get_client_ip(request)
    user_agent = get_device_info(request)

    serializer = SPProfileWriteSerializer(data=request.data)

    if not serializer.is_valid():

        ProviderRegistrationHistory.objects.create(
            email=email,
            mobile_number=mobile,
            successful=False,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=user_agent,
            error_message=str(serializer.errors),
        )

        return Response(
            {
                "success": False,
                "message": "Validation failed",
                "errors": serializer.errors,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        with transaction.atomic():

            sp_profile = serializer.save(
                is_profile_completed="in-email-verification",
            )

            try:
                otp_request, otp = create_sp_otp(
                    service_provider=sp_profile,
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

            verification_token = generate_sp_email_verification_token(
                sp_profile, otp_request
            )

            ProviderRegistrationHistory.objects.create(
                email=sp_profile.email_address,
                mobile_number=sp_profile.mobile_number,
                successful=True,
                ip_address=ip_address,
                user_agent=user_agent,
                device_name=user_agent,
            )

            transaction.on_commit(
                lambda: send_sp_otp_email.delay(
                    sp_profile.email_address,
                    otp,
                    OTP_EMAIL_VERIFICATION,
                )
            )

        return Response(
            {
                "success": True,
                "message": (
                    "Registration successful. "
                    "A verification code has been sent to your email."
                ),
                "data": {
                    "id": sp_profile.id,
                    "is_profile_completed": sp_profile.is_profile_completed,
                    "requires_email_verification": True,
                    "otp_request_id": str(otp_request.request_id),
                    "verification_token": verification_token,
                },
            },
            status=status.HTTP_201_CREATED,
        )

    except IntegrityError:

        ProviderRegistrationHistory.objects.create(
            email=email,
            mobile_number=mobile,
            successful=False,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=user_agent,
            error_message="Duplicate email or mobile number.",
        )

        logger.warning(
            "Duplicate registration attempt. Email=%s Mobile=%s IP=%s",
            email, mobile, ip_address,
        )

        return Response(
            {
                "success": False,
                "message": "Invalid email or mobile number provided.",
            },
            status=status.HTTP_409_CONFLICT,
        )

    except Exception as e:

        ProviderRegistrationHistory.objects.create(
            email=email,
            mobile_number=mobile,
            successful=False,
            ip_address=ip_address,
            user_agent=user_agent,
            device_name=user_agent,
            error_message=str(e),
        )

        logger.exception(
            "SP Registration failed. Email=%s Mobile=%s IP=%s",
            email, mobile, ip_address,
        )

        return Response(
            {
                "success": False,
                "message": "A server error occurred. Please try again later.",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )



@api_view(["POST"])
@throttle_classes([ClientOTPThrottle])
@authentication_classes([])
@permission_classes([AllowAny])
def verify_sp_email(request):

    ip_address = get_client_ip(request)
    user_agent = get_device_info(request)

    serializer = ClientOTPVerifySerializer(data=request.data)

    if not serializer.is_valid():
        return Response(
            {"success": False, "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    otp = serializer.validated_data["otp"]

    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        hash_otp("000000")
        return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

    raw_verification_token = auth_header[len("Bearer "):].strip()

    try:
        validated_token = AccessToken(raw_verification_token)
    except TokenError:
        hash_otp("000000")
        return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

    if validated_token.get("purpose") != "email_verification":
        hash_otp("000000")
        return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

    token_sp_id = validated_token.get("sp_id")
    token_id = validated_token.get("request_id")

    if not token_sp_id or not token_id:
        hash_otp("000000")
        return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

    try:
        with transaction.atomic():

            otp_request = (
                SPOTP.objects
                .select_for_update()
                .select_related("service_provider")
                .filter(
                    request_id=token_id,
                    service_provider_id=token_sp_id,
                    purpose="email_verification",
                )
                .first()
            )

            if otp_request is None:
                hash_otp("000000")
                return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            now = timezone.now()
            sp = otp_request.service_provider

            # Defense in depth, matching the client flow.
            if str(sp.id) != str(token_sp_id):
                logger.error(
                    "SP email verification mismatch: token=%s otp_row=%s",
                    token_sp_id, sp.id,
                )
                return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            if otp_request.is_used or otp_request.is_verified:
                return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            if now >= otp_request.expires_at:
                return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            # Status gate: only a provider still awaiting email verification
            # may use this endpoint. Same generic error, so callers can't
            # learn which status an account is in.
            if sp.is_profile_completed != PS.EMAIL_VERIFICATION:
                logger.warning(
                    "SP email verification rejected: sp=%s status=%s",
                    sp.id, sp.is_profile_completed,
                )
                hash_otp("000000")  # keep timing similar to the other reject paths
                return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            if otp_request.attempts >= otp_request.max_attempts:
                return Response(
                    {"success": False, "message": "Too many invalid verification code attempts."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            submitted_hash = hash_otp(otp)
            otp_valid = secrets.compare_digest(submitted_hash, otp_request.otp_hash)

            if not otp_valid:
                otp_request.attempts += 1
                otp_request.save(update_fields=["attempts"])

                if otp_request.attempts >= otp_request.max_attempts:
                    return Response(
                        {"success": False, "message": "Too many invalid verification code attempts."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            # Atomic EMAIL_VERIFICATION -> DETAILS. Fails if the row changed
            # underneath us, so the step can't run twice.
            if not advance_profile_status(sp, PS.EMAIL_VERIFICATION):
                return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            otp_request.is_verified = True
            otp_request.is_used = True
            otp_request.verified_at = now
            otp_request.save(update_fields=["is_verified", "is_used", "verified_at"])

            sp.email_verified_at = now
            sp.save(update_fields=["email_verified_at"])  # status already advanced

            tokens = generate_sp_tokens(sp)

        return Response(
            {
                "success": True,
                "message": "Email verified successfully.",
                "data": {
                    "id": sp.id,
                    "is_profile_completed": sp.is_profile_completed,
                    "access_token": tokens["access"],
                    "refresh_token": tokens["refresh"],
                },
            },
            status=status.HTTP_200_OK,
        )

    except Exception:
        logger.exception("SP email verification failed unexpectedly")
        return Response(
            {"success": False, "message": "Unable to verify your email at this time."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    


SP_PASSWORD_RESET_INVALID_OR_EXPIRED = {
    "success": False,
    "message": "Invalid or expired verification code.",
}


@api_view(["POST"])
@throttle_classes([ClientOTPThrottle])
@authentication_classes([])
@permission_classes([AllowAny])
def reset_sp_password(request):

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
        # (same as client, plus a required special character)
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
        if not re.search(r'[^\w\s]', new_password):
            errors.append("Password must contain at least one special character.")

        if errors:
            return Response({"error": errors}, status=status.HTTP_400_BAD_REQUEST)

        # --------------------------------------------------
        # EXTRACT + VALIDATE VERIFICATION TOKEN FROM HEADER
        # --------------------------------------------------
        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            hash_otp("000000")
            return Response(SP_PASSWORD_RESET_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

        raw_verification_token = auth_header[len("Bearer "):].strip()

        try:
            validated_token = AccessToken(raw_verification_token)

        except TokenError:
            hash_otp("000000")
            return Response(SP_PASSWORD_RESET_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

        if validated_token.get("purpose") != "password_reset":
            hash_otp("000000")
            return Response(SP_PASSWORD_RESET_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

        token_sp_id = validated_token.get("sp_id")
        token_request_id = validated_token.get("request_id")

        if not token_sp_id or not token_request_id:
            hash_otp("000000")
            return Response(SP_PASSWORD_RESET_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():

            otp_request = (
                SPOTP.objects
                .select_for_update()
                .select_related("service_provider")
                .filter(
                    request_id=token_request_id,
                    service_provider_id=token_sp_id,
                    purpose="password_reset",
                )
                .first()
            )

            if otp_request is None:
                hash_otp("000000")
                return Response(SP_PASSWORD_RESET_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            sp = otp_request.service_provider
            now = timezone.now()

            if sp.account_locked_until and sp.account_locked_until > now:
                return Response(
                    {
                        "error": [
                            "Account is temporarily locked. Try again later."
                        ]
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

            if otp_request.is_used or otp_request.is_verified:
                hash_otp("000000")
                return Response(SP_PASSWORD_RESET_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            if now >= otp_request.expires_at:
                hash_otp("000000")
                return Response(SP_PASSWORD_RESET_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

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

                return Response(SP_PASSWORD_RESET_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            # Defense in depth: confirm the OTP row's SP actually
            # matches the token's claimed sp_id.
            if str(sp.id) != str(token_sp_id):
                logger.error(
                    "SP password reset OTP mismatch: token=%s otp_row=%s",
                    token_sp_id, sp.id,
                )
                return Response(SP_PASSWORD_RESET_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            # Prevent password reuse
            if check_password(new_password, sp.password):
                return Response(
                    {"error": ["New password cannot be the same as the old password."]},
                    status=status.HTTP_400_BAD_REQUEST
                )

            otp_request.is_verified = True
            otp_request.is_used = True
            otp_request.verified_at = now
            otp_request.save(update_fields=["is_verified", "is_used", "verified_at",])

            sp.password = make_password(new_password)
            sp.failed_login_attempts = 0
            sp.password_changed_at = now
            sp.account_locked_until = None
            sp.save(update_fields=[
                "password", "failed_login_attempts", "account_locked_until", "password_changed_at"
            ])

        return Response(
            {"success": True, "message": "Password reset successfully"},
            status=status.HTTP_200_OK
        )

    except Exception:
        logger.exception("Unexpected error in reset_sp_password")
        return Response(
            {"error": "Unable to reset password at this time."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AuthThrottle])
def request_sp_password_reset(request):

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

        try:
            sp = SPProfile.objects.get(query)

        except SPProfile.DoesNotExist:
            return Response(
                {"error": "Invalid email or mobile number provided."},
                status=status.HTTP_404_NOT_FOUND
            )

        except SPProfile.MultipleObjectsReturned:
            return Response(
                {"error": "Multiple accounts found. Contact support."},
                status=status.HTTP_409_CONFLICT
            )

        if (
            sp.account_locked_until and
            sp.account_locked_until > timezone.now()
        ):
            return Response(
                {
                    "error": [
                        "Account is temporarily locked. Try again later."
                    ]
                },
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            otp_request, otp = create_sp_otp(
                service_provider=sp,
                purpose=OTP_PASSWORD_RESET,
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

        verification_token = generate_sp_password_reset_token(sp, otp_request)

        transaction.on_commit(
            lambda: send_sp_otp_email.delay(
                sp.email_address,
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
        logger.exception("Unexpected error in request_sp_password_reset")
        return Response(
            {"error": "Unable to process request at this time."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["POST"])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([AuthThrottle])
def change_sp_password(request):
    """
    Change the authenticated service provider's password.
    Operates ONLY on request.user, with no id taken from the payload (RLS).
    """
    with transaction.atomic():
        sp = SPProfile.objects.select_for_update().get(pk=request.user.pk)

        serializer = SPChangePasswordSerializer(
            data=request.data,
            context={"sp": sp},
        )
        serializer.is_valid(raise_exception=True)

        sp.password = make_password(serializer.validated_data["new_password"])
        sp.password_changed_at = timezone.now()
        sp.session_version += 1
        sp.save(update_fields=["password", "password_changed_at", "session_version"])

        email_address = sp.email_address
        transaction.on_commit(
            lambda: send_sp_password_changed_email.delay(email_address)
        )

    # Minted AFTER the sv bump — this device stays logged in; every other
    # device's token now fails the sv check immediately.
    tokens = generate_sp_tokens(sp)

    return Response(
        {
            "message": "Password changed successfully.",
            "access": tokens["access"],
            "refresh": tokens["refresh"],
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@throttle_classes([ClientOTPThrottle])
@authentication_classes([])
@permission_classes([AllowAny])
def resend_sp_otp(request):

    auth_header = request.headers.get("Authorization", "")

    if not auth_header.startswith("Bearer "):
        return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

    raw_verification_token = auth_header[len("Bearer "):].strip()

    try:
        validated_token = AccessToken(raw_verification_token)
    except TokenError:
        return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

    purpose = validated_token.get("purpose")

    if purpose not in ("login", "email_verification"):
        return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

    token_sp_id = validated_token.get("sp_id")
    token_request_id = validated_token.get("request_id")

    if not token_sp_id or not token_request_id:
        return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

    try:
        sp = SPProfile.objects.filter(id=token_sp_id).first()

        if sp is None:
            return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

        # -----------------------------------------------------
        # Confirm the original OTP challenge this token was
        # issued for still exists and hasn't already been
        # completed. Without this check, a token from a login
        # that already succeeded (or an email that's already
        # verified) could be replayed indefinitely to spam
        # new codes for that same sp/purpose.
        # -----------------------------------------------------

        original = (
            SPOTP.objects
            .filter(
                request_id=token_request_id,
                service_provider_id=token_sp_id,
                purpose=purpose,
            )
            .first()
        )

        if original is None:
            return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

        if original.is_verified:
            return Response(SP_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

        try:
            otp_request, otp = create_sp_otp(
                service_provider=sp,
                purpose=purpose,
            )
        except OTPCooldownError as e:
            return Response(
                {
                    "success": False,
                    "message": f"Please wait {e.retry_after} seconds before requesting another code.",
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        if purpose == "login":
            verification_token = generate_sp_login_token(sp, otp_request)
        else:
            verification_token = generate_sp_email_verification_token(sp, otp_request)

        transaction.on_commit(
            lambda: send_sp_otp_email.delay(
                sp.email_address,
                otp,
                purpose,
            )
        )

        return Response(
            {
                "success": True,
                "message": "A new verification code has been sent to your email.",
                "data": {
                    "id": sp.id,
                    "is_profile_completed": sp.is_profile_completed,
                    "requires_email_verification": True,
                    "otp_request_id": str(otp_request.request_id),
                    "verification_token": verification_token,
                },
            },
            status=status.HTTP_200_OK,
        )

    except Exception:
        logger.exception("SP OTP resend failed unexpectedly")
        return Response(
            {
                "success": False,
                "message": "Unable to resend verification code at this time.",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    

@api_view(["POST"])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([AuthThrottle])
def request_sp_password_reset_otp(request):
    sp = request.user

    if sp.account_locked_until and sp.account_locked_until > timezone.now():
        return Response(
            {"error": "Account is temporarily locked. Try again later."},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        with transaction.atomic():
            otp_request, otp = create_sp_otp(
                service_provider=sp,
                purpose=OTP_PASSWORD_RESET,
            )
            email_address = sp.email_address
            transaction.on_commit(
                lambda: send_sp_otp_email.delay(
                    email_address, otp, OTP_PASSWORD_RESET
                )
            )
    except OTPCooldownError as exc:
        return Response(
            {
                "error": "Please wait before requesting another code.",
                "retry_after": getattr(exc, "retry_after", None),
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    except Exception:
        logger.exception("Unexpected error in request_sp_password_reset_otp")
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
                "masked_email": _mask_email(sp.email_address),
            },
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([ClientOTPThrottle])
def reset_sp_password_with_otp(request):
    try:
        serializer = ResetSPPasswordWithOTPSerializer(
            data=request.data,
            context={"sp": request.user},
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
            sp = SPProfile.objects.select_for_update().get(pk=request.user.pk)
            now = timezone.now()

            if sp.account_locked_until and sp.account_locked_until > now:
                return Response(
                    {"error": ["Account is temporarily locked. Try again later"]},
                    status=status.HTTP_403_FORBIDDEN,
                )

            otp_request = (
                SPOTP.objects.select_for_update()
                .filter(
                    request_id=otp_request_id,
                    service_provider_id=sp.pk,
                    purpose="password_reset",
                )
                .first()
            )

            if otp_request is None:
                hash_otp("000000")
                return Response(SP_PASSWORD_RESET_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            if otp_request.is_used or otp_request.is_verified:
                hash_otp("000000")
                return Response(SP_PASSWORD_RESET_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            if now >= otp_request.expires_at:
                hash_otp("000000")
                return Response(SP_PASSWORD_RESET_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            if otp_request.attempts >= otp_request.max_attempts:
                hash_otp("000000")
                return Response(
                    {"success": False, "message": "Too many invalid OTP attempts."},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )

            if not secrets.compare_digest(hash_otp(otp), otp_request.otp_hash):
                otp_request.attempts += 1
                otp_request.save(update_fields=["attempts"])

                if otp_request.attempts >= otp_request.max_attempts:
                    return Response(
                        {"success": False, "message": "Too many invalid OTP attempts."},
                        status=status.HTTP_429_TOO_MANY_REQUESTS,
                    )

                return Response(SP_PASSWORD_RESET_INVALID_OR_EXPIRED, status=status.HTTP_400_BAD_REQUEST)

            if check_password(new_password, sp.password):
                return Response(
                    {"error": ["New password cannot be the same as the old password."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            otp_request.is_verified = True
            otp_request.is_used = True
            otp_request.verified_at = now
            otp_request.save(update_fields=["is_verified", "is_used", "verified_at"])

            sp.password = make_password(new_password)
            sp.failed_login_attempts = 0
            sp.password_changed_at = now
            sp.session_version += 1
            sp.save(update_fields=[
                "password", "failed_login_attempts",
                "password_changed_at", "session_version",
            ])

            email_address = sp.email_address
            transaction.on_commit(
                lambda: send_sp_password_changed_email.delay(email_address)
            )

        # Minted AFTER the sv bump — this device stays logged in; every
        # other token (any other device) now fails the sv check.
        tokens = generate_sp_tokens(sp)

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
        return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
    except Exception:
        logger.exception("Unexpected error in reset_sp_password_with_otp")
        return Response(
            {"error": "Unable to reset password at this time."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


    
@api_view(['POST'])
@throttle_classes([RegisterThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def register_device_token(request):
    try:
        serializer = DeviceTokenWriteSerializer(
            data=request.data,
            context={"request": request},
        )

        if not serializer.is_valid():
            return Response(
                {
                    "success": False,
                    "message": "Validation failed",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        device_token = serializer.save()

        return Response(
            {
                "success": True,
                "message": "Device token registered successfully",
                "token_id": device_token.id,
            },
            status=status.HTTP_200_OK,
        )

    except Exception:
        logger.exception("Device token registration failed")

        return Response(
            {
                "success": False,
                "message": "A server error occurred. Please try again later.",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

        

@api_view(["PATCH"])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@require_profile_status(
    PS.DETAILS, PS.ADDRESS, PS.SERVICES, PS.COST, PS.COMPLETED
)
def patch_sp_profile(request):
    sp_profile = request.user
    ip = get_client_ip(request)

    # Defense in depth: details can't be saved before the email is verified.
    if sp_profile.email_verified_at is None:
        logger.warning(
            "profile_flow event=status_rejected view=patch_sp_profile "
            "sp=%s reason=email_not_verified ip=%s",
            sp_profile.id, ip,
        )
        return Response(
            {
                "success": False,
                "message": "Please verify your email first.",
                "current_status": sp_profile.is_profile_completed,
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        service_provider = ServiceProvider.objects.select_related(
            "sp_profile"
        ).get(sp_profile=sp_profile)

    except ServiceProvider.DoesNotExist:
        logger.warning(
            "profile_flow event=not_found view=patch_sp_profile sp=%s ip=%s",
            sp_profile.id, ip,
        )
        return Response(
            {"success": False, "message": "Service Provider profile not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    try:
        serializer = ServiceProviderPatchSerializer(
            service_provider,
            data=request.data,
            partial=True,
            context={"request": request},
        )

        if not serializer.is_valid():
            logger.info(
                "profile_flow event=validation_failed view=patch_sp_profile "
                "sp=%s fields=%s ip=%s",
                sp_profile.id, list(serializer.errors.keys()), ip,
            )
            return Response(
                {
                    "success": False,
                    "message": "Please fix the errors below.",
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            serializer.save()

            if sp_profile.is_profile_completed == PS.DETAILS:
                if not advance_profile_status(sp_profile, PS.DETAILS):

                    sp_profile.refresh_from_db(fields=["is_profile_completed"])

        return Response(
            {
                "success": True,
                "message": "Profile updated successfully.",
                "data": {
                    **serializer.data,
                    "profile_status": sp_profile.is_profile_completed,
                },
            },
            status=status.HTTP_200_OK,
        )

    except Exception:
        logger.exception(
            "profile_flow event=unexpected_error view=patch_sp_profile sp=%s ip=%s",
            sp_profile.id, ip,
        )
        return Response(
            {
                "success": False,
                "message": "A server error occurred. Please try again later.",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    


from django.db.models import Q

@api_view(["GET"])
@authentication_classes([SPJWTAuthentication])
@throttle_classes([HeavyReadThrottle])
@permission_classes([IsAuthenticated])
def approved_services_list(request):
    """
    Return only APPROVED services.
    Supports ?search= for name + active non-prohibited keywords.
    """
    try:
        search = request.query_params.get("search", "").strip()

        qs = (
            Service.objects.filter(review_status="APPROVED")
            .select_related("service_group")
        )

        if search:
            qs = qs.filter(
                Q(service_name__icontains=search)
                | Q(
                    keywords__keyword__icontains=search,
                    keywords__is_active=True,
                    keywords__is_prohibited=False,
                )
            ).distinct()

        services = qs.order_by("service_name")
        serializer = ServiceReadSerializer(services, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    except DatabaseError as e:
        logger.error(f"DB error fetching approved services: {str(e)}")
        return Response(
            {"success": False, "message": "Unable to fetch services at the moment."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except Exception as e:
        logger.error(f"Unexpected error in approved_services_list: {str(e)}")
        return Response(
            {"success": False, "message": "Something went wrong while processing your request."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )



    


@api_view(["POST"])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@require_profile_status(PS.SERVICES, PS.COST, PS.COMPLETED)
def submit_service(request, provider_id):
    sp_profile = request.user
    ip = get_client_ip(request)

    # Ownership: the URL id must be the caller's own profile.
    if str(provider_id) != str(sp_profile.pk):
        logger.warning(
            "profile_flow event=ownership_rejected view=submit_service "
            "sp=%s requested_provider=%s ip=%s",
            sp_profile.pk, provider_id, ip,
        )
        return Response(
            {"error": "Provider not found."},
            status=status.HTTP_404_NOT_FOUND,  # 404, so ids can't be probed
        )

    if sp_profile.email_verified_at is None:
        logger.warning(
            "profile_flow event=status_rejected view=submit_service "
            "sp=%s reason=email_not_verified ip=%s",
            sp_profile.pk, ip,
        )
        return Response(
            {"error": "Please verify your email first.",
             "current_status": sp_profile.is_profile_completed},
            status=status.HTTP_403_FORBIDDEN,
        )

    service_name = (request.data.get("service_name") or "").strip()
    description = request.data.get("description", "")
    service_group_id = request.data.get("service_group")

    if not service_name:
        return Response(
            {"error": "service_name is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        provider = ServiceProvider.objects.select_related("sp_profile").get(
            sp_profile=sp_profile
        )

        validation = validate_service_submission(service_name, description)

        if validation["status"] == "rejected":
            logger.info(
                "profile_flow event=service_rejected view=submit_service sp=%s ip=%s",
                sp_profile.pk, ip,
            )
            return Response(
                {
                    "status": "rejected",
                    "reason": validation.get("reason", "Service violates policy"),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():

            if validation["status"] == "exists":
                service = validation["service"]

                existing = ProviderService.objects.filter(
                    provider=provider, service=service
                ).first()

                if existing and existing.is_active:
                    return Response(
                        {"error": "Service already linked to provider."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                if existing:
                    existing.is_active = True
                    existing.save(update_fields=["is_active"])
                    provider_service = existing
                    action, notes = "reactivated", "Service reactivated by provider."
                    result_status, http_code = "reactivated", status.HTTP_200_OK
                else:
                    provider_service = ProviderService.objects.create(
                        provider=provider, service=service
                    )
                    action, notes = "linked", "Service linked by provider."
                    result_status, http_code = validation["status"], status.HTTP_201_CREATED

            else:
                # "new" / "requires_review": needs a group.
                if not service_group_id:
                    return Response(
                        {"error": "service_group is required for new service."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                service_group = ServiceGroup.objects.select_related("category").get(
                    group_id=service_group_id
                )

                service = Service.objects.create(
                    service_name=service_name.title(),
                    description=description,
                    service_group=service_group,
                    review_status=(
                        "PENDING" if validation["status"] == "requires_review"
                        else "APPROVED"
                    ),
                    risk_level=service_group.category.risk_level,
                )
                provider_service = ProviderService.objects.create(
                    provider=provider, service=service
                )
                action, notes = "linked", "Service linked by provider."
                result_status, http_code = validation["status"], status.HTTP_201_CREATED

            ProviderServiceHistory.objects.create(
                provider_service=provider_service,
                provider=provider,
                service=service,
                action=action,
                notes=notes,
                created_by=request.user,
            )

            # in-services -> in-cost on the first service only. Later
            # statuses are untouched, so adding services never regresses.
            if sp_profile.is_profile_completed == PS.SERVICES:
                if not advance_profile_status(sp_profile, PS.SERVICES):
                    # Concurrent request already advanced it; the service is
                    # saved either way, so just report the real status.
                    sp_profile.refresh_from_db(fields=["is_profile_completed"])

        logger.info(
            "profile_flow event=service_%s view=submit_service sp=%s service=%s ip=%s",
            action, sp_profile.pk, service.pk, ip,
        )

        return Response(
            {
                "id": provider_service.id,
                "status": result_status,
                "is_primary": provider_service.is_primary,
                "service": ServiceReadSerializer(service).data,
                "profile_status": sp_profile.is_profile_completed,
            },
            status=http_code,
        )

    except ServiceProvider.DoesNotExist:
        return Response({"error": "Provider not found."},
                        status=status.HTTP_404_NOT_FOUND)

    except ServiceGroup.DoesNotExist:
        return Response({"error": "Invalid service group."},
                        status=status.HTTP_400_BAD_REQUEST)

    except ValidationError as e:
        message = e.messages[0] if getattr(e, "messages", None) else str(e)
        return Response({"error": message}, status=status.HTTP_400_BAD_REQUEST)

    except IntegrityError:
        logger.exception(
            "profile_flow event=integrity_error view=submit_service sp=%s ip=%s",
            sp_profile.pk, ip,
        )
        return Response({"error": "Request could not be completed."},
                        status=status.HTTP_400_BAD_REQUEST)

    except DatabaseError:
        logger.exception(
            "profile_flow event=database_error view=submit_service sp=%s ip=%s",
            sp_profile.pk, ip,
        )
        return Response({"error": "Service temporarily unavailable."},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)

    except Exception:
        logger.exception(
            "profile_flow event=unexpected_error view=submit_service sp=%s ip=%s",
            sp_profile.pk, ip,
        )
        return Response({"error": "Unexpected server error."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)




@api_view(['POST'])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def a_submit_service(request, provider_id):

    try:
        service_name = request.data.get("service_name")
        description = request.data.get("description", "")
        service_group_id = request.data.get("service_group")

        if not service_name:
            return Response(
                {"error": "service_name is required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Provider lookup
        provider = ServiceProvider.objects.select_related('sp_profile').get(
            sp_profile__id=provider_id
        )

        validation = validate_service_submission(service_name, description)

        if validation["status"] == "rejected":
            return Response({
                "status": "rejected",
                "reason": validation.get("reason", "Service violates policy")
            }, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():

            if validation["status"] == "exists":
                service = validation["service"]

                existing_provider_service = ProviderService.objects.filter(
                    provider=provider,
                    service=service,
                ).first()

                if existing_provider_service:
                    if existing_provider_service.is_active:
                        return Response(
                            {"error": "Service already linked to provider."},
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                    existing_provider_service.is_active = True
                    existing_provider_service.save(update_fields=["is_active"])
                    ProviderServiceHistory.objects.create(
                        provider_service=existing_provider_service,
                        provider=provider,
                        service=service,
                        action="reactivated",
                        notes="Service reactivated by provider.",
                        created_by=request.user,
                    )


                    return Response(
                        {
                            "status": "reactivated",
                            "id": existing_provider_service.id,
                            "is_primary": existing_provider_service.is_primary,
                            "service": ServiceReadSerializer(service).data,
 
                        },
                        status=status.HTTP_200_OK,
                    )

                # First-time link to an already-existing service.
                # No service_group needed -- the service already has one.
                provider_service = ProviderService.objects.create(
                    provider=provider,
                    service=service,
                )
                ProviderServiceHistory.objects.create(
                    provider_service=provider_service,
                    provider=provider,
                    service=service,
                    action="linked",
                    notes="Service linked by provider.",
                    created_by=request.user,
                )



                return Response({
                    "id": provider_service.id,
                    "status": validation["status"],
                    "is_primary": provider_service.is_primary,
                    "service": ServiceReadSerializer(service).data,
                    "profile_status": provider.sp_profile.is_profile_completed,
                }, status=status.HTTP_201_CREATED)

            # --- Only "new" / "requires_review" services get here ---
            # New service requires group
            if not service_group_id:
                return Response(
                    {"error": "service_group is required for new service."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            service_group = ServiceGroup.objects.select_related('category').get(
                group_id=service_group_id
            )

            review_status = (
                "PENDING"
                if validation["status"] == "requires_review"
                else "APPROVED"
            )

            service = Service.objects.create(
                service_name=service_name.strip().title(),
                description=description,
                service_group=service_group,
                review_status=review_status,
                risk_level=service_group.category.risk_level
            )

            provider_service = ProviderService.objects.create(
                provider=provider,
                service=service
            )
            ProviderServiceHistory.objects.create(
                provider_service=provider_service,
                provider=provider,
                service=service,
                action="linked",
                notes="Service linked by provider.",
                created_by=request.user,
            )

            

            return Response({
                "id": provider_service.id,
                "status": validation["status"],
                "is_primary": provider_service.is_primary,
                "service": ServiceReadSerializer(service).data,
                "profile_status": provider.sp_profile.is_profile_completed
            }, status=status.HTTP_201_CREATED)

    except ServiceProvider.DoesNotExist:
        return Response(
            {"error": "Provider not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    except ServiceGroup.DoesNotExist:
        return Response(
            {"error": "Invalid service group."},
            status=status.HTTP_400_BAD_REQUEST
        )

    except ValidationError as e:
        message = (
        e.messages[0]
        if hasattr(e, "messages") and e.messages
        else str(e)
    )
        return Response(
            {"error": message},
        status=status.HTTP_400_BAD_REQUEST,
    )

    except IntegrityError:
        logger.error("Integrity error in submit_service", exc_info=True)
        return Response(
            {"error": "Request could not be completed."},
            status=status.HTTP_400_BAD_REQUEST
        )

    except DatabaseError:
        logger.error("Database error in submit_service", exc_info=True)
        return Response(
            {"error": "Service temporarily unavailable."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )

    except Exception:
        logger.error("Unhandled error in submit_service", exc_info=True)
        return Response(
            {"error": "Unexpected server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    
    

@api_view(["POST"])
@authentication_classes([SPJWTAuthentication])
@throttle_classes([ProfileWriteThrottle])
@permission_classes([IsAuthenticated])
def upload_provider_service_affidavit(request, provider_service_id):

    try:
        provider = ServiceProvider.objects.select_related(
            "sp_profile"
        ).get(
            sp_profile=request.user
        )

    except ServiceProvider.DoesNotExist:
        return Response(
            {
                "success": False,
                "message": "Provider not found.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    # --------------------------------------------
    # Get ProviderService by provider_service_id
    # and ensure it belongs to the authenticated provider
    # --------------------------------------------
    provider_service = ProviderService.objects.filter(
        id=provider_service_id,
        provider=provider,
    ).first()

    if not provider_service:
        return Response(
            {
                "success": False,
                "message": "Service not found.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    # --------------------------------------------
    # Validate affidavit
    # --------------------------------------------
    serializer = ProviderServiceAffidavitSerializer(
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

    

    with transaction.atomic():
       

        uploaded_file = serializer.validated_data["affidavit"]

        # --------------------------------------------
        # AI Verification
        # --------------------------------------------
        ai_result = AIKYCClient.verify_affidavit(
            provider=provider,
            provider_service=provider_service,
            uploaded_file=uploaded_file,
        )
       

        # AI processing failed (OCR/System/etc.)
        if not ai_result["success"]:
            return Response(
                {
                    "success": False,
                    "message": ai_result["message"],
                    "error_type": ai_result["error_type"],
                    "ai_result": ai_result,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # AI rejected the affidavit
        
        if ai_result["verification_status"] not in ("verified", "approved"):
        

            return Response(
                {
                    "success": False,
                    "message": ai_result["message"],
                    "ai_result": ai_result,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Reset file pointer after sending to AI
        uploaded_file.seek(0)

        # --------------------------------------------
        # Calculate SHA256
        # --------------------------------------------
        document_hash = calculate_sha256(uploaded_file)

        uploaded_file.seek(0)

        # --------------------------------------------
        # Prevent duplicate uploads

        # --------------------------------------------

        existing_affidavits = ProviderServiceAffidavit.objects.filter(
    provider_service=provider_service,
)
        if existing_affidavits.exists():
   
            existing_affidavits.delete()     
        
        
        # --------------------------------------------
        # Archive previous affidavit
        # --------------------------------------------
        ProviderServiceAffidavit.objects.filter(
            provider_service=provider_service,
            is_current=True,
        ).update(
            is_current=False
        )

        # --------------------------------------------
        # Determine next version
        # --------------------------------------------
        latest = (
            ProviderServiceAffidavit.objects.filter(
                provider_service=provider_service
            )
            .order_by("-version")
            .first()
        )

        version = 1 if latest is None else latest.version + 1

        # --------------------------------------------
        # Save verified affidavit
        # --------------------------------------------
        affidavit = ProviderServiceAffidavit.objects.create(
    provider_service=provider_service,
    affidavit=uploaded_file,
    version=version,
    is_current=True,
    verification_status=ProviderServiceAffidavit.VerificationStatus.APPROVED,
    document_hash=document_hash,
    original_filename=uploaded_file.name,
    file_size=uploaded_file.size,
    mime_type=getattr(uploaded_file, "content_type", ""),
    ai_confidence=ai_result["confidence_score"],
    ai_result=ai_result,
    verification_engine="Plug AI v1",
)

        # --------------------------------------------
        # Update ProviderService
        # --------------------------------------------
        provider_service.has_uploaded_affidavit = True
        provider_service.is_affidavit_verified = True

        provider_service.save(
            update_fields=[
                "has_uploaded_affidavit",
                "is_affidavit_verified",
            ]
        )

    return Response(
        {
            "success": True,
            "message": ai_result["message"],
            "data": {
                "affidavit_id": affidavit.affidavit_id,
                "version": affidavit.version,
                "verification_status": affidavit.verification_status,
                "confidence_score": ai_result["confidence_score"],
                "verified_at": affidavit.verified_at,
                "ai_result": ai_result,
            },
        },
        status=status.HTTP_201_CREATED,
    )
    

@api_view(["POST"])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([ProfileWriteThrottle])
def upload_provider_qualification(request, service_id):



    try:
        provider = ServiceProvider.objects.select_related(
            "sp_profile"
        ).get(
            sp_profile=request.user
        )

    except ServiceProvider.DoesNotExist:
        return Response(
            {
                "success": False,
                "message": "Provider not found.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    try:
        provider_service = ProviderService.objects.select_related(
            "service"
        ).get(
            provider=provider,
            service_id=service_id,
        )

    except ProviderService.DoesNotExist:
        return Response(
            {
                "success": False,
                "message": "You are not linked to this service.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    serializer = ProviderQualificationSerializer(
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

    qualification = serializer.save(
        provider_service=provider_service
    )

    return Response(
        {
            "success": True,
            "message": "Document uploaded successfully.",
            "data": {
                "id": qualification.id,
                "title": qualification.title,
                "document_type": qualification.document_type,
                "verification_status": qualification.verification_status,
                "verified": qualification.verified,
                "uploaded_at": qualification.uploaded_at,
            },
        },
        status=status.HTTP_201_CREATED,
    )


def _parse_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    return None  # invalid


@api_view(["PATCH"])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@require_profile_status(PS.COST, PS.COMPLETED)
def update_cost_of_service(request, service_id):
    sp_profile = request.user
    ip = get_client_ip(request)

    if sp_profile.email_verified_at is None:
        logger.warning(
            "profile_flow event=status_rejected view=update_cost_of_service "
            "sp=%s reason=email_not_verified ip=%s",
            sp_profile.pk, ip,
        )
        return Response(
            {"error": "Please verify your email first.",
             "current_status": sp_profile.is_profile_completed},
            status=status.HTTP_403_FORBIDDEN,
        )

    # ---- Input validation (before touching the DB) ----
    raw_price = request.data.get("base_price")
    if raw_price is None or str(raw_price).strip() == "":
        return Response({"error": "base_price is required."},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        base_price = Decimal(str(raw_price).strip())
    except (InvalidOperation, ValueError, TypeError):
        return Response({"error": "Base price must be a valid number."},
                        status=status.HTTP_400_BAD_REQUEST)

    if not base_price.is_finite():
        return Response({"error": "Base price must be a valid number."},
                        status=status.HTTP_400_BAD_REQUEST)
    if base_price < 0:
        return Response({"error": "Base price cannot be negative."},
                        status=status.HTTP_400_BAD_REQUEST)
    if base_price < Decimal("35.00"):
        return Response({"error": "Base price cannot be less than R35."},
                        status=status.HTTP_400_BAD_REQUEST)
    if base_price > Decimal("10000.00"):
        return Response({"error": "Base price cannot exceed R10,000."},
                        status=status.HTTP_400_BAD_REQUEST)

    base_price = base_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    negotiable = _parse_bool(request.data.get("negotiable"), default=True)
    if negotiable is None:
        return Response({"error": "negotiable must be true or false."},
                        status=status.HTTP_400_BAD_REQUEST)

    notes = str(request.data.get("notes") or "").strip()[:1000]  # match your field's max_length

    try:
        with transaction.atomic():
            provider = ServiceProvider.objects.get(sp_profile=sp_profile)

            # Existing, active link only. No get_or_create: services are
            # linked through submit_service, which runs the policy checks.
            provider_service = (
                ProviderService.objects
                .select_for_update(of=("self",))
                .select_related("cost_of_service")
                .filter(
                    provider=provider,
                    service__service_id=service_id,
                    is_active=True,
                )
                .first()
            )

            if provider_service is None:
                logger.warning(
                    "profile_flow event=not_linked view=update_cost_of_service "
                    "sp=%s service=%s ip=%s",
                    sp_profile.pk, service_id, ip,
                )
                return Response({"error": "Service not found"},
                                status=status.HTTP_404_NOT_FOUND)

            cost = provider_service.cost_of_service
            if cost is None:
                cost = CostOfService.objects.create(
                    base_price=base_price, negotiable=negotiable, notes=notes
                )
                provider_service.cost_of_service = cost
                provider_service.save(update_fields=["cost_of_service"])
            else:
                cost.base_price = base_price
                cost.negotiable = negotiable
                cost.notes = notes
                cost.save(update_fields=["base_price", "negotiable", "notes"])

            # in-cost -> completed, once. Editing prices later is a plain
            # update and never touches the status.
            if sp_profile.is_profile_completed == PS.COST:
                if not advance_profile_status(sp_profile, PS.COST):
                    # Concurrent request advanced it; the price is saved.
                    sp_profile.refresh_from_db(fields=["is_profile_completed"])

        return Response(
            {
                "success": True,
                "cost_of_service": {
                    "id": cost.id,
                    "base_price": str(cost.base_price),
                    "negotiable": cost.negotiable,
                    "notes": cost.notes,
                },
                "profile_status": sp_profile.is_profile_completed,
            },
            status=status.HTTP_200_OK,
        )

    except ServiceProvider.DoesNotExist:
        return Response({"error": "Provider not found"},
                        status=status.HTTP_404_NOT_FOUND)

    except DatabaseError:
        logger.exception(
            "profile_flow event=database_error view=update_cost_of_service sp=%s ip=%s",
            sp_profile.pk, ip,
        )
        return Response({"error": "Service temporarily unavailable"},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)

    except Exception:
        logger.exception(
            "profile_flow event=unexpected_error view=update_cost_of_service sp=%s ip=%s",
            sp_profile.pk, ip,
        )
        return Response({"error": "Unexpected server error"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)


                        

@api_view(["PATCH"])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@require_profile_status(PS.COMPLETED)
def a_update_cost_of_service(request, service_id):
    sp_profile = request.user
    ip = get_client_ip(request)

    if sp_profile.email_verified_at is None:
        logger.warning(
            "profile_flow event=status_rejected view=a_update_cost_of_service "
            "sp=%s reason=email_not_verified ip=%s",
            sp_profile.pk, ip,
        )
        return Response(
            {"error": "Please verify your email first.",
             "current_status": sp_profile.is_profile_completed},
            status=status.HTTP_403_FORBIDDEN,
        )

    # ---- Input validation (before touching the DB) ----
    raw_price = request.data.get("base_price")
    if raw_price is None or str(raw_price).strip() == "":
        return Response({"error": "base_price is required."},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        base_price = Decimal(str(raw_price).strip())
    except (InvalidOperation, ValueError, TypeError):
        return Response({"error": "Base price must be a valid number."},
                        status=status.HTTP_400_BAD_REQUEST)

    if not base_price.is_finite():
        return Response({"error": "Base price must be a valid number."},
                        status=status.HTTP_400_BAD_REQUEST)
    if base_price < 0:
        return Response({"error": "Base price cannot be negative."},
                        status=status.HTTP_400_BAD_REQUEST)
    if base_price < Decimal("35.00"):
        return Response({"error": "Base price cannot be less than R35."},
                        status=status.HTTP_400_BAD_REQUEST)
    if base_price > Decimal("10000.00"):
        return Response({"error": "Base price cannot exceed R10,000."},
                        status=status.HTTP_400_BAD_REQUEST)

    base_price = base_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    negotiable = _parse_bool(request.data.get("negotiable"), default=True)
    if negotiable is None:
        return Response({"error": "negotiable must be true or false."},
                        status=status.HTTP_400_BAD_REQUEST)

    notes = str(request.data.get("notes") or "").strip()[:1000]  # match the model's max_length

    try:
        with transaction.atomic():
            provider = ServiceProvider.objects.get(sp_profile=sp_profile)

            # Existing, active link only. No get_or_create: services are
            # linked through submit_service, which runs the policy checks.
            provider_service = (
                ProviderService.objects
                .select_for_update(of=("self",))
                .select_related("cost_of_service")
                .filter(
                    provider=provider,
                    service__service_id=service_id,
                    is_active=True,
                )
                .first()
            )

            if provider_service is None:
                logger.warning(
                    "profile_flow event=not_linked view=a_update_cost_of_service "
                    "sp=%s service=%s ip=%s",
                    sp_profile.pk, service_id, ip,
                )
                return Response({"error": "Service not found"},
                                status=status.HTTP_404_NOT_FOUND)

            cost = provider_service.cost_of_service
            if cost is None:
                cost = CostOfService.objects.create(
                    base_price=base_price, negotiable=negotiable, notes=notes
                )
                provider_service.cost_of_service = cost
                provider_service.save(update_fields=["cost_of_service"])
            else:
                cost.base_price = base_price
                cost.negotiable = negotiable
                cost.notes = notes
                cost.save(update_fields=["base_price", "negotiable", "notes"])

        logger.info(
            "profile_flow event=cost_updated view=a_update_cost_of_service "
            "sp=%s service=%s ip=%s",
            sp_profile.pk, service_id, ip,
        )

        return Response(
            {
                "success": True,
                "cost_of_service": {
                    "id": cost.id,
                    "base_price": str(cost.base_price),
                    "negotiable": cost.negotiable,
                    "notes": cost.notes,
                },
                "profile_status": sp_profile.is_profile_completed,
            },
            status=status.HTTP_200_OK,
        )

    except ServiceProvider.DoesNotExist:
        return Response({"error": "Provider not found"},
                        status=status.HTTP_404_NOT_FOUND)

    except DatabaseError:
        logger.exception(
            "profile_flow event=database_error view=a_update_cost_of_service sp=%s ip=%s",
            sp_profile.pk, ip,
        )
        return Response({"error": "Service temporarily unavailable"},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)

    except Exception:
        logger.exception(
            "profile_flow event=unexpected_error view=a_update_cost_of_service sp=%s ip=%s",
            sp_profile.pk, ip,
        )
        return Response({"error": "Unexpected server error"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)



@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def sp_profile_list(request):

    try:

        # =========================
        # GET: list profiles
        # =========================
        if request.method == 'GET':
            profiles = SPProfile.objects.all()
            serializer = SPProfileReadSerializer(profiles, many=True)

            return Response(
                serializer.data,
                status=status.HTTP_200_OK
            )

    except Exception:
        logger.error("Unexpected error in sp_profile_list", exc_info=True)

        return Response(
            {"error": "Unexpected server error"},
            status=status.HTTP_500)


@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def sp_profile_detail(request):

    try:
        profile = request.user

        serializer = SPProfileReadSerializer(profile)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )

    except Exception:
        logger.error("Unexpected error in sp_profile_detail", exc_info=True)

        return Response(
            {"error": "Unexpected server error"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    
    
@api_view(['PATCH'])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def toggle_provider_active(request):

    try:
        provider = ServiceProvider.objects.select_related(
            'sp_profile'
        ).get(sp_profile=request.user)

        provider.is_active = not provider.is_active
        provider.save(update_fields=['is_active'])

        return Response(
            {
                "success": True,
                "message": "Provider active status updated",
                "is_active": provider.is_active,
            },
            status=status.HTTP_200_OK,
        )

    except ServiceProvider.DoesNotExist:
        return Response(
            {
                "success": False,
                "message": "Service provider not found",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    except Exception:
        logger.error("Unexpected error in toggle_provider_active", exc_info=True)

        return Response(
            {
                "success": False,
                "message": "Unexpected server error",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

@api_view(['GET'])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([UserReadThrottle])
def get_provider_services(request, provider_id):

    try:
        provider = get_object_or_404(
    ServiceProvider.objects.select_related("sp_profile"),
    sp_profile=request.user,
    sp_profile__id=provider_id,

)

        provider_services = (
    ProviderService.objects.select_related(
        "service",
        "provider",
        "cost_of_service",
        "provider__sp_profile",
    )
    .filter(
        provider=provider,
        is_active=True,
    )
    .annotate(
        completed_orders=Count(
            "orderservice",
            filter=Q(orderservice__status="completed"),
            distinct=True,
        ),
        average_rating=Avg(
            "orderservice__booking_items__shipments__session__ratings__score"
        ),
        
    )
)

        serializer = SPProviderSeviceSerializer(provider_services, many=True)

        return Response(
            {
                "success": True,
                "count": provider_services.count(),
                "data": serializer.data
            },
            status=status.HTTP_200_OK
        )

    except ServiceProvider.DoesNotExist:
        return Response(
            {
                "success": False,
                "message": "Provider not found."
            },
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
        logger.error("Unexpected error in get_provider_services", exc_info=True)

        return Response(
            {
                "success": False,
                "message": "Unexpected server error"
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(["PATCH"])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([UserReadThrottle])
def provider_update_cost_of_service(request, cost_id):
    try:
        sp_profile = get_sp_profile(request)
        provider = sp_profile.serviceprovider

        # Row-Level Security
        cost = CostOfService.objects.filter(
            pk=cost_id,
            provider_service__provider=provider,
        ).first()

        if cost is None:
            return Response(
                {
                    "success": False,
                    "message": "Cost of service not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = UpdateCostOfServiceSerializer(
            cost,
            data=request.data,
            partial=True,
        )

        if not serializer.is_valid():
            logger.warning(
                "Invalid CostOfService update by provider %s: %s",
                sp_profile.id,
                serializer.errors,
            )

            return Response(
                {
                    "success": False,
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer.save()

        logger.info(
            "Provider %s updated CostOfService %s",
            sp_profile.id,
            cost_id,
        )

        return Response(
            {
                "success": True,
                "message": "Cost of service updated successfully.",
                "data": serializer.data,
            },
            status=status.HTTP_200_OK,
        )

    except ObjectDoesNotExist:
        return Response(
            {
                "success": False,
                "message": "Authenticated provider not found.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    except Exception:
        logger.exception(
            "Unexpected error updating CostOfService %s",
            cost_id,
        )

        return Response(
            {
                "success": False,
                "message": "An unexpected error occurred. Please try again later.",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )



@api_view(["POST"])
@authentication_classes([SPJWTAuthentication])
@throttle_classes([ProfileWriteThrottle])
@permission_classes([IsAuthenticated])
def provider_logout(request):
    refresh_token = request.data.get("refresh")

    if not refresh_token:
        return Response(
            {
                "success": False,
                "message": "Refresh token is required.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        token = RefreshToken(refresh_token)
    except TokenError:
        return Response(
            {
                "success": False,
                "message": "Invalid or expired refresh token.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Only blacklist a token that actually belongs to the caller.
    # Without this check, any authenticated provider could blacklist
    # another provider's refresh token just by having a copy of it
    # (leaked log, shared device, support ticket, etc.), forcing that
    # other provider's session to die.
    #
    # Confirm "sp_id" is the exact claim name set by generate_sp_tokens() —
    # adjust below if it differs.
    token_sp_id = token.get("sp_id")

    if token_sp_id is None or str(token_sp_id) != str(request.user.id):
        logger.warning(
            "provider_logout: refresh token sp_id mismatch. "
            "caller=%s token_sp_id=%s",
            request.user.id,
            token_sp_id,
        )
        return Response(
            {
                "success": False,
                "message": "Invalid or expired refresh token.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        token.blacklist()

        ProviderLoginHistory.objects.create(
            service_provider=request.user,
            event_type="logout",
            successful=True,
            identifier=getattr(request.user, "email_address", None),
            ip_address=get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT"),
        )

        return Response(
            {
                "success": True,
                "message": "Logged out successfully.",
            },
            status=status.HTTP_200_OK,
        )

    except TokenError:
        return Response(
            {
                "success": False,
                "message": "Invalid or expired refresh token.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )


        
    

@api_view(["GET"])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([UserReadThrottle])
def get_provider_qualifications(request, provider_service_id):




    provider_service = get_object_or_404(
        ProviderService.objects.select_related(
            "provider",
            "provider__sp_profile",
        ),
        pk=provider_service_id,
        provider__sp_profile=request.user,
      
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

@api_view(["GET"])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([UserReadThrottle])
def get_provider_qualifications(request, provider_service_id):




    provider_service = get_object_or_404(
        ProviderService.objects.select_related(
            "provider",
            "provider__sp_profile",
        ),
        pk=provider_service_id,
        provider__sp_profile=request.user,
      
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


@api_view(["GET"])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([UserReadThrottle])
def get_cost_of_service_images(request, cost_of_service_id):
    cost_of_service = get_object_or_404(
        CostOfService.objects.select_related(
            "provider_service",
            "provider_service__provider",
            "provider_service__provider__sp_profile",
        ),
        id=cost_of_service_id,
        provider_service__provider__sp_profile=request.user,
  
        provider_service__is_active=True,
    )

    images = (
        cost_of_service.images
        .all()
        .order_by("-uploaded_at")
    )

    serializer = SPCostOfServiceImageReadSerializer(
        images,
        many=True,
        context={"request": request},
    )

    return Response(
        {
            "success": True,
            "count": images.count(),
            "data": serializer.data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["PATCH"])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([ProfileWriteThrottle])
@transaction.atomic
def deactivate_provider_service(request, provider_service_id):

    provider_service = get_object_or_404(
        ProviderService.objects.select_related(
            "provider",
            "provider__sp_profile",
            "service",
            "cost_of_service",
        ),
        id=provider_service_id,
        provider__sp_profile=request.user,
        is_active=True,
    )

    # Primary service cannot be removed
    if provider_service.is_primary:
        return Response(
            {
                "success": False,
                "message": "Your primary service cannot be removed.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # ------------------------------------------------------------------
    # Prevent removal if this service is still involved in active orders
    # ------------------------------------------------------------------

    has_active_orders = OrderService.objects.filter(
        service_required=provider_service.service,
        status__in=ACTIVE_ORDER_STATUSES,
    ).filter(
        Q(provider_for_service=provider_service) |
        Q(invited_providers=provider_service.provider.sp_profile)
    ).distinct().exists()

    if has_active_orders:
        return Response(
            {
                "success": False,
                "message": (
                    "This service cannot be removed because it is still linked "
                    "to one or more active orders."
                ),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # ------------------------------------------------------------------
    # Delete all service images
    # ------------------------------------------------------------------

    if provider_service.cost_of_service:
        for image in provider_service.cost_of_service.images.all():
            if image.image:
                image.image.delete(save=False)
            image.delete()

    # ------------------------------------------------------------------
    # Deactivate service
    # ------------------------------------------------------------------

    provider_service.is_active = False
    provider_service.save(update_fields=["is_active"])

    ProviderServiceHistory.objects.create(
        provider_service=provider_service,
        provider=provider_service.provider,
        service=provider_service.service,
        action="deactivated",
        notes="Service removed by provider.",
    )

    return Response(
        {
            "success": True,
            "message": "Service removed successfully.",
        },
        status=status.HTTP_200_OK,
    )

    

@api_view(['POST'])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def upload_service_images(request, cost_id):

    try:
        provider = ServiceProvider.objects.select_related(
            'sp_profile'
        ).get(sp_profile=request.user)

        cost = CostOfService.objects.select_related(
            'provider_service__provider'
        ).get(
            id=cost_id,
            provider_service__provider=provider
        )

        images = request.FILES.getlist("images")

        if not images:
            return Response(
                {
                    "success": False,
                    "message": "No images provided."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        current_count = cost.images.count()

        if current_count + len(images) > 5:
            return Response(
                {
                    "success": False,
                    "message": f"Maximum 5 images allowed. Currently stored: {current_count}."
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        created_images = []

        with transaction.atomic():
            for image_file in images:
                created_images.append(
                    CostOfServiceImage.objects.create(
                        cost_of_service=cost,
                        image=image_file
                    )
                )

        serializer = CostOfServiceImageReadSerializer(
            created_images,
            many=True,
            context={"request": request}
        )

        return Response(
            {
                "success": True,
                "message": "Images uploaded successfully.",
                "count": len(created_images),
                "images": serializer.data,
            },
            status=status.HTTP_201_CREATED
        )

    except ServiceProvider.DoesNotExist:
        return Response(
            {
                "success": False,
                "message": "Provider not found."
            },
            status=status.HTTP_404_NOT_FOUND
        )

    except CostOfService.DoesNotExist:
        return Response(
            {
                "success": False,
                "message": "Cost of service not found or access denied."
            },
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
        logger.error("Unexpected error in upload_service_images", exc_info=True)

        return Response(
            {
                "success": False,
                "message": "Unexpected server error."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# -------- ServiceGroup --------

@api_view(['GET'])
@authentication_classes([SPJWTAuthentication])
@throttle_classes([HeavyReadThrottle])
@permission_classes([IsAuthenticated])
def service_group_list(request):

    try:

        # =========================
        # GET: list service groups
        # =========================
        if request.method == 'GET':
            groups = ServiceGroup.objects.all()
            serializer = ServiceGroupSerializer(groups, many=True)

            return Response(
                serializer.data,
                status=status.HTTP_200_OK
            )

    except Exception:
        logger.error("Unexpected error in service_group_list", exc_info=True)

        return Response(
            {
                "success": False,
                "message": "Unexpected server error."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([UserReadThrottle])
def service_group_detail(request, group_id):
    try:
        group = ServiceGroup.objects.get(group_id=group_id)
    except ServiceGroup.DoesNotExist:
        return Response({'error': 'Service Group not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = ServiceGroupSerializer(group)
        return Response(serializer.data)




# -------- Service --------


INITIAL_RADIUS_KM = 30.0
MAX_RADIUS_KM = 50.0
EARTH_RADIUS_KM = 6371.0

def _distance_expression(client_lat, client_lon):
    lat = Radians(Cast(F("latitude"), FloatField()))
    lon = Radians(Cast(F("longitude"), FloatField()))
    cos_angle = (
        Sin(Radians(Value(client_lat))) * Sin(lat)
        + Cos(Radians(Value(client_lat))) * Cos(lat)
        * Cos(lon - Radians(Value(client_lon)))
    )
    # Clamp: float error can push this just past 1 when the provider is at the
    # client's exact spot, and ACos would then raise a DB error.
    clamped = Least(Value(1.0), Greatest(Value(-1.0), cos_angle))
    return ExpressionWrapper(ACos(clamped) * EARTH_RADIUS_KM, output_field=FloatField())


def _nearby_provider_count(distance_expr, radius_km):
    """Distinct active providers with a live location within radius, per service."""
    sub = (
        SPLiveLocation.objects
        .filter(
            provider__is_active=True,
            provider__provider_services__is_active=True,
            provider__provider_services__service=OuterRef("pk"),
        )
        .alias(distance_km=distance_expr)
        .filter(distance_km__lte=radius_km)
        .values("provider__provider_services__service")
        .annotate(c=Count("provider", distinct=True))
        .values("c")
    )
    return Coalesce(Subquery(sub, output_field=IntegerField()), 0)


@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def service_list(request):
    try:
        if request.user.is_profile_completed != "completed":
            return Response(
                {
                    "success": False,
                    "code": "profile_incomplete",
                    "message": "Complete your profile to view services.",
                    "profile_status": request.user.is_profile_completed,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        search = request.query_params.get("search", "").strip()

        qs = Service.objects.filter(review_status="APPROVED").select_related("service_group")

        # One query, done once (not per service).
        addr = (
            ClientAddress.objects.select_related("address")
            .filter(client__client_profile=request.user, is_default=True, is_active=True)
            .first()
        )

        if addr:
            dist = _distance_expression(
                float(addr.address.latitude), float(addr.address.longitude)
            )
            qs = qs.annotate(
                _near_30=_nearby_provider_count(dist, INITIAL_RADIUS_KM),
                _near_50=_nearby_provider_count(dist, MAX_RADIUS_KM),
            ).annotate(
                # Same rule as the live-location endpoint: 30 km first,
                # widen to 50 km only if nothing is within 30.
                active_provider_count=Case(
                    When(_near_30__gt=0, then=F("_near_30")),
                    default=F("_near_50"),
                    output_field=IntegerField(),
                )
            )
        else:
            # No default address: keep the old non-location count.
            qs = qs.annotate(
                active_provider_count=Count(
                    "service_providers__provider",
                    filter=Q(service_providers__provider__is_active=True),
                    distinct=True,
                )
            )

        if search:
            qs = qs.filter(
                Q(service_name__icontains=search)
                | Q(
                    keywords__keyword__icontains=search,
                    keywords__is_active=True,
                    keywords__is_prohibited=False,
                )
            ).distinct()

        serializer = ServiceSerializer(qs.order_by("service_name"), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception:
        logger.exception("Unexpected error in service_list")
        return Response(
            {"success": False, "message": "Unexpected server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
# @api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
# @throttle_classes([UserReadThrottle])
# @authentication_classes([SPJWTAuthentication])
# @permission_classes([IsAuthenticated])
# def service_detail(request, pk):
#     try:
#         service = Service.objects.get(pk=pk)
#     except Service.DoesNotExist:
#         return Response({'error': 'Service not found.'}, status=status.HTTP_404_NOT_FOUND)

#     if request.method == 'GET':
#         serializer = ServiceSerializer(service)
#         return Response(serializer.data)

#     elif request.method in ['PUT', 'PATCH']:
#         partial = request.method == 'PATCH'
#         serializer = ServiceSerializer(service, data=request.data, partial=partial)
#         if serializer.is_valid():
#             serializer.save()
#             return Response(serializer.data)
#         return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

#     elif request.method == 'DELETE':
#         service.delete()
#         return Response(status=status.HTTP_204_NO_CONTENT)


# -------- ServiceProvider --------

# @api_view(['GET', 'POST'])
# @throttle_classes([UserReadThrottle])
# @authentication_classes([SPJWTAuthentication])
# @permission_classes([IsAuthenticated])
# def service_provider_list(request):
#     if request.method == 'GET':
#         providers = ServiceProvider.objects.all()
#         serializer = ServiceProviderReadSerializer(providers, many=True)
#         return Response(serializer.data)

#     elif request.method == 'POST':
#         serializer = ServiceProviderWriteSerializer(data=request.data)
#         if serializer.is_valid():
#             serializer.save()
#             return Response(serializer.data, status=status.HTTP_201_CREATED)
#         return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def service_provider_list_service(request):

 

    try:
        service_id = request.query_params.get('service_id')
        search = request.query_params.get('search')
        group_id = request.query_params.get('group_id')

        try:
            limit = int(request.query_params.get('limit', 20))
            limit = min(limit, 50)
        except ValueError:
            limit = 20

        

        # --------------------------------------------------
        # CLIENT LOCATION
        # --------------------------------------------------

        try:
            client_default_address = (
                ClientAddress.objects
                .select_related('address')
                .get(
                    client__client_profile=request.user,
                    is_default=True,
                    is_active=True
                )
            )

            client_lat = float(
                client_default_address.address.latitude
            )

            client_lon = float(
                client_default_address.address.longitude
            )

            

        except ClientAddress.DoesNotExist:

           

            return Response(
                [],
                status=status.HTTP_200_OK
            )

        # --------------------------------------------------
        # DISTANCE CALCULATION
        # --------------------------------------------------

        INITIAL_RADIUS_KM = 30.0
        MAX_RADIUS_KM = 50.0
        EARTH_RADIUS_KM = 6371.0

        distance_expression = ExpressionWrapper(
            ACos(
                Sin(Radians(client_lat))
                * Sin(
                    Radians(
                        Cast(F('latitude'), FloatField())
                    )
                )
                +
                Cos(Radians(client_lat))
                * Cos(
                    Radians(
                        Cast(F('latitude'), FloatField())
                    )
                )
                *
                Cos(
                    Radians(
                        Cast(F('longitude'), FloatField())
                    ) - Radians(client_lon)
                )
            ) * EARTH_RADIUS_KM,
            output_field=FloatField()
        )

        # --------------------------------------------------
        # LIVE LOCATION QUERY
        # --------------------------------------------------

        live_locations = (
            SPLiveLocation.objects
            .select_related(
                'provider',
                'provider__sp_profile'
            )
            .filter(
                provider__is_active=True
            )
            .annotate(
                distance_km=distance_expression
            )
        )

        if service_id:
            live_locations = live_locations.filter(
        provider__provider_services__is_active=True,
        provider__provider_services__service_id=service_id,
    )
        if group_id:
            live_locations = live_locations.filter(
        provider__provider_services__is_active=True,
        provider__provider_services__service__service_group_id=group_id,
    )

        if search:
            live_locations = live_locations.filter(
                Q(
                    provider__sp_profile__first_name__icontains=search
                )
                |
                Q(
                    provider__sp_profile__last_name__icontains=search
                )
            )

        

        providers = list(
            live_locations
            .filter(distance_km__lte=INITIAL_RADIUS_KM)
            .order_by('distance_km')[:limit]
        )

      

        if not providers:

            providers = list(
                live_locations
                .filter(distance_km__lte=MAX_RADIUS_KM)
                .order_by('distance_km')[:limit]
            )

    
        if not providers:

         

            return Response(
                [],
                status=status.HTTP_200_OK
            )

        provider_ids = [
            item.provider_id
            for item in providers
        ]

        

        ordered_providers = [
            item.provider
            for item in providers
        ]

        serializer = ClientServiceProviderReadSerializer(
            ordered_providers,
            many=True
        )

        

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )

    except Exception:

        logger.exception(
            "Unexpected error in service_provider_list_service"
        )

        return Response(
            {
                "success": False,
                "message": "Unexpected server error."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(["POST"])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([UserReadThrottle])
def upload_cost_of_service_image(request, cost_id):
    try:
        sp_profile = get_sp_profile(request)
        provider = sp_profile.serviceprovider

        cost = CostOfService.objects.filter(
            pk=cost_id,
            provider_service__provider=provider,
        ).first()

        if cost is None:
            return Response(
                {
                    "success": False,
                    "message": "Cost of service not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CostOfServiceImageSerializer(
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

        serializer.save(cost_of_service=cost)

        logger.info(
            "Provider %s uploaded image for CostOfService %s",
            sp_profile.id,
            cost_id,
        )

        return Response(
            {
                "success": True,
                "message": "Image uploaded successfully.",
                "data": serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )

    except ObjectDoesNotExist:
        if not serializer.is_valid():
            
            return Response(
                {
                    "success": False,
                    "errors": serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    except Exception:
        logger.exception(
            "Unexpected error uploading service image."
        )

        return Response(
            {
                "success": False,
                "message": "An unexpected error occurred.",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["DELETE"])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([UserReadThrottle])
def delete_provider_qualification(request, qualification_id):
    try:
        sp_profile = get_sp_profile(request)
        provider = sp_profile.serviceprovider

        qualification = ProviderQualification.objects.filter(
            pk=qualification_id,
            provider_service__provider=provider,
        ).first()

        if qualification is None:
            return Response(
                {
                    "success": False,
                    "message": "Qualification not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        qualification.document.delete(save=False)
        qualification.delete()

        logger.info(
            "Provider %s deleted qualification %s",
            sp_profile.id,
            qualification_id,
        )

        return Response(
            {
                "success": True,
                "message": "Qualification deleted successfully.",
            },
            status=status.HTTP_200_OK,
        )

    except ObjectDoesNotExist:
        return Response(
            {
                "success": False,
                "message": "Authenticated provider not found.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    except Exception:
        logger.exception(
            "Unexpected error deleting qualification."
        )

        return Response(
            {
                "success": False,
                "message": "An unexpected error occurred.",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["DELETE"])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([UserReadThrottle])
def delete_cost_of_service_image(request, image_id):
    try:
        sp_profile = get_sp_profile(request)
        provider = sp_profile.serviceprovider

        image = CostOfServiceImage.objects.filter(
            pk=image_id,
            cost_of_service__provider_service__provider=provider,
        ).select_related("cost_of_service").first()

        if image is None:
            return Response(
                {
                    "success": False,
                    "message": "Image not found.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        image_count = CostOfServiceImage.objects.filter(
            cost_of_service=image.cost_of_service,
        ).count()

        if image_count <= 1:
            return Response(
                {
                    "success": False,
                    "message": "At least one service image is required.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        image.image.delete(save=False)
        image.delete()

        logger.info(
            "Provider %s deleted service image %s",
            sp_profile.id,
            image_id,
        )

        return Response(
            {
                "success": True,
                "message": "Image deleted successfully.",
            },
            status=status.HTTP_200_OK,
        )

    except ObjectDoesNotExist:
        return Response(
            {
                "success": False,
                "message": "Authenticated provider not found.",
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    except Exception:
        logger.exception(
            "Unexpected error deleting service image."
        )

        return Response(
            {
                "success": False,
                "message": "An unexpected error occurred.",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    
    
    
MAX_RETRIES = 5
RETRY_DELAY = 0.1  

@api_view(['POST'])
@throttle_classes([LiveLocationWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def update_sp_live_location(request):

    try:
        latitude = request.data.get("latitude")
        longitude = request.data.get("longitude")

        if latitude is None or longitude is None:
            return Response(
                {"error": "latitude and longitude are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            lat = Decimal(str(latitude))
            lon = Decimal(str(longitude))
        except (InvalidOperation, TypeError):
            return Response(
                {"error": "Invalid latitude or longitude format"},
                status=status.HTTP_400_BAD_REQUEST
            )

        provider = get_service_provider(request)

        created = False
        live_location = None

        for attempt in range(MAX_RETRIES):
            try:
                with transaction.atomic():

                    live_location = SPLiveLocation.objects.select_for_update(
                        nowait=True
                    ).filter(provider=provider).first()

                    if live_location and (
                        live_location.latitude == lat and
                        live_location.longitude == lon
                    ):
                        return Response(
                            {
                                "message": "Location unchanged",
                                "data": {
                                    "provider_id": provider.id,
                                    "latitude": str(live_location.latitude),
                                    "longitude": str(live_location.longitude),
                                    "updated_at": live_location.updated_at,
                                }
                            },
                            status=status.HTTP_200_OK
                        )

                    if live_location:
                        live_location.latitude = lat
                        live_location.longitude = lon
                        live_location.save()
                        created = False
                    else:
                        live_location = SPLiveLocation.objects.create(
                            provider=provider,
                            latitude=lat,
                            longitude=lon
                        )
                        created = True

                    SPLocationHistory.objects.create(
                        provider=provider,
                        latitude=lat,
                        longitude=lon,
                    )

                break

            except OperationalError as e:
                if "database is locked" in str(e).lower():
                    time.sleep(RETRY_DELAY)
                    continue

                logger.error("DB operational error in live location", exc_info=True)

                return Response(
                    {"error": "Database error. Try again."},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )

        else:
            return Response(
                {"error": "Service temporarily busy. Please retry."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )

        return Response(
            {
                "message": "Live location updated successfully",
                "created": created,
                "data": {
                    "provider_email": provider.sp_profile.email_address,
                    "latitude": str(live_location.latitude),
                    "longitude": str(live_location.longitude),
                    "updated_at": live_location.updated_at,
                }
            },
            status=status.HTTP_200_OK
        )

    except ServiceProvider.DoesNotExist:
        return Response(
            {"error": "Service provider not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
        logger.error("Unexpected error in update_sp_live_location", exc_info=True)

        return Response(
            {"error": "Unexpected server error"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )




@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def service_provider_detail(request, provider_id):

    try:
        provider = ServiceProvider.objects.select_related(
            "sp_profile"
        ).get(
            sp_profile__id=provider_id
        )

        serializer = ServiceProviderSerializer(provider)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )

    except ServiceProvider.DoesNotExist:
        return Response(
            {"error": "Service Provider not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
        logger.error("Unexpected error in service_provider_detail", exc_info=True)

        return Response(
            {"error": "Unexpected server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    

@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def service_provider_details(request, provider_id):

    try:
        provider = ServiceProvider.objects.select_related(
            "sp_profile",
            "live_location",
        ).get(sp_profile=request.user)

        serializer = ServiceProviderMyReadSerializer(provider)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )

    except ServiceProvider.DoesNotExist:
        return Response(
            {"error": "Service Provider not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    except Exception:
        logger.error(
            "Unexpected error in service_provider_details",
            exc_info=True,
        )

        return Response(
            {"error": "Unexpected server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    
# -------- ServiceProvider Address --------
@api_view(['GET'])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def service_provider_address_detail(request, address_id):

    try:
        provider = get_service_provider(request)

        address = Address.objects.select_related().get(
            id=address_id,
            serviceprovider=provider
        )

        serializer = SPAddressSerializer(address)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )

    except Address.DoesNotExist:
        return Response(
            {
                "success": False,
                "message": "Address not found."
            },
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
        logger.error("Unexpected error in service_provider_address_detail", exc_info=True)

        return Response(
            {
                "success": False,
                "message": "Unexpected server error."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    

@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def service_provider_address(request):

    try:
        provider = get_service_provider(request)

        addresses = Address.objects.filter(
            serviceprovider=provider
        )

        serializer = SPAddressSerializer(addresses, many=True)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )

    except Exception:
        logger.error("Unexpected error in service_provider_address", exc_info=True)

        return Response(
            {"error": "Unexpected server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    

    
@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def providers_by_service(request, service_id):

    try:
        providers = (
            ServiceProvider.objects
            .filter(
                services__service_id=service_id,
                is_active=True  # 🔥 consistent visibility rule
            )
            .select_related("sp_profile")
            .distinct()
            .order_by("sp_profile__id")
        )

        serializer = ServiceProviderReadSerializer(
            providers,
            many=True
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )

    except Exception:
        logger.exception("Unexpected error in providers_by_service")

        return Response(
            {"error": "Unexpected server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    



@api_view(['GET'])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([UserReadThrottle])
def get_cost_of_service_images_by_cost_id(request, cost_id):

    try:
        if not CostOfService.objects.filter(id=cost_id).exists():
            return Response(
                {"error": "Cost of service not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        images = (
            CostOfServiceImage.objects
            .filter(cost_of_service_id=cost_id)
            .order_by('-uploaded_at')
        )

        serializer = CostOfServiceImageReadSerializer(
            images,
            many=True,
            context={'request': request}
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )

    except Exception:
        logger.exception(
            "Unexpected error in get_cost_of_service_images_by_cost_id"
        )

        return Response(
            {"error": "Unexpected server error."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    

@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def costs_by_sp(request, provider_id, service_id=None):

    try:
        sp = ServiceProvider.objects.select_related(
            'sp_profile'
        ).get(
            sp_profile__id=provider_id,
            is_active=True
        )

        provider_services = (
            ProviderService.objects.select_related(
                'service',
                'cost_of_service',
            )
            .filter(
                provider=sp,
                is_active=True,          # Only active linked services
                cost_of_service__isnull=False,
            )
        )

        # ---------------- SINGLE COST ----------------
        if service_id is not None:
            provider_service = provider_services.filter(
                service_id=service_id,
            ).first()

            if not provider_service or not provider_service.cost_of_service:
                return Response(
                    {
                        "detail": "Cost of service not found for this provider and service."
                    },
                    status=status.HTTP_404_NOT_FOUND
                )

            serializer = CostOfServiceSerializer(
                provider_service.cost_of_service
            )

            return Response(serializer.data, status=status.HTTP_200_OK)

        # ---------------- ALL COSTS ----------------
        costs = list(
            provider_services
            .exclude(cost_of_service=None)
            .order_by('service__service_name')
            .values_list('cost_of_service', flat=False)
        )

        # safer fallback (ensures serializer stability)
        costs = [ps.cost_of_service for ps in provider_services if ps.cost_of_service]

        serializer = CostOfServiceSerializer(
            costs,
            many=True
        )

        return Response(serializer.data, status=status.HTTP_200_OK)

    except ServiceProvider.DoesNotExist:
        return Response(
            {"detail": "Service provider not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
        logger.exception("Error fetching provider costs")

        return Response(
            {"detail": "An unexpected server error occurred."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )



@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def fetch_sp_addresses_by_service(request, service_id):

    try:
        Service.objects.get(id=service_id)

        providers = ServiceProvider.objects.filter(
            services__service_id=service_id,
            is_active=True
        )

        addresses = Address.objects.filter(
            serviceprovider__in=providers,
            latitude__isnull=False,
            longitude__isnull=False
        ).distinct()

        serializer = SPAddressSerializer(
            addresses,
            many=True
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )

    except Service.DoesNotExist:
        return Response(
            {"detail": "Service not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    except Exception:
        return Response(
            {"detail": "An unexpected error occurred."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['GET'])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([LiveLocationReadThrottle])
def fetch_sp_live_locations_by_service(request, service_id):

    try:
        # 1. Dynamic Limit Resolution
        try:
            limit = int(request.query_params.get('limit', 6))
            if limit > 10:
                limit = 10
        except ValueError:
            limit = 5
      

        # 2. Fetch Client Coordinates
        try:
            client_default_address = ClientAddress.objects.select_related('address').get(
                client__client_profile=request.user,
                is_default=True,
                is_active=True
            )
            client_lat = float(client_default_address.address.latitude)
            client_lon = float(client_default_address.address.longitude)
           
        except ClientAddress.DoesNotExist:
            
            return Response(
            
                status=status.HTTP_400_BAD_REQUEST
            )

        INITIAL_RADIUS_KM = 30.0
        MAX_RADIUS_KM = 50.0
        EARTH_RADIUS_KM = 6371.0

        distance_expression = ExpressionWrapper(
            ACos(
                Sin(Radians(client_lat)) * Sin(Radians(Cast(F('latitude'), FloatField()))) +
                Cos(Radians(client_lat)) * Cos(Radians(Cast(F('latitude'), FloatField()))) *
                Cos(Radians(Cast(F('longitude'), FloatField())) - Radians(client_lon))
            ) * EARTH_RADIUS_KM,
            output_field=FloatField()
        )

        # 3. Base Query Trace
        
        base_query = (
            SPLiveLocation.objects
            .select_related("provider")
            .filter(
                provider__is_active=True,
                provider__provider_services__is_active=True,
                provider__provider_services__service__service_id=service_id,
            )
            .annotate(distance_km=distance_expression)
        )

    
        pre_filter_count = base_query.count()
   
        
        

        # 4. Range Filtering Traces
        results_list = list(base_query.filter(distance_km__lte=INITIAL_RADIUS_KM).order_by('distance_km')[:limit])
  

        if not results_list:
      
            results_list = list(base_query.filter(distance_km__lte=MAX_RADIUS_KM).order_by('distance_km')[:limit])


        if not results_list:

            return Response({"success": True, "data": []}, status=status.HTTP_200_OK)

       
        serializer = SPLiveLocationSerializer(results_list, many=True)

        return Response({"success": True, "data": serializer.data}, status=status.HTTP_200_OK)

    except Exception as e:

        logger.exception("Unexpected error in fetch_sp_live_locations_by_service")
        return Response(
            {"success": False, "message": "Unable to fetch live locations at this time."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([LiveLocationReadThrottle])
def sps_by_live_location(request):

    ids = request.GET.get('ids')

    if not ids:
        return Response(
            {'error': 'Please provide provider IDs.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    id_list = [int(i) for i in ids.split(',') if i.isdigit()]

    sps = (
        ServiceProvider.objects.filter(
            sp_profile_id__in=id_list,
            is_active=True,
        )
        .select_related(
            "sp_profile",
            "location",
        )
        .prefetch_related(
            Prefetch(
                "provider_services",
                queryset=ProviderService.objects.filter(
                    is_active=True,
                ).select_related("service"),
            )
        )
        .distinct()
    )

    if not sps.exists():
        return Response(
            {'error': 'No active service providers found for the given IDs.'},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = ServiceProviderReadSerializer(
        sps,
        many=True,
        context={'request': request}
    )

    return Response(
        {'service_providers': serializer.data},
        status=status.HTTP_200_OK
    )

    


@api_view(['GET'])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([LiveLocationReadThrottle])
def client_get_sps_by_live_location(request):
    """
    GET: Fetch all active service providers linked to multiple live location IDs.
    Example: /api/service_providersDB/sp-by-live-locations/?ids=1,2,3
    """
    ids = request.GET.get('ids')
    if not ids:
        return Response(
            {'error': 'Please provide live location IDs.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    id_list = [int(i) for i in ids.split(',') if i.isdigit()]

    live_locations = SPLiveLocation.objects.filter(
        id__in=id_list
    ).select_related('provider')

    sps = (
        ServiceProvider.objects.filter(
            sp_profile__in=[loc.provider.sp_profile for loc in live_locations],
            is_active=True,
        )
        .select_related(
            "sp_profile",
            "location",
        )
        .prefetch_related(
            Prefetch(
                "provider_services",
                queryset=ProviderService.objects.filter(
                    is_active=True,
                ).select_related("service"),
            )
        )
        .distinct()
    )

    if not sps.exists():
        return Response(
            {'error': 'No active service providers found for the given live location IDs.'},
            status=status.HTTP_404_NOT_FOUND
        )

    serializer = ServiceProviderReadSerializer(
        sps,
        many=True,
        context={'request': request}
    )

    return Response(
        {'service_providers': serializer.data},
        status=status.HTTP_200_OK
    )



@api_view(["POST"])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
@throttle_classes([AccountDeleteThrottle])
def delete_sp_account(request):
    with transaction.atomic():
        sp = SPProfile.objects.select_for_update().get(pk=request.user.pk)

        serializer = DeleteSPAccountSerializer(data=request.data, context={"sp": sp})
        serializer.is_valid(raise_exception=True)

        service_provider = ServiceProvider.objects.filter(
            sp_profile=sp
        ).select_for_update().first()

        # ---------------- BLOCKING CHECKS ----------------
        # ASSUMPTION: OrderService.provider_for_service -> ProviderService -> provider -> ServiceProvider.
        # Confirm this path matches your actual relations.
        active_orders = OrderService.objects.filter(
            provider_for_service__provider=service_provider
        ).exclude(status__in=TERMINAL_ORDER_STATUSES)

        blocked_session = Session.objects.filter(
            shipment__service_ordered__order__provider_for_service__provider=service_provider,
            session_status="in_session",
        ).exists()

        blocked_shipment = Shipment.objects.filter(
            service_ordered__order__provider_for_service__provider=service_provider,
            shipment_status__in=BLOCKING_SHIPMENT_STATUSES,
        ).exists()

        if blocked_session or blocked_shipment:
            return Response(
                {
                    "error": (
                        "You can't delete your account while a booking is "
                        "in progress. Please wait for the current session "
                        "to finish, or cancel bookings that are in transit "
                        "or have arrived."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        # ---------------- RELEASE ACTIVE ORDERS ASSIGNED TO THIS PROVIDER ----------------
        for order in active_orders:
            Negotiation.objects.filter(
                service_order=order
            ).exclude(
                status__in=["accepted", "rejected", "canceled", "expired"]
            ).update(status="canceled")

            order.provider_for_service = None
            order.status = "cancelled"  # confirm exact terminal string
            order.save(update_fields=["provider_for_service", "status"])

        # ---------------- REMOVE FROM EVERY INVITED-PROVIDERS LIST ----------------
        for order in OrderService.objects.filter(invited_providers=sp):
            order.invited_providers.remove(sp)

        # ---------------- DEACTIVATE SERVICES + DELETE THEIR UPLOADS ----------------
        if service_provider:
            provider_services = ProviderService.objects.filter(provider=service_provider)

            for ps in provider_services:
                for q in ps.qualifications.all():
                    if q.document:
                        q.document.delete(save=False)
                ps.qualifications.all().delete()

                for aff in ps.affidavits.all():
                    if aff.affidavit:
                        aff.affidavit.delete(save=False)
                ps.affidavits.all().delete()

                if ps.cost_of_service:
                    for img in ps.cost_of_service.images.all():
                        if img.image:
                            img.image.delete(save=False)
                    ps.cost_of_service.images.all().delete()

            provider_services.update(is_active=False)

        # ---------------- DELETE ID / LIVENESS DOCUMENTS ----------------
        if service_provider:
            documents = SupportingDocument.objects.filter(provider=service_provider)
            for doc in documents:
                for f in (doc.front_file, doc.back_file, doc.liveness_video):
                    if f:
                        f.delete(save=False)
            documents.delete()

        # ---------------- ANONYMIZE SERVICE PROVIDER ----------------
        if service_provider:
            if service_provider.profile_image:
                service_provider.profile_image.delete(save=False)

            service_provider.full_name = "Deleted Provider"
            service_provider.gender = None
            service_provider.sp_description = None
            service_provider.profile_image = None
            service_provider.is_active = False
            service_provider.save(update_fields=[
                "full_name", "gender", "sp_description",
                "profile_image", "is_active",
            ])

        # ---------------- ANONYMIZE + LOCK SP AUTH ----------------
        original_email = sp.email_address

        sp.email_address = f"deleted-sp-{sp.id}@deleted.invalid"
        sp.mobile_number = None
        sp.is_active = False
        sp.mfa_enabled = False
        sp.mfa_secret = None
        sp.password = make_password(secrets.token_urlsafe(48))
        sp.session_version += 1  # same "blacklist" mechanism as client deletion
        sp.deleted_at = timezone.now()
        sp.save(update_fields=[
            "email_address", "mobile_number", "is_active",
            "mfa_enabled", "mfa_secret", "password",
            "session_version", "deleted_at",
        ])

        transaction.on_commit(
            lambda: send_sp_account_deleted_email.delay(original_email)
        )

    return Response(
        {"message": "Your account has been deleted."},
        status=status.HTTP_200_OK,
    )