from django.conf import settings
from django.db import models
from django.forms import ValidationError
from api.bookings.utils.choices import BUILDING_TYPE_CHOICES
from django.contrib.auth.hashers import make_password
from django.db.models import Q
import hashlib
from django.db import transaction
from api.serviceProvidersDB.services.service_category_constants import RiskLevel, ServiceCategoryID, ServiceCategoryName


class Address(models.Model):
    id = models.AutoField(primary_key=True, editable=False, db_index=True)
    building_type  = models.CharField(max_length=100, choices=BUILDING_TYPE_CHOICES , default='house')
    unit_number = models.CharField(max_length=20, blank=True, default="")
    street_number = models.CharField(max_length=10, blank=True, null=True)
    route = models.CharField("Street Name", max_length=255, blank=True, null=True)
    locality = models.CharField("City/Town", max_length=100, blank=True, null=True)
    administrative_area_level_1 = models.CharField("Province/State", max_length=100, blank=True, null=True)
    formatted_address = models.CharField("Full Address", max_length=512, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    place_id = models.CharField(max_length=255, blank=True, null=True, unique=True, editable=False, db_index=True)

    def __str__(self):
        return (
            self.formatted_address
            or f"{self.street_number or ''} {self.route or ''}, {self.locality or ''}, {self.administrative_area_level_1 or ''}, {self.country or ''}".strip()
            or "Unnamed Address"
        )

    

class ServiceCategory(models.Model):

    category_id = models.CharField(
        max_length=10,
        primary_key=True,
        unique=True,
        choices= ServiceCategoryID.choices,
        db_index=True
    )

    name = models.CharField(max_length=100, unique=True, choices=ServiceCategoryName.choices, db_index=True)

    risk_level = models.CharField(
    max_length=20,
    choices=RiskLevel.choices,
    db_index=True
)

    requires_verification = models.BooleanField(default=False, db_index=True)
    requires_admin_approval = models.BooleanField(default=False, db_index=True)

    def __str__(self):
        return f"{self.name} ({self.risk_level})"

class ServiceGroup(models.Model):
    group_id = models.CharField(
        max_length=10,
        primary_key=True,
        editable=False,
        unique=True
    )
    name = models.CharField(max_length=100, unique=True)

    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.PROTECT,
        related_name="groups"
   , null=True )

    def __str__(self):
        return f"{self.name} ({self.group_id})"


class Service(models.Model):
    REVIEW_STATUS = [
        ("PENDING", "Pending Review"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    ]

    review_status = models.CharField(
        max_length=20,
        choices=REVIEW_STATUS,
        default="APPROVED",
        db_index=True
    )
    risk_level = models.CharField(
        max_length=20,
        choices=RiskLevel.choices,
        default=RiskLevel.LOW,
        db_index=True
    )
    service_id = models.AutoField(primary_key=True, editable=False, db_index=True)
    service_name = models.CharField(max_length=100, db_index=True)
    service_group = models.ForeignKey(
        ServiceGroup,
        on_delete=models.SET_NULL,
        null=True,
        related_name="services",
        db_index=True
    )
    description = models.TextField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.service_group and self.service_group.category:
            self.risk_level = self.service_group.category.risk_level
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.service_name}"


    

class ServiceKeyword(models.Model):
    keyword = models.CharField(max_length=100, unique=True, db_index=True)
    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name="keywords",
        null=True,
        blank=True,
        db_index=True
    )
    # Add this field to match your validator logic
    risk_level = models.CharField(
        max_length=20,
        choices=RiskLevel.choices,
        default=RiskLevel.LOW,
        db_index=True
    )
    is_prohibited = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)

    def __str__(self):
        return f"{self.keyword} ({self.risk_level})"
    

    
class ProviderRegistrationHistory(models.Model):

    email = models.CharField(max_length=255, null=True, blank=True)
    mobile_number = models.CharField(max_length=20, null=True, blank=True)

    successful = models.BooleanField(default=False)

    ip_address = models.GenericIPAddressField(null=True)
    user_agent = models.TextField(blank=True, null=True)
    device_name = models.CharField(max_length=100, blank=True, null=True)

    error_message = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True,null=True)

    class Meta:
        db_table = "sp_registration_history"

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
    


    

