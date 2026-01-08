from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model


class Address(models.Model):

    latitude = models.DecimalField(max_digits=9, decimal_places=7, blank=True, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=7, blank=True, null=True)
    place_id = models.IntegerField( blank=True, null=True)
    street_number = models.CharField(max_length=10, blank=True, null=True)
    route = models.CharField("Street Name", max_length=255, blank=True, null=True)
    locality = models.CharField("City/Town", max_length=100)
    administrative_area_level_1 = models.CharField("Province/State", max_length=100)
    formatted_address = models.CharField("Full Address", max_length=512, blank=False, null=True,editable=False)
    country = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)

    clients = models.ManyToManyField('ClientDetails', through='ClientAddress', related_name='addresses')

    def get_formatted_address(self):
        parts = [self.street_number, self.route, self.locality, self.administrative_area_level_1]
        return ", ".join(filter(None, parts))
    
    def save(self, *args, **kwargs):
        self.formatted_address = self.get_formatted_address()
        super().save(*args, **kwargs)

    def __str__(self):
     return self.formatted_address or self.get_formatted_address()


class ClientAuth(models.Model):
    email_address = models.EmailField(primary_key=True, max_length=100)
    mobile_number = models.CharField(max_length=60, default='0719503706')
    password = models.CharField(max_length=128)
    

    def __str__(self):
        return f"{self.email_address} - {self.password}"


class ClientDetails(models.Model):
    first_name = models.CharField(max_length=100, null=True, blank=True)
    last_name = models.CharField(max_length=100, null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    client_profile = models.OneToOneField(ClientAuth, on_delete=models.CASCADE, primary_key=True)
    rating = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True, default=0.0)
    client_pp = models.ImageField(upload_to='client_profile_pics', default='default.jpg', null=True, blank=True)
    client_ID = models.CharField(max_length=20, blank=True, null=True)
    is_active = models.BooleanField(default=True)




    def __str__(self):
        return f"{self.first_name} - {self.last_name}-{self.client_profile.email_address}"


class ClientAddress(models.Model):
    RESIDENTIAL = "Residential Address"
    VACATION = "Vacation Address"
    ADDRESS_TYPE_CHOICES = [
        (RESIDENTIAL, "Residential Address"),
        (VACATION, "Vacation Address"),
    ]

    client = models.ForeignKey(ClientDetails, on_delete=models.CASCADE)
    address = models.ForeignKey(Address, on_delete=models.CASCADE)
    is_owner = models.BooleanField("Are you the owner of the household?", default=False)
    house_administrator = models.BooleanField(default=False, editable=False, null=True)
    is_super_user = models.BooleanField(default=False, editable=False, null=True)
    address_type = models.CharField(
        max_length=100,
        choices=ADDRESS_TYPE_CHOICES,
        default=RESIDENTIAL
    )

    # ✅ belongs to ClientAddress, not Address
    is_default = models.BooleanField(default=False)

    is_verified = models.BooleanField(default=False)

    class Meta:
        unique_together = ('client', 'address')

    def clean(self):
        # Ensure only one default per client
        if self.is_default:
            other_defaults = ClientAddress.objects.filter(
                client=self.client,
                is_default=True
            ).exclude(pk=self.pk)
            if other_defaults.exists():
                raise ValidationError("Each client can only have one default address.")

        # Owners restriction
        if self.is_owner:
            owner_count = ClientAddress.objects.filter(
                address=self.address,
                is_owner=True
            ).exclude(pk=self.pk).count()
            if owner_count >= 2:
                raise ValidationError("Only two clients can be marked as owners of this address.")

    def save(self, *args, **kwargs):
        self.full_clean()

        # Auto-assign admin/super_user roles
        if self.is_owner:
            self.house_administrator = True
            self.is_super_user = True
        else:
            self.house_administrator = False
            self.is_super_user = False

        # ✅ if this is default, unset others for this client
        if self.is_default:
            ClientAddress.objects.filter(
                client=self.client,
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Client: {self.client.first_name} - {self.address} (Default: {self.is_default}, Owner: {self.is_owner})"

    
class PendingAddressApproval(models.Model):
    address = models.ForeignKey(Address, on_delete=models.CASCADE)
    requested_by = models.ForeignKey(ClientDetails, on_delete=models.CASCADE)
    owner = models.ForeignKey(ClientDetails, related_name='approver', on_delete=models.CASCADE)
    status = models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

User = get_user_model()

class ClientNotification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='client_notifications')
    title = models.CharField(max_length=255)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"To {self.recipient} - {self.title}"


