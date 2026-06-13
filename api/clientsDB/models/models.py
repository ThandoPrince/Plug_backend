from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
import uuid
from django.utils import timezone
from datetime import timedelta

from django.db import models
from api.bookings.utils.choices import BUILDING_TYPE_CHOICES




class Address(models.Model):
    unit_number = models.CharField(max_length=20, blank=True, default="")
    access_notes = models.TextField(blank=True, null=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=7, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=7, blank=True, null=True)
    place_id = models.CharField(max_length=255, blank=True, null=True)
    street_number = models.CharField(max_length=10, blank=True, null=True)
    route = models.CharField("Street Name", max_length=255, blank=True, null=True)
    locality = models.CharField("City/Town", max_length=100)
    administrative_area_level_1 = models.CharField("Province/State", max_length=100)
    formatted_address = models.CharField("Full Address", max_length=512, blank=False, null=True,editable=False)
    country = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    is_verified = models.BooleanField(default=False)
    building_type  = models.CharField(max_length=100, choices=BUILDING_TYPE_CHOICES , default='house')

    clients = models.ManyToManyField('ClientDetails', through='ClientAddress', related_name='addresses')
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["place_id", "unit_number"],
                name="unique_household_identity"
            )
        ]

    def clean(self):

    # Apartment must have unit number
        if self.building_type == "apartment" and not self.unit_number:
            raise ValidationError("Unit number is required for apartments.")

    # House must not have unit number
        if self.building_type == "house" and self.unit_number:
            raise ValidationError("Houses cannot have a unit number.")

    # Basic structural validation
        required_fields = [
            self.street_number,
            self.route,
            self.locality,
            self.latitude,
            self.longitude
    ]

        if not all(required_fields):
            raise ValidationError("Incomplete address data.")

    def get_formatted_address(self):
        parts = [self.street_number, self.route, self.locality, self.administrative_area_level_1]
        return ", ".join(filter(None, parts))
    
    def save(self, *args, **kwargs):
        self.formatted_address = self.get_formatted_address()
        super().save(*args, **kwargs)

    def __str__(self):
     return self.formatted_address or self.get_formatted_address()
    




class ClientAuth(models.Model):
    id = models.AutoField(primary_key=True)

    email_address = models.EmailField(
        unique=True,
        max_length=100
    )

    mobile_number = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        unique=True
    )

    password = models.CharField(max_length=128)

    Profile_CHOICES = [
        ("in-details", "In-Details"),
        ("in-address", "In-Address"),
        ("completed", "Completed"),
    ]

    is_profile_completed = models.CharField(
        default="in-details",
        choices=Profile_CHOICES,
        max_length=20
    )

    @property
    def is_authenticated(self):
        return True
    @property
    def is_anonymous(self):
        return False

    def __str__(self):
        return f"{self.email_address}"

class DeviceToken(models.Model):
    DEVICE_TYPES = (
        ("android", "Android"),
        ("ios", "iOS"),
        ("web", "Web"),
        ("huawei", "Huawei"),
    )
    PROVIDER_TYPES = (
        ("firebase", "Firebase Cloud Messaging"),
        ("huawei", "Huawei Push Kit"),
    )
    provider = models.CharField(max_length=20, choices=PROVIDER_TYPES, default="firebase")

    client = models.ForeignKey(
        'ClientAuth',  # link to your auth model
        on_delete=models.CASCADE,
        related_name="device_tokens"
    )
    fcm_token = models.CharField(max_length=512)
    device_type = models.CharField(max_length=20, choices=DEVICE_TYPES)
    device_name = models.CharField(max_length=100, blank=True, null=True)
    os_version = models.CharField(max_length=50, blank=True, null=True)
    app_version = models.CharField(max_length=20, blank=True, null=True)
    last_seen = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.client.email_address} - {self.device_name or self.device_type}"


class ClientDetails(models.Model):
    first_name = models.CharField(max_length=100, null=True, blank=True)
    last_name = models.CharField(max_length=100, null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    client_profile = models.OneToOneField(ClientAuth, on_delete=models.CASCADE, primary_key=True)
    rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True, default=0.0)
    client_pp = models.ImageField(upload_to='client_profile_pics', default='default.jpg', null=True, blank=True)
    client_ID = models.CharField(max_length=20, blank=True, null=True, unique=True, auto_created=True)
    is_active = models.BooleanField(default=True)




    def __str__(self):
        return f"{self.first_name} - {self.last_name}-{self.client_profile.email_address}"
    
class ClientSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    client = models.ForeignKey(
        ClientAuth,
        on_delete=models.CASCADE,
        related_name="sessions"
    )

    token = models.CharField(max_length=255, unique=True)

    device_id = models.CharField(max_length=255, null=True, blank=True)
    device_name = models.CharField(max_length=255, null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    last_used = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)

    def is_expired(self):
        return timezone.now() >= self.expires_at

    def __str__(self):
        return f"{self.client.email_address} - {self.device_name} - Active: {self.is_active}"
    



class ClientAddress(models.Model):
    id = models.AutoField(auto_created=True, primary_key=True)
    is_active = models.BooleanField(default=True)

    RESIDENTIAL = "Residential Address"
    VACATION = "Vacation Address"

    ADDRESS_TYPE_CHOICES = [
        (RESIDENTIAL, "Residential Address"),
        (VACATION, "Vacation Address"),
    ]

    client = models.ForeignKey("ClientDetails", on_delete=models.CASCADE)
    address = models.ForeignKey("Address", on_delete=models.CASCADE)

    # User-controlled flags
    is_owner = models.BooleanField(
        "Are you the owner of the household?",
        default=False
    )

    house_administrator = models.BooleanField(
        "Are you responsible for what happens on the premises?",
        default=False
    )

    # 🔒 Only granted after document approval
    is_super_user = models.BooleanField(
        default=False,
        editable=False
    )

    address_type = models.CharField(
        max_length=100,
        choices=ADDRESS_TYPE_CHOICES,
        default=RESIDENTIAL
    )

    is_default = models.BooleanField(default=False)

    class Meta:
        unique_together = ('client', 'address')

    # --------------------------------------------------
    # VALIDATION
    # --------------------------------------------------
    def clean(self):
        """
        Business validation only.
        Do NOT validate default uniqueness here.
        """

        # Maximum 2 owners per address
        if self.is_owner:
            owner_count = ClientAddress.objects.filter(
                address=self.address,
                is_owner=True
            ).exclude(pk=self.pk).count()

            if owner_count >= 2:
                raise ValidationError(
                    "Only two clients can be marked as owners of this address."
                )


    def save(self, *args, **kwargs):
        """
        Automatically ensure only one default per client.
        """


        if self.is_default:
            ClientAddress.objects.filter(
                client=self.client,
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)

        # Now run validation AFTER fixing defaults
        self.full_clean()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.client.first_name} - {self.address}"
    
class AddressSuperUserVerification(models.Model):

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    client_address = models.OneToOneField(
        ClientAddress,
        on_delete=models.CASCADE,
        related_name="verification_request"
    )

    proof_of_residence = models.FileField(
        upload_to="media/address_verifications/proof_of_residence/"
    )

    id_document = models.ImageField(
        upload_to="media/address_verifications/id_documents"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending"
    )

    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    admin_notes = models.TextField(blank=True, null=True)

    def approve(self):
        self.status = "approved"
        self.reviewed_at = timezone.now()
        self.save()

        # 🔥 Promote user to super user
        self.client_address.is_super_user = True
        self.client_address.save(update_fields=["is_super_user"])

    def reject(self, note=None):
        self.status = "rejected"
        self.reviewed_at = timezone.now()
        if note:
            self.admin_notes = note
        self.save()

    def __str__(self):
        return f"Verification for {self.client_address}"


    
class PendingAddressApproval(models.Model):
    address = models.ForeignKey(Address, on_delete=models.CASCADE)
    requested_by = models.ForeignKey(ClientDetails, on_delete=models.CASCADE)
    owner = models.ForeignKey(ClientDetails, related_name='approver', on_delete=models.CASCADE)
    status = models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='pending', max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    id = models.AutoField(auto_created=True, primary_key=True)

User = get_user_model()

class ClientNotification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='client_notifications')
    title = models.CharField(max_length=255)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"To {self.recipient} - {self.title}"


