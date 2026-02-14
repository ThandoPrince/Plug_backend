from rest_framework import serializers
from django.utils import timezone
from .models import Negotiation, NegotiationRound, OrderService, BookingItem, Rating, ServicePicture, Session, SessionLocationPing, SessionToken, Shipment, ShipmentRoute
from api.serviceProvidersDB.serializers import ProviderSeviceSerializer, ServiceSerializer
from api.clientsDB.serializers import AddressOnlySerializer, ClientSerializer
from api.clientsDB.models.models import ClientDetails, ClientAuth, Address
from django.contrib.auth.hashers import make_password



class NegotiationRoundWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = NegotiationRound
        fields = ['negotiation', 'sender_type', 'offered_price', 'message']
        read_only_fields = ['negotiation', 'sender_type']

    def validate(self, data):
        offered_price = data.get('offered_price')
        if offered_price is None:
            raise serializers.ValidationError("Offered price is required.")
        return data


class NegotiationRoundReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = NegotiationRound
        fields = ["id", "negotiation", "sender_type", "offered_price", "message", "created_at"]
        read_only_fields = ["id", "created_at"]


class NegotiationReadSerializer(serializers.ModelSerializer):
    rounds = NegotiationRoundReadSerializer(many=True, read_only=True)
    provider_for_negotiation = ProviderSeviceSerializer(read_only=True)

    class Meta:
        model = Negotiation
        fields = '__all__'
        read_only_fields = ['negotiation_id', 'created_at']



class NegotiationWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Negotiation
        fields = '__all__'

    def validate(self, data):
        # Only provider can accept
        status = data.get('status')
        if status == 'accepted':
            request = self.context.get('request')
            user = getattr(request, 'user', None)
            provider = getattr(self.instance, 'provider_for_negotiation', None)
            if provider is None or (user and provider.provider.user != user):
                raise serializers.ValidationError("Only the provider can accept this negotiation.")
        return data

    def update(self, instance, validated_data):
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Automatically create negotiation round
        NegotiationRound.objects.create(
            negotiation=instance,
            sender_type="provider",
            offered_price=instance.provider_response_price or instance.proposed_price,
            message="Provider responded"
        )

        # Update final_price if accepted
        if instance.status == 'accepted':
            order = instance.service_order
            order.final_price = instance.provider_response_price or instance.proposed_price
            order.save(update_fields=['final_price'])

        return instance


# --- Client counter-offer ---
class NegotiationClientCounterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Negotiation
        fields = ['proposed_price', 'message']

    def update(self, instance, validated_data):
        instance.proposed_price = validated_data.get('proposed_price', instance.proposed_price)
        instance.message = validated_data.get('message', instance.message)
        instance.status = 'pending'
        instance.save()

        NegotiationRound.objects.create(
            negotiation=instance,
            sender_type="client",
            offered_price=instance.proposed_price,
            message=instance.message or "Client counter-offer"
        )

        return instance





# ------------------- ServicePicture -------------------

class ServicePictureReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServicePicture
        fields = ['id', 'image', 'uploaded_at']
        read_only_fields = ['id', 'uploaded_at']


# ------------------- OrderService -------------------


class OrderServiceReadSerializer(serializers.ModelSerializer):

    service_pictures = ServicePictureReadSerializer(many=True, read_only=True)
    total_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    final_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    delivery_address = AddressOnlySerializer(read_only=True)
    provider_for_service = ProviderSeviceSerializer(read_only=True)
    invited_providers = ProviderSeviceSerializer(many=True, read_only=True)
    client = ClientSerializer(read_only=True)
    service_required = ServiceSerializer(read_only=True)

    class Meta:
        model = OrderService
        fields = '__all__'
        read_only_fields = ['order_id', 'date_and_time_created', 'total_price', 'final_price']

# ------------------- BookingItem -------------------

class BookingItemReadSerializer(serializers.ModelSerializer):
    negotiation = NegotiationReadSerializer(required=False, allow_null=True)
    order = OrderServiceReadSerializer(read_only=True)

    class Meta:
        model = BookingItem
        fields = '__all__'
        read_only_fields = ['item_id', 'checkin_token', 'token_expiry']



class ClientEmailField(serializers.SlugRelatedField):
    """
    Custom field to map client email to ClientDetails instance.
    """
    def to_internal_value(self, data):
        try:
            client_auth = ClientAuth.objects.get(email_address=data)
            return ClientDetails.objects.get(client_profile=client_auth)
        except ClientAuth.DoesNotExist:
            raise serializers.ValidationError(f"No client found with email '{data}'.")
        except ClientDetails.DoesNotExist:
            raise serializers.ValidationError(f"No client details linked to '{data}' found.")


from rest_framework import serializers
from decimal import Decimal, InvalidOperation