class SPProfile(models.Model):
    id = models.AutoField(primary_key=True, db_index=True)
    email_address = models.EmailField(unique=True, db_index=True)
    password = models.CharField(max_length=128)
    mobile_number = models.CharField(max_length=20, unique=True, null=True, db_index=True)
    Profile_CHOICES = [
        ("in-details", "In-Details"),
        ("in-address", "In-Address"),
        ("in-services", "In-Services"),
        ("in-cost", "In-Cost"),
        ("in_verification", "In-Verification"),
        ("completed", "Completed"),
    ]
    mfa_enabled = models.BooleanField(default=False)
    mfa_secret = models.CharField(max_length=32, null=True, blank=True)
    failed_login_attempts = models.PositiveIntegerField(default=0)
    total_failed_login_attempts = models.PositiveIntegerField(default=0)

    account_locked_until = models.DateTimeField(
    null=True,
    blank=True
)
    updated_at = models.DateField(auto_created=True,null=True, blank=True)
    date_created = models.DateField(null=True,blank=True,auto_created=True)

    last_login_at = models.DateTimeField(
    null=True,
    blank=True
)

    last_login_ip = models.GenericIPAddressField(
    null=True,
    blank=True
)
    is_profile_completed = models.CharField(default="in-details", choices=Profile_CHOICES, max_length= 20, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    class Meta:
        db_table = 'sp_profiles'
        indexes = [
            models.Index(fields=['email_address', 'is_active', 'is_profile_completed','mfa_enabled','mobile_number'],name='sp_profile_lookup_idx'),
            models.Index(fields=['id'])
        ]

    @property
    def is_authenticated(self):
        return True
    @property
    def is_anonymous(self):
        return False

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def __str__(self):
        return f"SPProfile: {self.email_address}"
    
class ProviderLoginHistory(models.Model):
    service_provider = models.ForeignKey(
        SPProfile,
        on_delete=models.CASCADE, null=True
    )
    successful = models.BooleanField(default=False)
    identifier = models.CharField(max_length=100, null=True)
    user_agent = models.TextField(blank=True, null=True)
    ip_address = models.GenericIPAddressField(null=True,
    blank=True,)
    device_name = models.CharField(max_length=100, blank=True, null=True)



    
    
class ServiceProvider(models.Model):

    rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True, default=0.0, db_index=True)
    full_name = models.CharField(max_length=85, db_index=True)
    gender = models.CharField(max_length=50, null=True, blank=True, db_index=True)
    id_number = models.CharField(max_length=20, db_index=True)
    sp_description = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Brief description of yourself and qualities"
    )
    dob = models.DateField()

    updated_at = models.DateField(auto_now=True, db_index=True, null=True)
    date_created = models.DateField(auto_now_add=True, db_index=True,null=True)

    is_active = models.BooleanField(default=True)
    location = models.ForeignKey(Address, on_delete=models.SET_NULL, null=True, db_index=True)
    sp_profile = models.OneToOneField(
        SPProfile,
        on_delete=models.CASCADE,
        primary_key=True,
        db_index=True
    )

    class Meta:
        indexes = [
            models.Index(fields=['rating']),
            models.Index(fields=['dob']),
            models.Index(fields=['sp_profile']),
            models.Index(fields=['date_created']),
            models.Index(fields=['updated_at']),
            models.Index(fields=['id_number', 'gender', 'full_name']),
        ]

    def service_provider_upload_path(instance, filename):
        safe_email = instance.sp_profile.email_address.replace('@', '_at_')
        return f"profile_images/providers/{safe_email}/{filename}"

    profile_image = models.ImageField(
        upload_to=service_provider_upload_path,
        null=True,
        blank=True
    )




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
        default="firebase",
        db_index=True
    )
    ip_address = models.GenericIPAddressField(null=True,
    blank=True,)

    service_provider = models.ForeignKey(
        'SPProfile',
        on_delete=models.CASCADE,
        related_name="device_tokens",
        db_index=True
    )

    fcm_token = models.CharField(max_length=512, db_index=True)
    device_type = models.CharField(max_length=20, choices=DEVICE_TYPES, db_index=True)
    device_name = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    os_version = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    app_version = models.CharField(max_length=20, blank=True, null=True, db_index=True)
    last_seen = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["service_provider", "fcm_token"],
                name="unique_token_per_service_provider"
            )
        ]
        indexes = [
            models.Index(fields=['fcm_token','device_type','service_provider']),
            

        ]

    def __str__(self):
        return f"{self.service_provider.email_address} - {self.device_name or self.device_type}"
    
