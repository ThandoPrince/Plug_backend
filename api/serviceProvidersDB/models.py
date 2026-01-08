from django.conf import settings
from django.db import models
from django.forms import ValidationError


class Address(models.Model):
    id = models.AutoField(primary_key=True, editable=False)
    street_number = models.CharField(max_length=10, blank=True, null=True)
    route = models.CharField("Street Name", max_length=255, blank=True, null=True)
    locality = models.CharField("City/Town", max_length=100, blank=True, null=True)
    administrative_area_level_1 = models.CharField("Province/State", max_length=100, blank=True, null=True)
    formatted_address = models.CharField("Full Address", max_length=512, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
    place_id = models.CharField(max_length=255, blank=True, null=True, unique=True, editable=False)

    def __str__(self):
        return (
            self.formatted_address
            or f"{self.street_number or ''} {self.route or ''}, {self.locality or ''}, {self.administrative_area_level_1 or ''}, {self.country or ''}".strip()
            or "Unnamed Address"
        )




class ServiceGroup(models.Model):
    group_id = models.CharField(
        max_length=10,
        primary_key=True,
        editable=False,
        unique=True
    )
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return f"{self.name} ({self.group_id})"


class Service(models.Model):
    service_id = models.AutoField(primary_key=True, editable=False)
    service_name = models.CharField(max_length=100)
    service_group = models.ForeignKey(ServiceGroup, on_delete=models.SET_NULL, null=True)
    description = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.service_name}"
    @property
    def active_provider_count(self):
        return self.providers.filter(is_active=True).count()
    

class ProviderService(models.Model):
    provider = models.ForeignKey('ServiceProvider', on_delete=models.CASCADE)
    service = models.ForeignKey(Service, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('provider', 'service')

    def __str__(self):
        return f"{self.provider.full_name} - {self.service.service_name}"
    



class SPProfile(models.Model):
    email_address = models.EmailField(primary_key=True)
    password = models.CharField(max_length=128)

    def __str__(self):
        return f"SPProfile: {self.email_address}"
    
class SupportingDocument(models.Model):
    provider = models.ForeignKey('ServiceProvider', on_delete=models.CASCADE, related_name='documents')
    document_name = models.CharField(max_length=100)
    document_file = models.FileField(upload_to='supporting_documents/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.document_name} for {self.provider.full_name}"


class ServiceProvider(models.Model):
    rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    full_name = models.CharField(max_length=85)
    gender = models.CharField(max_length=50, null=True, blank=True)
    id_number = models.CharField(max_length=20)
    sp_description = models.CharField(max_length=255, null=True, blank=True, help_text="Brief description of yourself and qualities")
    dob = models.DateField()
    is_active = models.BooleanField(default=True)
    is_discoverable = models.BooleanField(default=True)
    mobile_number = models.CharField(max_length=20)
    location = models.ForeignKey(Address, on_delete=models.SET_NULL, null=True)
    sp_profile = models.OneToOneField(SPProfile, on_delete=models.CASCADE, primary_key=True)
    services = models.ManyToManyField(Service, through='ProviderService', related_name='providers')
    

    def service_provider_upload_path(instance, filename):
        
        safe_email = instance.sp_profile.email_address.replace('@', '_at_')
        return f"profile_images/providers/{safe_email}/{filename}"

    profile_image = models.ImageField(upload_to=service_provider_upload_path, null=True, blank=True)

class SPLiveLocation(models.Model):
    provider = models.OneToOneField(
        ServiceProvider, 
        on_delete=models.CASCADE, 
        related_name="live_location"
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.provider.full_name} - ({self.latitude}, {self.longitude}) @ {self.updated_at}"
    
class SPLocationHistory(models.Model):
    provider = models.ForeignKey(ServiceProvider, on_delete=models.CASCADE, related_name="location_history")
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-recorded_at']

    def __str__(self):
        return f"{self.provider.full_name} - ({self.latitude}, {self.longitude}) @ {self.recorded_at}"





class CostOfService(models.Model):
    service = models.ForeignKey(Service, on_delete=models.CASCADE, related_name='costs')
    provider = models.ForeignKey(ServiceProvider, on_delete=models.CASCADE)
    base_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    negotiable = models.BooleanField(default=True)
    notes = models.TextField(blank=True, null=True, )

    class Meta:
        unique_together = ['service', 'provider']
    def __str__(self):
        return f"{self.service.service_name} - {self.provider.full_name} - Base Price: {self.base_price}"


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
