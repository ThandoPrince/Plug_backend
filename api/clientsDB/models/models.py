import os

from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
import uuid
from django.utils import timezone
from datetime import timedelta
from django.db import models, transaction
from django.db import models
from api.bookings.utils.choices import BUILDING_TYPE_CHOICES




class Address(models.Model):
    unit_number = models.CharField(max_length=20, blank=True, default="",db_index=True)
    access_notes = models.TextField(blank=True, null=True,db_index=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=7, blank=True, null=True,db_index=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=7, blank=True, null=True,db_index=True)
    place_id = models.CharField(max_length=255, blank=True, null=True,db_index=True)
    street_number = models.CharField(max_length=10, blank=True, null=True,db_index=True)
    route = models.CharField("Street Name", max_length=255, blank=True, null=True,db_index=True)
    locality = models.CharField("City/Town", max_length=100,db_index=True)
    administrative_area_level_1 = models.CharField("Province/State", max_length=100,db_index=True)
    formatted_address = models.CharField("Full Address", max_length=512, blank=False, null=True,editable=False,db_index=True)
    country = models.CharField(max_length=100,db_index=True)
    postal_code = models.CharField(max_length=20,db_index=True)
    is_verified = models.BooleanField(default=False,db_index=True)
    date_created = models.DateTimeField(auto_now=True, null=True,db_index=True)
    building_type  = models.CharField(max_length=100, choices=BUILDING_TYPE_CHOICES , default='house',db_index=True)

    clients = models.ManyToManyField('ClientDetails', through='ClientAddress', related_name='addresses',db_index=True)
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["place_id", "unit_number"],
                name="unique_household_identity"
            )
        ]
        indexes = [
            models.Index(fields=["place_id","latitude", "longitude"]),
            models.Index(fields=["place_id"]),
            models.Index(fields=["is_verified"]),
           
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
    id = models.AutoField(primary_key=True,db_index=True)

    email_address = models.EmailField(
        unique=True,
        max_length=100,db_index=True
    )
    failed_login_attempts = models.PositiveIntegerField(default=0,db_index=True)
    account_locked_until = models.DateTimeField(
        null=True,
        blank=True,db_index=True
    )

    mobile_number = models.CharField(
        max_length=60,
        blank=True,
        null=True,
        unique=True,db_index=True
    )
    date_created = models.DateTimeField (auto_now= True, null=True,db_index=True)
    last_login_ip = models.GenericIPAddressField(
        null=True,
        blank=True,db_index=True
    )
    mfa_enabled = models.BooleanField(default=False)
    mfa_secret = models.CharField(max_length=32, null=True, blank=True)
    last_login_at = models.DateTimeField(
    null=True,
    blank=True,
    db_index=True
)


    password = models.CharField(max_length=128)

    Profile_CHOICES = [
        ("in-details", "In-Details"),
        ("in-address", "In-Address"),
        ("completed", "Completed"),
        ("in-kyc", "In-KYC"),
        ("is_blocked", "Is-Blocked"),
    ]
    total_failed_login_attempts = models.PositiveIntegerField(
        default=0,db_index=True
    )

    is_profile_completed = models.CharField(
        default="in-details",
        choices=Profile_CHOICES,
        max_length=20,db_index=True
    )
    class Meta:
        indexes = [
            models.Index(fields=["id"]),
           
    ]

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

    provider = models.CharField(
        max_length=20,
        choices=PROVIDER_TYPES,
        default="firebase"
    )

    client = models.ForeignKey(
        'ClientAuth',
        on_delete=models.CASCADE,
        related_name="device_tokens"
    )

    fcm_token = models.CharField(max_length=512)

    device_type = models.CharField(
        max_length=20,
        choices=DEVICE_TYPES
    )

    device_name = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    os_version = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )

    app_version = models.CharField(
        max_length=20,
        blank=True,
        null=True
    )

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True
    )

    last_seen = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.client.email_address} - {self.device_name or self.device_type}"
    
class ClientLoginHistory(models.Model):
    client = models.ForeignKey(
        ClientAuth,
        on_delete=models.CASCADE, null=True
    )
    successful = models.BooleanField(default=False)
    identifier = models.CharField(max_length=100, null=True)
    user_agent = models.TextField(blank=True, null=True)
    ip_address = models.GenericIPAddressField()
    device_name = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class ClientRegistrationHistory(models.Model):

    email = models.CharField(max_length=255, null=True, blank=True)
    mobile_number = models.CharField(max_length=20, null=True, blank=True)

    successful = models.BooleanField(default=False)

    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True, null=True)
    device_name = models.CharField(max_length=100, blank=True, null=True)

    error_message = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "client_registration_history"

        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["mobile_number"]),
            models.Index(fields=["ip_address"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["successful"]),
        ]

        ordering = ["-created_at"]

    def __str__(self):
        status = "SUCCESS" if self.successful else "FAILED"
        return f"{status} | {self.email or self.mobile_number} | {self.ip_address}"