class OrderServiceWriteSerializer(serializers.ModelSerializer):
    client = ClientEmailField(
        queryset=ClientDetails.objects.all(),
        slug_field='client_profile.email_address'
    )
    delivery_address = serializers.PrimaryKeyRelatedField(queryset=Address.objects.all())
    provider_for_service = serializers.PrimaryKeyRelatedField(
        queryset=ProviderSeviceSerializer.Meta.model.objects.all(),
        required=False,
        allow_null=True
    )
    service_pictures = ServicePictureReadSerializer(many=True, read_only=True)
    invited_providers = serializers.SlugRelatedField(
        queryset=ProviderSeviceSerializer.Meta.model.objects.all(),
        many=True,
        slug_field='provider__sp_profile__email_address'
    )

    # Explicitly define fields you want to validate
    title = serializers.CharField(required=True, allow_blank=False)
    notes = serializers.CharField(required=True, allow_blank=False)


    proposal_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=True
    )

    class Meta:
        model = OrderService
        fields = '__all__'

    def validate_proposal_price(self, value):
        # Ensure proposal_price is numeric and positive
        if value <= 0:
            raise serializers.ValidationError("Proposal price must be greater than 0.")
        return value

    def create(self, validated_data):
        invited_providers = validated_data.pop("invited_providers", [])
        request = self.context.get("request")

        order = OrderService.objects.create(**validated_data)

        # Create initial negotiations if proposal_price exists
        if order.proposal_price:
            for provider in invited_providers:
                negotiation = Negotiation.objects.create(
                    service_order=order,
                    provider_for_negotiation=provider,
                    proposed_price=order.proposal_price
                )
                NegotiationRound.objects.create(
                    negotiation=negotiation,
                    sender_type="client",
                    offered_price=order.proposal_price,
                    message="Initial proposal"
                )

        order.invited_providers.set(invited_providers)

        # Handle uploaded service pictures
        if request and hasattr(request, "FILES"):
            for file in request.FILES.getlist("service_pictures"):
                ServicePicture.objects.create(order=order, image=file)

        return order

    
    
class ShipmentReadSerializer(serializers.ModelSerializer):
    service_ordered = BookingItemReadSerializer(read_only=True)


    class Meta:
        model = Shipment
        fields = '__all__'
        read_only_fields = ['shipment_id', 'created_at']

class ShipmentWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shipment
        fields = [
            "shipment_schedule_date",
            "shipment_schedule_time",
            "shipment_status",
            "shipment_confirmation",
            "service_ordered",
        ]

    def validate(self, data):
        date = data.get("shipment_schedule_date")
        time = data.get("shipment_schedule_time")

        if date and time:
            # Prevent scheduling older dates
            from datetime import datetime
            dt = datetime.combine(date, time)
            if dt < timezone.now():
                raise serializers.ValidationError("Shipment schedule cannot be in the past.")

        return data
    
class ShipmentRouteWriteSerializer(serializers.ModelSerializer):
    shipment_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = ShipmentRoute
        fields = [
            "shipment_id",
            "origin_lat",
            "origin_lng",
            "destination_lat",
            "destination_lng",
            "distance_meters",
            "duration_seconds",
            "geometry",
            "recalculated",
        ]

    # --------------------
    # Validation
    # --------------------

    def validate_origin_lat(self, value):
        if not -90 <= value <= 90:
            raise serializers.ValidationError("Invalid origin latitude")
        return value

    def validate_origin_lng(self, value):
        if not -180 <= value <= 180:
            raise serializers.ValidationError("Invalid origin longitude")
        return value

    def validate_destination_lat(self, value):
        if not -90 <= value <= 90:
            raise serializers.ValidationError("Invalid destination latitude")
        return value

    def validate_destination_lng(self, value):
        if not -180 <= value <= 180:
            raise serializers.ValidationError("Invalid destination longitude")
        return value

    def validate_distance_meters(self, value):
        if value <= 0:
            raise serializers.ValidationError("Distance must be greater than zero")
        return value

    def validate_duration_seconds(self, value):
        if value <= 0:
            raise serializers.ValidationError("Duration must be greater than zero")
        return value

    # --------------------
    # Creation logic
    # --------------------

    def create(self, validated_data):
        shipment_id = validated_data.pop("shipment_id")
        shipment = Shipment.objects.get(pk=shipment_id)

    # Check if a route already exists for this shipment
        try:
         route = shipment.route  # OneToOneField gives reverse relation
        # Update existing route
         for attr, value in validated_data.items():
            setattr(route, attr, value)
         route.is_active = True
         route.recalculated = True  # mark as recalculated since it's an update
         route.save()  # ShipmentRoute.save() will create a ShipmentRouteHistory automatically
         return route
        except ShipmentRoute.DoesNotExist:
        # No route exists, create a new one
         return ShipmentRoute.objects.create(
            shipment=shipment,
            is_active=True,
            **validated_data
        )

    
class ShipmentRouteReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShipmentRoute
        fields = '__all__'

        