class CostOfService(models.Model):
    base_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, db_index=True)
    negotiable = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True, null=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['base_price']),
            

        ]

    
    def __str__(self):
        return f"Base Price: {self.base_price}"
    



class CostOfServiceImage(models.Model):
    cost_of_service = models.ForeignKey(
        'CostOfService',
        on_delete=models.CASCADE,
        related_name='images', db_index=True
    )

    image = models.ImageField(upload_to='service_images/', db_index=True)

    uploaded_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['cost_of_service']),
            
        ]

    def save(self, *args, **kwargs):
        if self.cost_of_service_id:
            existing_count = CostOfServiceImage.objects.filter(
                cost_of_service_id=self.cost_of_service_id
            ).count()

            if existing_count >= 5 and not self.pk:
                raise ValidationError(
                    "Maximum of 5 images allowed per service."
                )

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Service Image {self.id} for Cost {self.cost_of_service_id}"
    




class ProviderService(models.Model):
    provider = models.ForeignKey(
        'ServiceProvider',
        on_delete=models.CASCADE,
        related_name='provider_services',
        db_index=True
    )
    is_active = models.BooleanField(default=True, db_index=True)
    id = models.AutoField(primary_key=True, editable=False, db_index=True),

    service = models.ForeignKey(
        'Service',
        on_delete=models.CASCADE,
        related_name='service_providers', db_index=True   
    )

    cost_of_service = models.OneToOneField(
        'CostOfService',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='provider_service', db_index=True
    )
    has_uploaded_affidavit = models.BooleanField(
    default=False,
    db_index=True,
)
    is_affidavit_verified = models.BooleanField(
    default=False,
    db_index=True,
)
    date_created = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )
    

    is_primary = models.BooleanField(default=False, db_index=True)

    class Meta:
        unique_together = ('provider', 'service')

        constraints = [
            models.UniqueConstraint(
                fields=['provider'],
                condition=Q(is_primary=True),
                name='unique_primary_service_per_provider'
            )
        ]

        indexes = [
            models.Index(fields=['provider','is_active']),
            models.Index(fields=['date_created']),
            models.Index(fields=['service']),
            models.Index(fields=['cost_of_service']),
            models.Index(fields=['is_primary']),
            models.Index(fields=['is_affidavit_verified']),
            models.Index(fields=['has_uploaded_affidavit']),

        ]

    def clean(self):
        # Only validate when creating a new active service
        if self.pk is None and self.is_active:
            existing_count = ProviderService.objects.filter(
                provider=self.provider,
                is_active=True,
            ).count()

            if existing_count >= 3:
                raise ValidationError(
                    "A provider can only have a maximum of 3 active services."
                )
    def save(self, *args, **kwargs):
        with transaction.atomic():

            is_new = self.pk is None

            if is_new and not ProviderService.objects.filter(
                provider=self.provider,
                is_active=True,
            ).exists():
                self.is_primary = True

            if self.is_primary:
                ProviderService.objects.filter(
                    provider=self.provider,
                    is_primary=True,
                ).exclude(pk=self.pk).update(
                    is_primary=False,
                )

            self.full_clean()
            super().save(*args, **kwargs)
    
