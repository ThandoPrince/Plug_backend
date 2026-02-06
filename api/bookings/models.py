from datetime import timedelta
from django.forms import ValidationError
from django.utils import timezone
import uuid
from django.conf import settings
from django.db import models
from .utils.choices import ORDER_STATUS, SESSION_STATUS, SHIPMENT_STATUS, PAYMENT_STATUS
from django.db.models import Avg


class OrderService(models.Model):
    title = models.CharField(max_length=255, null=True, blank=True, help_text="Example, I want my nails done.")
    order_id = models.AutoField(primary_key=True)
    proposal_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    base_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    final_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.TextField(null=True, blank=True, help_text="Brief description of the service you require.")
    is_negotiated = models.BooleanField(default=False, null=True, blank=True)
    client = models.ForeignKey('clientsDB.ClientDetails', on_delete=models.CASCADE, null=True, blank=True)
    requested_date = models.DateField(null=True, blank=True)
    provider_for_service = models.ForeignKey('serviceProvidersDB.ProviderService', on_delete=models.SET_NULL, null=True, blank=True)
    requested_date_time = models.TimeField(null=True, blank=True)
    service_required = models.ForeignKey('serviceProvidersDB.Service', on_delete=models.SET_NULL, null=True, blank=True)
    
    delivery_address = models.ForeignKey(
        'clientsDB.Address',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    date_and_time_created = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=100, choices=ORDER_STATUS, default='pending')
    is_broadcasted = models.BooleanField(default=False)

    invited_providers = models.ManyToManyField(
        'serviceProvidersDB.ProviderService',
        related_name='invited_orders',
        blank=True
    )

    def save(self, *args, **kwargs):
        if self.pk:
            old = OrderService.objects.get(pk=self.pk)
            if old.status != self.status:
                OrderHistory.objects.create(
                    order=self,
                    previous_status=old.status,
                    new_status=self.status
                )
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"Order {self.order_id} | Client: {self.client.first_name} {self.client.last_name} "
            f"| Status: {self.status}"
        )

    @property
    def total_price(self):
        return sum(item.final_price for item in self.booking_items.all())


class ServicePicture(models.Model):
    order = models.ForeignKey(
        OrderService,
        on_delete=models.CASCADE,
        related_name="service_pictures"  # order.service_pictures.all()
    )
  
    uploaded_at = models.DateTimeField(auto_now_add=True)


    def order_pictures_upload_path(instance, filename):
        
        safe_order = instance.order.order_id
        return f"order_images/{safe_order}/{filename}"

    
    image = models.ImageField(upload_to=order_pictures_upload_path, null=True, blank=True)

    def __str__(self):
        return f"Picture {self.id} for Order {self.order.order_id} uploaded at {self.uploaded_at}"


class Negotiation(models.Model):
    negotiation_id = models.AutoField(primary_key=True)
    service_order = models.ForeignKey(
        OrderService, on_delete=models.CASCADE, related_name='negotiation', null=True, blank=True
    )
    provider_for_negotiation = models.ForeignKey(
        'serviceProvidersDB.ProviderService', on_delete=models.CASCADE, null=True, blank=True)
    
    base_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    proposed_price = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    provider_response_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in-negotiation', 'In-Negotiation'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('expired', 'Expired'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    updated_at = models.DateTimeField(auto_now=True)

    
    last_responder = models.CharField(
        max_length=10,
        choices=[('client', 'Client'), ('provider', 'Provider')],
        null=True,
        blank=True
    )

    
    round_count = models.PositiveSmallIntegerField(default=0)
    max_rounds = 1000

    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
       
        if self.pk:
            old = Negotiation.objects.get(pk=self.pk)
            if old.status != self.status:
                if self.status == 'accepted' and self.last_responder == 'provider':
               
                    self.service_order.final_price = self.provider_response_price or self.proposed_price
                    # self.service_order.is_negotiated = True
                    self.service_order.status = 'accepted'
                    self.service_order.save()
                elif self.status == 'rejected':
                    
                    self.round_count += 1
                    if self.round_count >= self.max_rounds:
                        
                        self.service_order.status = 'pending'
                        self.service_order.is_broadcasted = False  
                        self.service_order.service_provider = None
                        self.service_order.save()
                        if self.service_order.invited_providers.count() == 1:
                            self.service_order.broadcast_to_new_providers()
                        
        super().save(*args, **kwargs)

    @classmethod
    def provider_respond(cls, order_id, provider, response_price, accept=True):
        """
        Provider responds to negotiation.
        If accepted, updates provider_response_price and status to accepted.
        """
        from django.db import transaction
        with transaction.atomic():
            order = OrderService.objects.select_for_update().get(pk=order_id)

            
            if provider not in order.invited_providers.all():
                raise Exception("Provider not invited")

            negotiation = getattr(order, 'negotiation', None)
            if not negotiation:
                raise Exception("Negotiation not initiated")

           
            if negotiation.round_count >= negotiation.max_rounds:
                raise Exception("Maximum negotiation rounds reached")

            negotiation.provider_response_price = response_price
            negotiation.status = 'accepted' if accept else 'rejected'
            negotiation.last_responder = 'provider'
            negotiation.save()

    @classmethod
    def client_counter_offer(cls, order_id, counter_price):
     
        from django.db import transaction
        with transaction.atomic():
            order = OrderService.objects.select_for_update().get(pk=order_id)
            negotiation = getattr(order, 'negotiation', None)
            if not negotiation:
                raise Exception("Negotiation not initiated")

            
            negotiation.round_count += 1
            if negotiation.round_count > negotiation.max_rounds:
                
                order.status = 'pending'
                order.is_broadcasted = False
                order.service_provider = None
                order.save()
                return

            
            negotiation.proposed_price = counter_price
            negotiation.status = 'pending'
            negotiation.last_responder = 'client'
            negotiation.save()

    def __str__(self):
        return (
            f"Negotiation {self.negotiation_id} | Status: {self.status} "
            f"| Round: {self.round_count}/{self.max_rounds} "
            f"| Proposed: R{self.proposed_price} | Response: R{self.provider_response_price or 'N/A'}"
        )
    
