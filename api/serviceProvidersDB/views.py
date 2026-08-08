from datetime import timezone
from decimal import Decimal, InvalidOperation
import json
import os
import time
from rest_framework_simplejwt.tokens import RefreshToken
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
from api.bookings.models import OrderService
from api.bookings.utils.choices import ACTIVE_ORDER_STATUSES
from api.clientsDB.models.models import ClientAddress, ClientDetails, DeviceToken
from api.clientsDB.services.client_ip_address_helper import get_client_ip, get_device_info
from api.clientsDB.services.jwt_client_authentication import ClientJWTAuthentication

from api.serviceProvidersDB.services.affidavit_hash_calcultor import calculate_sha256
from api.serviceProvidersDB.services.affidavit_verification_service import AIKYCClient
from api.serviceProvidersDB.services.kyc_verification_service import KYCService
from api.serviceProvidersDB.services.service_validator import validate_service_submission
from api.serviceProvidersDB.services.sp_jwt_authentication import SPJWTAuthentication
from plug_backend import settings
from plug_backend.helpers.auth_helpers import get_service_provider, get_sp_profile
from plug_backend.throttles import AuthThrottle, HeavyReadThrottle, LiveLocationReadThrottle, LiveLocationWriteThrottle, ProfileWriteThrottle, RegisterThrottle, UploadThrottle, UserReadThrottle
from plug_backend.utils.sp_jwt_helper import generate_sp_tokens
from .models import CostOfService, CostOfServiceImage, ProviderLoginHistory, ProviderQualification, ProviderRegistrationHistory, ProviderService, ProviderServiceAffidavit, ProviderServiceHistory, SPLiveLocation, SPLocationHistory, SPProfile, ServiceGroup, Service, ServiceProvider, Address
from .serializers import (
    ClientSPProfileReadSerializer,
    ClientServiceProviderReadSerializer,
    CostOfServiceImageReadSerializer,
    CostOfServiceImageSerializer,
    CostOfServiceImageWriteSerializer,
    CostOfServiceSerializer,
    DeviceTokenWriteSerializer,
    ProviderQualificationReadSerializer,
    ProviderQualificationSerializer,
    ProviderServiceAffidavitSerializer,
    ProviderSeviceSerializer,
    SPAddressDocumentWriteSerializer,
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




@api_view(['POST'])
@throttle_classes([AuthThrottle])
@permission_classes([AllowAny])
def sp_login(request):

    ip_address = get_client_ip(request)
    user_agent = get_device_info(request)

    try:
        serializer = SPLoginSerializer(
            data=request.data,
            context={"request": request}
        )

        if serializer.is_valid():

            sp = serializer.validated_data["user"]

            # 🔐 LOG SUCCESSFUL LOGIN
            ProviderLoginHistory.objects.create(
                service_provider=sp,
                successful=True,
                identifier=request.data.get("email"),
                user_agent=user_agent,
                ip_address=ip_address,
                device_name=request.data.get("device_name")
            )

            tokens = generate_sp_tokens(sp)

            return Response(
                {
                    "success": True,
                    "message": "Login successful",
                    "data": {
                        "id": sp.id,
                        "is_profile_completed": sp.is_profile_completed,
                        "access_token": tokens["access"],
                        "refresh_token": tokens["refresh"],
                    }
                },
                status=status.HTTP_200_OK
            )

        # 🔐 LOG FAILED LOGIN
        ProviderLoginHistory.objects.create(
            service_provider=None,
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

        logger.exception("SP login failed unexpectedly")

        # 🔐 LOG SYSTEM FAILURE
        ProviderLoginHistory.objects.create(
            service_provider=None,
            successful=False,
            identifier=request.data.get("email"),
            user_agent=user_agent,
            ip_address=ip_address,
            device_name=request.data.get("device_name")
        )

        return Response(
            {
                "success": False,
                "message": "Unable to process login at this time."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    




@api_view(["POST"])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def sp_update_profile(request):
    print("FILES RECEIVED:", request.FILES)
    print("POST DATA:", request.data)

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




@api_view(["POST"])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def sp_add_address_document(request):
    print("FILES RECEIVED:", request.FILES)
    print("POST DATA:", request.data)
    address_raw = request.data.get("address")

    if not address_raw:
        return Response(
            {
                "success": False,
                "message": "Address data missing",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        address_dict = json.loads(address_raw)
    except (json.JSONDecodeError, TypeError):
        return Response(
            {
                "success": False,
                "message": "Invalid address format",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    sp_profile = get_sp_profile(request)

    clean_data = {
        "address": address_dict,
        "id_type": request.data.get("id_type"),
        "front_file": request.FILES.get("front_file"),
        "back_file": request.FILES.get("back_file"),
        "liveness_video": request.FILES.get("liveness_video"),
    }

    liveness = request.FILES.get("liveness_video")

    if liveness:
        print("Liveness name:", liveness.name)
        print("Liveness size:", liveness.size)
        print("Content type:", liveness.content_type)
    else:
        print("No liveness video received")

    serializer = SPAddressDocumentWriteSerializer(data=clean_data)

    if not serializer.is_valid():
        logger.warning(
            "SP address document validation failed: %s",
            serializer.errors
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
        """
        Copies the uploaded file's bytes to a temp path WITHOUT
        touching/moving/renaming the original uploaded file object,
        so it remains fully readable/saveable afterward (e.g. by
        the serializer's model save).
        """
        if not file_obj:
            return None

        path = f"temp/{filename}"
        full_path = os.path.join(settings.MEDIA_ROOT, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        file_obj.seek(0)
        with open(full_path, "wb") as dest:
            for chunk in file_obj.chunks():
                dest.write(chunk)

        file_obj.seek(0)  # reset for whoever reads it next
        return full_path

    front_path = back_path = liveness_path = None

    try:
        with transaction.atomic():

            # ----------------------------------
            # Save temp files FIRST — copies bytes only,
            # doesn't move/consume the original file objects
            # ----------------------------------
            front_path = save_temp(
                clean_data["front_file"],
                f"{sp_profile.pk}_front.jpg"
            )

            back_path = save_temp(
                clean_data["back_file"],
                f"{sp_profile.pk}_back.jpg"
            )

            liveness_path = save_temp(
                clean_data["liveness_video"],
                f"{sp_profile.pk}_liveness.mp4"
            )

            # ----------------------------------
            # Now save provider + document
            # (safe: original file objects are untouched)
            # ----------------------------------
            result = serializer.save(sp_profile=sp_profile)

            service_provider = result["provider"]
            document = result["document"]

            # ----------------------------------
            # Call AI
            # ----------------------------------
            ai_result = KYCService.verify_with_ai(
                customer_id=service_provider.sp_profile.pk,
                full_name=service_provider.full_name,
                front_path=front_path,
                back_path=back_path,
                selfie_path=liveness_path,
            )

            logger.info("AI RESULT: %s", ai_result)

            if not isinstance(ai_result, dict):
                raise ValidationError(
                    {
                        "kyc": "Invalid response from AI verification service."
                    }
                )

            # ----------------------------------
            # HTTP/API failure
            # ----------------------------------
            if ai_result.get("success") is False:

                document.ai_response = ai_result
                document.verification_status = "rejected"
                document.risk_level = "high"
                document.verification_score = ai_result.get("face_match_score")

                document.save(update_fields=[
                    "ai_response",
                    "verification_status",
                    "verification_score",
                    "risk_level",
                ])

                face_meta = ai_result.get("face_meta", {})

                raise ValidationError({
                    "kyc": {
                        "type": face_meta.get("error_type") or ai_result.get("reason"),
                        "message": (
                            face_meta.get("message")
                            or ai_result.get("message")
                            or "Identity verification failed."
                        ),
                        "details": face_meta.get("details") or ai_result.get("reason"),
                        "score": ai_result.get("face_match_score"),
                    }
                })

            # ----------------------------------
            # Verification failed
            # ----------------------------------
            verification_status = ai_result.get(
                "verification_status",
                ""
            ).lower()

            if verification_status not in ["verified", "approved", "success"]:

                document.ai_response = ai_result
                document.verification_status = "rejected"
                document.verification_score = ai_result.get(
                    "face_match_score"
                )
                document.risk_level = ai_result.get(
                    "risk_level",
                    "high"
                )

                document.save(update_fields=[
                    "ai_response",
                    "verification_status",
                    "verification_score",
                    "risk_level",
                ])

                face_meta = ai_result.get("face_meta", {})

                raise ValidationError({
                    "kyc": {
                        "type": face_meta.get("error_type"),
                        "message": face_meta.get(
                            "message",
                            "Identity verification failed."
                        ),
                        "details": face_meta.get("details"),
                        "score": ai_result.get("face_match_score"),
                    }
                })

            # ----------------------------------
            # SUCCESS
            # ----------------------------------
            document.ai_response = ai_result
            document.verification_status = "verified"
            document.verification_score = ai_result.get(
                "face_match_score",
                0
            )
            document.risk_level = ai_result.get(
                "risk_level",
                "low"
            )

            document.save(update_fields=[
                "ai_response",
                "verification_status",
                "verification_score",
                "risk_level",
            ])

            sp_profile = service_provider.sp_profile
            sp_profile.is_profile_completed = "in-services"
            sp_profile.save(update_fields=[
                "is_profile_completed"
            ])

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

        logger.warning("KYC validation failed: %s", e.detail)

        return Response(
            {
                "success": False,
                "message": "KYC verification failed.",
                "errors": e.detail,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    except Exception:

        logger.exception(
            "Failed to complete SP address document registration"
        )

        return Response(
            {
                "success": False,
                "message": "Unable to complete registration at this time.",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    finally:
        # Cleanup temp files
        for path in [front_path, back_path, liveness_path]:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except Exception:
                logger.warning("Failed to delete temp file %s", path)

                

@api_view(["POST"])
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
                is_profile_completed="in-details"
            )

            tokens = generate_sp_tokens(sp_profile)

            ProviderRegistrationHistory.objects.create(
                email=sp_profile.email_address,
                mobile_number=sp_profile.mobile_number,
                successful=True,
                ip_address=ip_address,
                user_agent=user_agent,
                device_name=user_agent,
            )

        return Response(
            {
                "success": True,
                "message": "Service Provider registered successfully.",
                "data": {
                    "id": sp_profile.id,
                    "profile_status": sp_profile.is_profile_completed,
                    "access_token": tokens["access"],
                    "refresh_token": tokens["refresh"],
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
            email,
            mobile,
            ip_address,
        )

        return Response(
            {
                "success": False,
                "message": "An account with this email or mobile already exists.",
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
            email,
            mobile,
            ip_address,
        )

        return Response(
            {
                "success": False,
                "message": "A server error occurred. Please try again later.",
            },
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
def patch_sp_profile(request):

    try:
        service_provider = ServiceProvider.objects.select_related(
            'sp_profile'
        ).get(sp_profile=request.user)

    except ServiceProvider.DoesNotExist:
        return Response({
            "success": False,
            "message": "Service Provider profile not found."
        }, status=status.HTTP_404_NOT_FOUND)

    try:
        serializer = ServiceProviderPatchSerializer(
            service_provider,
            data=request.data,
            partial=True,
            context={'request': request}
        )

        if not serializer.is_valid():
            return Response({
                "success": False,
                "message": "Please fix the errors below.",
                "errors": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer.save()

        sp_profile = service_provider.sp_profile
        sp_profile.is_profile_completed = "in-address"
        sp_profile.save(update_fields=["is_profile_completed"])

        return Response({
            "success": True,
            "message": "Profile updated successfully.",
            "data": {
                **serializer.data,
                "profile_status": sp_profile.is_profile_completed,
            }
        }, status=status.HTTP_200_OK)

    except Exception:
        logger.exception(
            "Failed to update service provider profile. User ID: %s",
            request.user.id
        )

        return Response({
            "success": False,
            "message": "A server error occurred. Please try again later."
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



@api_view(["GET"])
@authentication_classes([SPJWTAuthentication])
@throttle_classes([HeavyReadThrottle])
@permission_classes([IsAuthenticated])
def approved_services_list(request):
    """
    Return only APPROVED services.
    """
    try:
        services = Service.objects.filter(
            review_status="APPROVED"
        ).select_related("service_group")

        serializer = ServiceReadSerializer(services, many=True)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )

    except DatabaseError as e:
        logger.error(f"DB error fetching approved services: {str(e)}")

        return Response(
            {
                "success": False,
                "message": "Unable to fetch services at the moment."
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )

    except Exception as e:
        logger.error(f"Unexpected error in approved_services_list: {str(e)}")

        return Response(
            {
                "success": False,
                "message": "Something went wrong while processing your request."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )



@api_view(['POST'])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def submit_service(request, provider_id):

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

                    provider.sp_profile.is_profile_completed = "in-cost"
                    provider.sp_profile.save(update_fields=["is_profile_completed"])

                    return Response(
                        {
                            "status": "reactivated",
                            "id": existing_provider_service.id,
                            "is_primary": existing_provider_service.is_primary,
                            "service": ServiceReadSerializer(service).data,
                            "profile_status": provider.sp_profile.is_profile_completed,
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

                provider.sp_profile.is_profile_completed = "in-cost"
                provider.sp_profile.save(update_fields=["is_profile_completed"])

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

            provider.sp_profile.is_profile_completed = "in-cost"
            provider.sp_profile.save(update_fields=["is_profile_completed"])

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

    except ValidationError:
        # No message_dict exposure
        return Response(
            {"error": "Invalid data provided."},
            status=status.HTTP_400_BAD_REQUEST
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


@api_view(['POST'])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def submit_service(request, provider_id):

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

                    provider.sp_profile.is_profile_completed = "in-cost"
                    provider.sp_profile.save(update_fields=["is_profile_completed"])

                    return Response(
                        {
                            "status": "reactivated",
                            "id": existing_provider_service.id,
                            "is_primary": existing_provider_service.is_primary,
                            "service": ServiceReadSerializer(service).data,
                            "profile_status": provider.sp_profile.is_profile_completed,
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

                provider.sp_profile.is_profile_completed = "in-cost"
                provider.sp_profile.save(update_fields=["is_profile_completed"])

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

            provider.sp_profile.is_profile_completed = "in-cost"
            provider.sp_profile.save(update_fields=["is_profile_completed"])

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

                    provider.sp_profile.is_profile_completed = "in-cost"
                    provider.sp_profile.save(update_fields=["is_profile_completed"])

                    return Response(
                        {
                            "status": "reactivated",
                            "id": existing_provider_service.id,
                            "is_primary": existing_provider_service.is_primary,
                            "service": ServiceReadSerializer(service).data,
                            "profile_status": provider.sp_profile.is_profile_completed,
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
            print(f"Removing {existing_affidavits.count()} existing affidavit(s).")
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
        print("Serializer errors:", serializer.errors)
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


@api_view(['PATCH'])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def update_cost_of_service(request, service_id):

    try:
        provider = ServiceProvider.objects.select_related(
            'sp_profile'
        ).get(sp_profile=request.user)

    except ServiceProvider.DoesNotExist:
        return Response(
            {"error": "Provider not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    try:
        service = Service.objects.get(service_id=service_id)

    except Service.DoesNotExist:
        return Response(
            {"error": "Service not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    provider_service, _ = ProviderService.objects.get_or_create(
        provider=provider,
        service=service
    )

    data = request.data
    base_price = data.get("base_price")
    negotiable = data.get("negotiable", True)
    notes = data.get("notes", "")

    try:
        with transaction.atomic():

            if provider_service.cost_of_service is None:
                cost = CostOfService.objects.create(
                    base_price=base_price,
                    negotiable=negotiable,
                    notes=notes
                )
                provider_service.cost_of_service = cost
                provider_service.save()
            else:
                cost = provider_service.cost_of_service
                cost.base_price = base_price
                cost.negotiable = negotiable
                cost.notes = notes
                cost.save()

            provider.sp_profile.is_profile_completed = "completed"
            provider.sp_profile.save(update_fields=["is_profile_completed"])

        return Response({
            "success": True,
            "cost_of_service": {
                "id": cost.id,
                "base_price": str(cost.base_price) if cost.base_price else None,
                "negotiable": cost.negotiable,
                "notes": cost.notes,
            },
            "profile_status": provider.sp_profile.is_profile_completed
        }, status=status.HTTP_200_OK)

    except DatabaseError:
        logger.error("Database error in update_cost_of_service", exc_info=True)
        return Response(
            {"error": "Service temporarily unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )

    except Exception:
        logger.error("Unexpected error in update_cost_of_service", exc_info=True)
        return Response(
            {"error": "Unexpected server error"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

@api_view(['PATCH'])
@throttle_classes([ProfileWriteThrottle])
@authentication_classes([SPJWTAuthentication])
@permission_classes([IsAuthenticated])
def a_update_cost_of_service(request, service_id):

    try:
        provider = ServiceProvider.objects.select_related(
            'sp_profile'
        ).get(sp_profile=request.user)

    except ServiceProvider.DoesNotExist:
        return Response(
            {"error": "Provider not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    try:
        service = Service.objects.get(service_id=service_id)

    except Service.DoesNotExist:
        return Response(
            {"error": "Service not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    provider_service, _ = ProviderService.objects.get_or_create(
        provider=provider,
        service=service
    )

    data = request.data
    base_price = data.get("base_price")
    negotiable = data.get("negotiable", True)
    notes = data.get("notes", "")

    try:
        with transaction.atomic():

            if provider_service.cost_of_service is None:
                cost = CostOfService.objects.create(
                    base_price=base_price,
                    negotiable=negotiable,
                    notes=notes
                )
                provider_service.cost_of_service = cost
                provider_service.save()
            else:
                cost = provider_service.cost_of_service
                cost.base_price = base_price
                cost.negotiable = negotiable
                cost.notes = notes
                cost.save()


        return Response({
            "success": True,
            "cost_of_service": {
                "id": cost.id,
                "base_price": str(cost.base_price) if cost.base_price else None,
                "negotiable": cost.negotiable,
                "notes": cost.notes,
            },
            "profile_status": provider.sp_profile.is_profile_completed
        }, status=status.HTTP_200_OK)

    except DatabaseError:
        logger.error("Database error in update_cost_of_service", exc_info=True)
        return Response(
            {"error": "Service temporarily unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE
        )

    except Exception:
        logger.error("Unexpected error in update_cost_of_service", exc_info=True)
        return Response(
            {"error": "Unexpected server error"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )



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
        token.blacklist()

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

@api_view(['GET'])
@throttle_classes([UserReadThrottle])
@authentication_classes([ClientJWTAuthentication])
@permission_classes([IsAuthenticated])
def service_list(request):

    try:
        services = (
            Service.objects.filter(
                review_status="APPROVED"
            )
            .select_related("service_group")
            .annotate(
                active_provider_count=Count(
                    "service_providers__provider",
                    filter=Q(service_providers__provider__is_active=True),
                    distinct=True
                )
            )
            .order_by("service_name")  # 🔥 deterministic ordering
        )

        serializer = ServiceSerializer(services, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    except Exception:
        logger.exception("Unexpected error in service_list")

        return Response(
            {
                "success": False,
                "message": "Unexpected server error."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
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

            print("[CLIENT LOCATION] No default address found")

            return Response(
                [],
                status=status.HTTP_200_OK
            )

        # --------------------------------------------------
        # DISTANCE CALCULATION
        # --------------------------------------------------

        INITIAL_RADIUS_KM = 50.0
        MAX_RADIUS_KM = 200.0
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

        print(
            f"[PRE FILTER COUNT] "
            f"{live_locations.count()}"
        )

        providers = list(
            live_locations
            .filter(distance_km__lte=INITIAL_RADIUS_KM)
            .order_by('distance_km')[:limit]
        )

        print(
            f"[50KM RESULTS] {len(providers)}"
        )

        if not providers:

            providers = list(
                live_locations
                .filter(distance_km__lte=MAX_RADIUS_KM)
                .order_by('distance_km')[:limit]
            )

            print(
                f"[200KM RESULTS] {len(providers)}"
            )

        if not providers:

            print("[RESULT] No providers found")

            return Response(
                [],
                status=status.HTTP_200_OK
            )

        provider_ids = [
            item.provider_id
            for item in providers
        ]

        print(
            f"[PROVIDER IDS] {provider_ids}"
        )

        ordered_providers = [
            item.provider
            for item in providers
        ]

        serializer = ClientServiceProviderReadSerializer(
            ordered_providers,
            many=True
        )

        print(
            f"[SUCCESS] Returning "
            f"{len(ordered_providers)} providers"
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
            print(serializer.errors)
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
        ).get(
            sp_profile__id=provider_id,
        )

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
    print(f"\n=== [DEBUG START] Fetching locations for Service ID: {service_id} ===")
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

        INITIAL_RADIUS_KM = 50.0
        MAX_RADIUS_KM = 200.0
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