class ProviderServiceHistory(models.Model):
    ACTION_CHOICES = [
        ("linked", "Linked"),
        ("updated", "Updated"),
        ("primary_changed", "Primary Changed"),
        ("deactivated", "Deactivated"),
        ("reactivated", "Reactivated"),
    ]

    provider_service = models.ForeignKey(
        ProviderService,
        on_delete=models.CASCADE,
        related_name="history",
    )

    provider = models.ForeignKey(
        ServiceProvider,
        on_delete=models.CASCADE,
        related_name="provider_service_history",
    )

    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
    )

    action = models.CharField(
        max_length=30,
        choices=ACTION_CHOICES,
        db_index=True,
    )

    notes = models.TextField(
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    created_by = models.ForeignKey(
        SPProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]


class ProviderServiceAffidavit(models.Model):

    class VerificationStatus(models.TextChoices):
        APPROVED = "APPROVED", "Approved"
        PENDING = "PENDING", "Pending"
        REJECTED = "REJECTED", "Rejected"
        EXPIRED = "EXPIRED", "Expired"
        SUPERSEDED = "SUPERSEDED", "Superseded"

    affidavit_id = models.AutoField(primary_key=True)

    provider_service = models.ForeignKey(
        "ProviderService",
        on_delete=models.CASCADE,
        related_name="affidavits",
        db_index=True,
    )

    affidavit = models.FileField(
        upload_to="provider/affidavits/%Y/%m/",
    )

    version = models.PositiveIntegerField()

    is_current = models.BooleanField(
        default=True,
        db_index=True,
    )

    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
        db_index=True,
    )

    # ---------------------------------------------------
    # File Metadata
    # ---------------------------------------------------

    document_hash = models.CharField(
        max_length=64,
        unique=True,
        editable=False,
        db_index=True,null=True,
    )

    original_filename = models.CharField(
        max_length=255,
        db_index=True,null=True,
    )

    file_size = models.BigIntegerField(
        db_index=True,null=True,
    )

    mime_type = models.CharField(
        max_length=100,
        db_index=True,null=True,
    )

    # ---------------------------------------------------
    # AI Verification
    # ---------------------------------------------------

    ai_confidence = models.FloatField(
        default=0.0,null=True,
    )

    ai_result = models.JSONField(
        default=dict,
        blank=True,null=True,
    )

    verification_engine = models.CharField(
        max_length=50,
        default="Plug AI v1",null=True,
    )

    verified_at = models.DateTimeField(
        auto_now_add=True,null=True,
    )

    # ---------------------------------------------------
    # Legacy Review (Audit Only)
    # ---------------------------------------------------

    review_notes = models.TextField(
        blank=True,
        null=True,
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reviewed_affidavits",
    )

    class Meta:
        ordering = ["-version"]

        constraints = [
            models.UniqueConstraint(
                fields=["provider_service", "version"],
                name="unique_affidavit_version",
            ),
            models.UniqueConstraint(
                fields=["provider_service"],
                condition=Q(is_current=True),
                name="one_current_affidavit",
            ),
        ]
        indexes = [
            models.Index(fields=['verified_at','verification_status']),
            models.Index(fields=['ai_result','verification_status']),
            models.Index(fields=['ai_confidence']),
            models.Index(fields=['verification_status','provider_service']),
            models.Index(fields=['provider_service']),
            

        ]

    def __str__(self):
        return (
            f"{self.provider_service.provider.full_name} - "
            f"{self.provider_service.service.service_name} "
            f"(v{self.version})"
        )
    



class ProviderQualification(models.Model):

    class DocumentType(models.TextChoices):
        QUALIFICATION = "QUALIFICATION", "Qualification"
        CERTIFICATE = "CERTIFICATE", "Certificate"
        LICENSE = "LICENSE", "Licence"
        PORTFOLIO = "PORTFOLIO", "Portfolio"
        INSURANCE = "INSURANCE", "Insurance"
        REFERENCE = "REFERENCE", "Reference"
        OTHER = "OTHER", "Other"

    class VerificationStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    provider_service = models.ForeignKey(
        "ProviderService",
        on_delete=models.CASCADE,
        related_name="qualifications",
    )

    

    document_type = models.CharField(
        max_length=30,
        choices=DocumentType.choices,
        default=DocumentType.QUALIFICATION,
    )

    title = models.CharField(
        max_length=200,
    )

    issuing_body = models.CharField(
        max_length=200,
        blank=True,
    )

    issue_date = models.DateField(
        null=True,
        blank=True,
    )

    expiry_date = models.DateField(
        null=True,
        blank=True,
    )

    document = models.FileField(
        upload_to="provider/qualifications/%Y/%m/",
    )

    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
        db_index=True,
    )

    verified = models.BooleanField(
        default=False,
        db_index=True,
    )

    verified_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    rejection_reason = models.TextField(
        blank=True,
        null=True,
    )

    uploaded_at = models.DateTimeField(
        auto_now_add=True,
    )

    def __str__(self):
        return self.title

    