class NegotiationRound(models.Model):
    negotiation = models.ForeignKey(Negotiation, on_delete=models.CASCADE, related_name="rounds")
    sender_type = models.CharField(
        max_length=20,
        choices=[("client", "Client"), ("provider", "Provider")]
    )
    offered_price = models.DecimalField(max_digits=10, decimal_places=2)
    message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class BookingItem(models.Model):
    item_id = models.AutoField(primary_key=True)
    order = models.ForeignKey(OrderService, on_delete=models.CASCADE, related_name='booking_items',)
    def __str__(self):
        service_name = self.order.service_required.service_name if self.order.service_required else 'N/A'
        provider_name = str(self.order.provider_for_service) if self.order.provider_for_service else 'N/A'
        return f"Item {self.item_id} | {service_name} | Provider: {provider_name}"




class Shipment(models.Model):
    shipment_id = models.AutoField(primary_key=True)
    shipment_schedule_date = models.DateField()
    shipment_schedule_time = models.TimeField()
    shipment_status = models.CharField(max_length=50, choices=SHIPMENT_STATUS, default='Pending')
    shipment_confirmation = models.BooleanField(default=False)
    service_ordered = models.ForeignKey(BookingItem, on_delete=models.CASCADE, related_name="shipments")
    created_at = models.DateTimeField(auto_now_add=True)




    def save(self, *args, **kwargs):
        is_new = self.pk is None
        old_status = None
        if not is_new:
            old_status = Shipment.objects.get(pk=self.pk).shipment_status

        super().save(*args, **kwargs)

        
     
    


    def __str__(self):
    
        return f"Shipment {self.shipment_id} | Status: {self.shipment_status} | Date: {self.shipment_schedule_date} | Time: {self.shipment_schedule_time}"
    
class ShipmentRouteHistory(models.Model):
    history_id = models.AutoField(primary_key=True)

    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name="route_history"
    )

    route = models.ForeignKey(
        'ShipmentRoute',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="history_entries"
    )

    # Snapshot of route data
    origin_lat = models.FloatField()
    origin_lng = models.FloatField()

    destination_lat = models.FloatField()
    destination_lng = models.FloatField()

    distance_meters = models.PositiveIntegerField()
    duration_seconds = models.PositiveIntegerField()

    geometry = models.JSONField()

    reason = models.CharField(
        max_length=50,
        choices=[
            ("initial", "Initial Route"),
            ("recalculated", "Recalculated"),
            ("off_route", "Off Route"),
            ("manual", "Manual Update"),
        ],
        default="initial"
    )

    created_at = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        
        ordering = ["created_at"]

    def __str__(self):
        return (
            f"RouteHistory {self.history_id} | "
            f"Shipment {self.shipment.shipment_id} | "
            f"{self.reason}"
        )
    
class ShipmentRoute(models.Model):
    class TravelMode(models.TextChoices):
        CAR = "car", "Car"
        PEDESTRIAN = "pedestrian", "Pedestrian"
        BICYCLE = "bicycle", "Bicycle"
        SCOOTER = "scooter", "Scooter"

    route_id = models.AutoField(primary_key=True)

    shipment = models.OneToOneField(
        Shipment,
        on_delete=models.CASCADE,
        related_name="route"
    )

    origin_lat = models.FloatField()
    origin_lng = models.FloatField()
    destination_lat = models.FloatField()
    destination_lng = models.FloatField()

    distance_meters = models.PositiveIntegerField()
    duration_seconds = models.PositiveIntegerField()

    geometry = models.JSONField()

    travel_mode = models.CharField(
        max_length=20,
        choices=TravelMode.choices,
        default=TravelMode.CAR,
        help_text="Mode of travel for this route",
        null=True,
        blank=True
    )

    is_active = models.BooleanField(default=True)
    recalculated = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)


        ShipmentRouteHistory.objects.create(
            shipment=self.shipment,
            route=self,
            origin_lat=self.origin_lat,
            origin_lng=self.origin_lng,
            destination_lat=self.destination_lat,
            destination_lng=self.destination_lng,
            distance_meters=self.distance_meters,
            duration_seconds=self.duration_seconds,
            geometry=self.geometry,
            reason="initial" if is_new else "recalculated",
        )

    def __str__(self):
        return f"Route {self.route_id} | Shipment {self.shipment.shipment_id}"