class ClientDetails(models.Model):
    first_name = models.CharField(max_length=100, null=True, blank=True)
    last_name = models.CharField(max_length=100, null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)

    client_profile = models.OneToOneField(
        ClientAuth,
        on_delete=models.CASCADE,
        primary_key=True,
    )

    rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        null=True,
        blank=True,
        default=0.0,
    )

    client_pp = models.ImageField(
        upload_to='client_profile_pics',
        default='default.jpg',
        null=True,
        blank=True,
    )

    client_ID = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        unique=True,
        auto_created=True,
    )

    is_active = models.BooleanField(default=True)


    last_updated = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=["client_ID","client_profile","first_name","client_pp","is_active","rating"]),

           
    ]

    def __str__(self):
        return (
            f"{self.first_name} - "
            f"{self.last_name} - "
            f"{self.client_profile.email_address}"
        )
    
class ClientSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    client = models.ForeignKey(
        ClientAuth,
        on_delete=models.CASCADE,
        related_name="sessions"
    )
    date_created = models.DateTimeField (auto_created=True, null=True)

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
    id = models.AutoField(primary_key=True ,db_index=True)
    is_active = models.BooleanField(default=True,db_index=True)
    date_created = models.DateTimeField(auto_now_add=True, null=True,db_index=True)
    in_request = models.BooleanField (default=False, null=True  )
    is_activatable = models.BooleanField(default=True,db_index=True)

    RESIDENTIAL = "Residential Address"
    VACATION = "Vacation Address"

    ADDRESS_TYPE_CHOICES = [
        (RESIDENTIAL, "Residential Address"),
        (VACATION, "Vacation Address"),
    ]

    client = models.ForeignKey("ClientDetails", on_delete=models.CASCADE,db_index=True)
    address = models.ForeignKey("Address", on_delete=models.CASCADE,db_index=True)

    is_owner = models.BooleanField(
        "Are you the owner of the household?",
        default=False,db_index=True
    )

    house_administrator = models.BooleanField(
        "Are you responsible for what happens on the premises?",
        default=False,db_index=True
    )

    is_super_user = models.BooleanField(
        default=False,
        editable=True,db_index=True
    )

    address_type = models.CharField(
        max_length=100,
        choices=ADDRESS_TYPE_CHOICES,
        default=RESIDENTIAL,db_index=True
    )

    is_default = models.BooleanField(default=False,db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['client', 'address'],
                name='unique_client_address'
            )
        ]

        indexes = [
            models.Index(fields=["id","client", "address", "is_active","is_default","is_activatable"]),
             models.Index(fields=["id","is_default"]),
             models.Index(fields=["id","is_activatable"]),
           
    ]

    # --------------------------------------------------
    # VALIDATION
    # --------------------------------------------------
    def clean(self):
        """
        Business-level validation only.
        """

        super().clean()

        # Limit owners per address
        if self.is_owner:
            owner_count = ClientAddress.objects.filter(
                address=self.address,
                is_owner=True
            ).exclude(pk=self.pk).count()

            if owner_count >= 5:
                raise ValidationError(
                    "Only five clients can be marked as owners for this address."
                )

    # --------------------------------------------------
    # SAVE LOGIC
    # --------------------------------------------------
    def save(self, *args, **kwargs):
        """
        Ensures:
        - Only one default per client
        - Validation always runs
        - Race-safe updates
        """

        self.full_clean()

        with transaction.atomic():

            if self.is_default:
                ClientAddress.objects.filter(
                    client=self.client,
                    is_default=True
                ).exclude(pk=self.pk).update(is_default=False)

            super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.client} - {self.address}"


    
def secure_verification_path(instance, filename):
    """
    Stores files under a randomized, non-guessable structure.
    """

    ext = os.path.splitext(filename)[1].lower()

    valid_extensions = ['.pdf', '.jpg', '.jpeg', '.png', '.mp4']
    if ext not in valid_extensions:
        raise ValidationError("Unsupported file format. Use PDF, JPG, PNG, or MP4.")

    random_filename = f"{uuid.uuid4()}{ext}"

    client_id = instance.client_address.client.client_ID

    return os.path.join(
        "address_verifications",
        f"client_{client_id}",
        random_filename
    )