class SessionTokenReadSerializer(serializers.ModelSerializer):
    """
    Send token info to the client for QR display
    """
    shipment = ShipmentReadSerializer(read_only=True)

    class Meta:
        model = SessionToken
        fields = [
            "token_id",
            "checkin_token",
            "token_expiry",
            "shipment",
            "created_at",
        ]
        read_only_fields = fields



# -------------------------------
# Session Serializer
# -------------------------------
class SessionReadSerializer(serializers.ModelSerializer):
    shipment = ShipmentReadSerializer(read_only=True)
    duration_seconds = serializers.SerializerMethodField()

    class Meta:
        model = Session
        fields = '__all__'

    def get_duration_seconds(self, obj):
        return int(obj.duration().total_seconds())

    


# Optional: SessionWriteSerializer (for checkout maybe)
class SessionWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Session
        fields = [
            "shipment",
            "checkin_time",
            "checkin_location",
            "checkout_time",
            "checkout_location",
        ]
        read_only_fields = ["checkin_time"]




class ConfirmCheckinSerializer(serializers.Serializer):
    checkin_token = serializers.UUIDField()
    checkin_location = serializers.JSONField()

    def validate(self, data):
        try:
            token = SessionToken.objects.select_related(
                "shipment", "session"
            ).get(checkin_token=data["checkin_token"])
        except SessionToken.DoesNotExist:
            raise serializers.ValidationError({
                "detail": "Invalid token."
            })

        # 🔒 Already used
        if token.session:
            raise serializers.ValidationError({
                "detail": "This token has already been used."
            })

        # ⏱ Expired → mark for refresh
        if not token.is_valid():
            data["expired_token"] = token
            return data

        # ✅ Valid token
        data["token_instance"] = token
        return data


class ConfirmCheckinResponseSerializer(serializers.ModelSerializer):
    shipment = ShipmentReadSerializer(read_only=True)
    duration = serializers.SerializerMethodField()

    class Meta:
        model = Session
        fields = [
            "session_id",
            "shipment",            # ✅ FIXED (lowercase, matches declared field)
            "checkin_time",
            "checkin_location",
            "checkout_time",
            "checkout_location",
            "duration",
        ]

    def get_duration(self, obj):
        duration = obj.duration()
        return duration.total_seconds() if duration else None
    
class SessionLocationPingReadSerializer(serializers.ModelSerializer):
    session = SessionReadSerializer(read_only=True)
    class Meta:
        model = SessionLocationPing
        fields = '__all__'
        

class SessionLocationPingWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionLocationPing
        # Only allow input of latitude, longitude, and accuracy
        fields = ['latitude', 'longitude', 'accuracy']

class SessionStatusUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Session
        fields = (
            "session_status",
            "checkout_location",
        )

class RatingWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rating
        fields = ["session", "score", "review"]

    def validate(self, data):
        session = data["session"]
        user = self.context["request"].user
        order = session.shipment.service_ordered.order

        if session.session_status != "completed":
            raise serializers.ValidationError(
                "Session must be completed before rating."
            )

        # Client rating provider
        if hasattr(user, "clientdetails"):
            if Rating.objects.filter(session=session, rater_client=user.clientdetails).exists():
                raise serializers.ValidationError("You already rated this session.")

        # Provider rating client
        elif hasattr(user, "providerservice"):
            if Rating.objects.filter(session=session, rater_provider=user.providerservice).exists():
                raise serializers.ValidationError("You already rated this session.")
        else:
            raise serializers.ValidationError("Invalid user.")

        return data

    def create(self, validated_data):
        user = self.context["request"].user
        session = validated_data["session"]
        order = session.shipment.service_ordered.order

        if hasattr(user, "clientdetails"):
            validated_data["rater_client"] = user.clientdetails
            validated_data["rater_provider"] = order.provider_for_service

        elif hasattr(user, "providerservice"):
            validated_data["rater_provider"] = user.providerservice
            validated_data["rater_client"] = order.client

        return super().create(validated_data)
    
class RatingReadSerializer(serializers.ModelSerializer):
    author_type = serializers.SerializerMethodField()
    session = SessionReadSerializer(read_only=True)
    class Meta:
        model = Rating
        fields = '__all__'

    def get_author_type(self, obj):
        if obj.rater_client:
            return "client"
        if obj.rater_provider:
            return "provider"
        return "unknown"

class SubmitRatingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rating
        fields = ["score", "review"]

    def validate_score(self, value):
        if value < 1 or value > 5:
            raise serializers.ValidationError(
                "Score must be between 1 and 5."
            )
        return value

    def validate(self, data):
        rating = self.instance

        # Safety check
        if not rating:
            raise serializers.ValidationError(
                "Rating instance is required."
            )

        # ✅ Prevent rating before session completion
        if rating.session.session_status != "completed":
            raise serializers.ValidationError(
                "You can only submit a rating after the session is completed."
            )

        # ✅ Prevent double submission
        if rating.score > 0:
            raise serializers.ValidationError(
                "Rating already submitted."
            )

        return data