class Session(models.Model):
    session_id = models.AutoField(primary_key=True)

    shipment = models.OneToOneField(
        Shipment,
        on_delete=models.CASCADE,
        related_name="session"  # IMPORTANT
    )

    checkin_time = models.DateTimeField(auto_now_add=True)
    checkin_location = models.JSONField()

    checkout_time = models.DateTimeField(null=True, blank=True)
    checkout_location = models.JSONField(null=True, blank=True)

    session_status = models.CharField(
        max_length=50,
        choices=SESSION_STATUS,
        default="in_progress"
    )

    date_created = models.DateTimeField(auto_now_add=True)

    def duration(self):
        if self.checkout_time:
            return self.checkout_time - self.checkin_time
        return timezone.now() - self.checkin_time

    def __str__(self):
        return f"Session {self.session_id} | Shipment {self.shipment.shipment_id}"

    



class SessionToken(models.Model):
    checkin_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False
    )

    token_expiry = models.DateTimeField(null=True, blank=True)
    token_id = models.AutoField(primary_key=True)

    session = models.ForeignKey(
        'Session',
        on_delete=models.CASCADE,
        related_name='tokens',
        null=True,
        blank=True
    )

    shipment = models.ForeignKey(
        'Shipment', on_delete=models.CASCADE, related_name='tokens', null=True, blank=True
        
    )

    created_at = models.DateTimeField(auto_now_add=True, null=True)

    TOKEN_LIFETIME_MINUTES = 15  

    def is_valid(self):
        return timezone.now() < self.token_expiry

    @classmethod
    def create_new(cls, shipment, session=None):
        """Always creates a fresh token"""
        return cls.objects.create(
            shipment=shipment,
            session=session,
            token_expiry=timezone.now() + timedelta(minutes=cls.TOKEN_LIFETIME_MINUTES)
        )

    @classmethod
    def get_or_refresh_token(cls, shipment, session=None):
        """
        Returns active token.
        If expired → auto-create a new one.
        """
        token = (
            cls.objects
            .filter(shipment=shipment)
            .order_by("-created_at")
            .first()
        )

        if token and token.is_valid():
            return token

        return cls.create_new(shipment=shipment, session=session)

    def __str__(self):
        return f"SessionToken {self.token_id} | Expires at {self.token_expiry}"

class SessionLocationPing(models.Model):
    ping_id = models.AutoField(primary_key=True)

    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name="location_pings"
    )

    latitude = models.FloatField()
    longitude = models.FloatField()

    accuracy = models.FloatField(null=True, blank=True)

    inside_geofence = models.BooleanField(default=True)

    distance_from_site_meters = models.FloatField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return (
            f"Ping {self.ping_id} | "
            f"Session {self.session.session_id} | "
            f"{'Inside' if self.inside_geofence else 'Outside'}"
        )



    
class OrderHistory(models.Model):
    history_id = models.AutoField(primary_key=True)
    order = models.ForeignKey(OrderService, on_delete=models.CASCADE, related_name='history')
    status_change_date = models.DateTimeField(auto_now_add=True)
    previous_status = models.CharField(max_length=20)
    new_status = models.CharField(max_length=20)

    def __str__(self):
        return (
            f"History {self.history_id} | Order {self.order.order_id} "
            f"| Changed from {self.previous_status} to {self.new_status} on {self.status_change_date}"
        )


class Rating(models.Model):
    session = models.ForeignKey(
        'Session',
        on_delete=models.CASCADE,
        related_name="ratings"
    )

    # Who is giving the rating
    rater_client = models.ForeignKey(
        'clientsDB.ClientDetails',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="given_ratings"
    )

    rater_provider = models.ForeignKey(
        'serviceProvidersDB.ServiceProvider',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="given_ratings"
    )

    score = models.PositiveSmallIntegerField(
        choices=[(i, i) for i in range(1, 6)],
        null=True,
        blank=True
    )

    review = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # Prevent both being NULL
            models.CheckConstraint(
                check=(
                    models.Q(rater_client__isnull=False) |
                    models.Q(rater_provider__isnull=False)
                ),
                name="rating_must_have_a_rater"
            ),

            # Prevent both being filled
            models.CheckConstraint(
                check=~(
                    models.Q(rater_client__isnull=False) &
                    models.Q(rater_provider__isnull=False)
                ),
                name="rating_only_one_rater"
            ),

            models.UniqueConstraint(
                fields=["session", "rater_client"],
                name="unique_client_rating_per_session"
            ),
            models.UniqueConstraint(
                fields=["session", "rater_provider"],
                name="unique_provider_rating_per_session"
            ),
        ]

    def clean(self):
        if self.session.session_status != "completed":
            raise ValidationError("Rating is only allowed after the session is completed.")

    def __str__(self):
        rater = self.rater_client or self.rater_provider
        return f"Rating {self.score}/5 | Session {self.session.session_id} | By {rater}"