class SupportingDocument(models.Model):

    ID_TYPE_CHOICES = [
        ("greenbook", "Green Book"),
        ("card", "ID Card"), 
    ]
    provider = models.ForeignKey(
        'ServiceProvider',
        on_delete=models.CASCADE,
        related_name='documents',
        db_index=True
    )

    id_type = models.CharField(max_length=20, choices=ID_TYPE_CHOICES, default='card')

    front_file = models.FileField(upload_to='sp_ids/', blank=True, null=True)
    back_file = models.FileField(upload_to='sp_ids/', blank=True, null=True)

    # 🔥 NEW FIELDS
    liveness_video = models.FileField(upload_to='sp_liveness/', blank=True, null=True)
    
    verification_status = models.CharField(
        max_length=20,
        default="pending"
    )

    verification_score = models.FloatField(null=True, blank=True)
    risk_level = models.CharField(max_length=20, default="unknown")

    ai_response = models.JSONField(null=True, blank=True)

    uploaded_at = models.DateTimeField(auto_now_add=True)




class SPLiveLocation(models.Model):
    provider = models.OneToOneField(
        ServiceProvider,
        on_delete=models.CASCADE,
        related_name="live_location",
        db_index=True,
    )

    latitude = models.DecimalField(max_digits=9, decimal_places=6,db_index=True,)
    longitude = models.DecimalField(max_digits=9, decimal_places=6,db_index=True,)

    suburb = models.CharField(
        max_length=100,
        blank=True,
        null=True,db_index=True,
    )

    city = models.CharField(
        max_length=100,
        blank=True,
        null=True,db_index=True,
    )

    province = models.CharField(
        max_length=100,
        blank=True,
        null=True,db_index=True,
    )

    updated_at = models.DateTimeField(auto_now=True,db_index=True,)

    class Meta: 
        indexes = [ models.Index(fields=["provider","latitude", "longitude"]),
                    models.Index(fields=["updated_at"]),
                    models.Index(fields=["suburb","city"]),
                     ]
    
class SPLocationHistory(models.Model):
    provider = models.ForeignKey(ServiceProvider, on_delete=models.CASCADE, related_name="location_history", db_index=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, db_index=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6,db_index=True)
    recorded_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-recorded_at']
        indexes = [
            models.Index(fields=["provider"]),
    ]

    def __str__(self):
        return f"{self.provider.full_name} - ({self.latitude}, {self.longitude}) @ {self.recorded_at}"








class ServiceProviderAvailability(models.Model):
    provider = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='availabilities')
    day_of_week = models.IntegerField(
        choices=[(i, day) for i, day in enumerate(
            ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        )]
    )
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        unique_together = ('provider', 'day_of_week', 'start_time', 'end_time')

    def clean(self):
       
        if self.start_time >= self.end_time:
            raise ValidationError("Start time must be before end time.")

     
        overlapping = ServiceProviderAvailability.objects.filter(
            provider=self.provider,
            day_of_week=self.day_of_week
        ).exclude(pk=self.pk)  

        for avail in overlapping:
          
            if (self.start_time < avail.end_time and self.end_time > avail.start_time):
                raise ValidationError(
                    f"Availability overlaps with existing time range: {avail.start_time} - {avail.end_time}"
                )

    def save(self, *args, **kwargs):
        self.full_clean()  
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.provider} - {self.get_day_of_week_display()} {self.start_time}-{self.end_time}"