class ClientAddressHistory(models.Model):
    ACTION_CREATED = "created"
    ACTION_ACTIVATED = "activated"
    ACTION_DEACTIVATED = "deactivated"
    ACTION_REACTIVATED = "reactivated"
    ACTION_SUPER_USER_ASSIGNED = "super_user_assigned"
    ACTION_SUPER_USER_REMOVED = "super_user_removed"
    ACTION_OWNER_ASSIGNED = "owner_assigned"
    ACTION_OWNER_REMOVED = "owner_removed"
    ACTION_ADMIN_ASSIGNED = "admin_assigned"
    ACTION_ADMIN_REMOVED = "admin_removed"

    ACTION_CHOICES = [
        (ACTION_CREATED, "Created"),
        (ACTION_ACTIVATED, "Activated"),
        (ACTION_DEACTIVATED, "Deactivated"),
        (ACTION_REACTIVATED, "Reactivated"),
        (ACTION_SUPER_USER_ASSIGNED, "Super User Assigned"),
        (ACTION_SUPER_USER_REMOVED, "Super User Removed"),
        (ACTION_OWNER_ASSIGNED, "Owner Assigned"),
        (ACTION_OWNER_REMOVED, "Owner Removed"),
        (ACTION_ADMIN_ASSIGNED, "Administrator Assigned"),
        (ACTION_ADMIN_REMOVED, "Administrator Removed"),
    ]

    client_address = models.ForeignKey(
        "ClientAddress",
        on_delete=models.CASCADE,
        related_name="history",
        db_index=True,
    )

    performed_by = models.ForeignKey(
        "ClientDetails",
        on_delete=models.PROTECT,
        related_name="client_address_actions",
        null=True,
        blank=True,
        db_index=True,
    )

    action = models.CharField(
        max_length=100,
        choices=ACTION_CHOICES,
        db_index=True,
    )

    reason = models.TextField(
        null=True,
        blank=True,
    )

    metadata = models.JSONField(
        null=True,
        blank=True,
    )

    date_created = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        ordering = ["-date_created"]

    def __str__(self):
        return (
            f"{self.client_address_id} - "
            f"{self.action} - "
            f"{self.date_created}"
        )




class AddressSuperUserVerification(models.Model):

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    client_address = models.OneToOneField(
        "ClientAddress",
        on_delete=models.CASCADE,
        related_name="verification_request"
    )

    date_created = models.DateTimeField(auto_now_add=True, null=True)

    proof_of_residence = models.FileField(
        upload_to=secure_verification_path
    )

    id_document = models.ImageField(
        upload_to=secure_verification_path
    )

    liveness_video = models.FileField(
        upload_to=secure_verification_path, null=True, blank=True
    )
    id_number = models.CharField(
        max_length=20,
        blank=False,
        null=False,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING
    )

    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    admin_notes = models.TextField(blank=True, null=True)

    # --------------------------------------------------
    # VALIDATION
    # --------------------------------------------------
    def clean(self):
        super().clean()

        # Videos are legitimately much bigger than a scanned document,
        # so this needs its own ceiling rather than sharing the 5MB
        # limit meant for images/PDFs.
        MAX_SIZES = {
            "proof_of_residence": 5 * 1024 * 1024,    # 5MB
            "id_document": 5 * 1024 * 1024,           # 5MB
            "liveness_video": 50 * 1024 * 1024,       # 50MB
        }

        for field_name, max_size in MAX_SIZES.items():
            file = getattr(self, field_name)

            if file and hasattr(file, "size") and file.size > max_size:
                raise ValidationError({
                    field_name: f"File size cannot exceed {max_size // (1024 * 1024)}MB."
                })

    # --------------------------------------------------
    # APPROVAL FLOW
    # --------------------------------------------------
    def approve(self):
        """
        Approve this verification.

        The physical address is marked verified only on the
        False -> True transition. Each approved client receives
        their own superuser status.
        """

        with transaction.atomic():

            verification = (
                AddressSuperUserVerification.objects
                .select_for_update()
                .get(pk=self.pk)
            )

            if verification.status == self.STATUS_APPROVED:
                return

            # -------------------------------------------------
            # APPROVE THIS VERIFICATION
            # -------------------------------------------------
            verification.status = self.STATUS_APPROVED
            verification.reviewed_at = timezone.now()

            verification.save(
                update_fields=[
                    "status",
                    "reviewed_at",
                ]
            )

            # -------------------------------------------------
            # MARK ADDRESS VERIFIED
            #
            # Only a currently-unverified address is updated.
            # If another client already verified it, this updates
            # zero rows and does nothing.
            # -------------------------------------------------
            Address.objects.filter(
                pk=verification.client_address.address_id,
                is_verified=False,
            ).update(
                is_verified=True
            )

            # -------------------------------------------------
            # MAKE THIS CLIENT A SUPERUSER
            # -------------------------------------------------
            ClientAddress.objects.filter(
                pk=verification.client_address_id,
            ).update(
                is_super_user=True
            )

    def reject(self, note=None):
        """
        Reject verification with optional admin note.
        """

        self.status = self.STATUS_REJECTED
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
    date_created = models.DateTimeField (auto_created=True, null=True)
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


class Notification(models.Model):

    NOTIFICATION_TYPES = [
        ("booking", "Booking"),
        ("negotiation", "Negotiation"),
        ("shipment", "Shipment"),
        ("session", "Session"),
        ("rating", "Rating"),
        ("system", "System"),
    ]

    recipient = models.ForeignKey(
        ClientAuth,
        on_delete=models.CASCADE,
        related_name="legacy_notifications"
    )

    notification_type = models.CharField(
        max_length=50,
        choices=NOTIFICATION_TYPES
    )

    title = models.CharField(max_length=255)

    message = models.TextField()

    is_read = models.BooleanField(default=False)

    payload = models.JSONField(
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]