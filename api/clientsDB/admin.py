from django.contrib import admin
from .models.models import AddressSuperUserVerification, ClientDetails, ClientAuth, Address, ClientAddress, ClientLoginHistory, DeviceToken, PendingAddressApproval, ClientNotification

# -----------------------------
# ClientAuth Admin
# -----------------------------
@admin.register(DeviceToken)
class DeviceTokenAdmin(admin.ModelAdmin):
    list_display = ('owner_email_or_username', 'device_type', 'device_name', 'os_version', 'app_version', 'last_seen')
    search_fields = ('client__email_address', 'admin__username', 'device_name', 'fcm_token')
    list_filter = ('device_type', 'last_seen')

    readonly_fields = ('fcm_token', 'device_type', 'device_name', 'os_version', 'app_version', 'last_seen')

    def owner_email_or_username(self, obj):
        if obj.client:
            return obj.client.email_address
        elif obj.admin:
            return obj.admin.username
        return "Unknown"
    owner_email_or_username.short_description = "Owner"

    
@admin.register(ClientAuth)
class ClientAuthAdmin(admin.ModelAdmin):
    list_display = ('email_address', 'mobile_number','total_failed_login_attempts', 'date_created','last_login_at' )
    search_fields = ('email_address', 'mobile_number')

@admin.register(ClientLoginHistory)
class ClientLoginHistoryAdmin(admin.ModelAdmin):
    list_display = ('client', 'successful','device_name', 'ip_address','created_at' )
    search_fields = ('ip_address', 'client')

# -----------------------------
# ClientDetails Admin
# -----------------------------
class ClientAddressInline(admin.TabularInline):
    model = ClientAddress
    extra = 0
    readonly_fields = ('house_administrator', 'is_super_user')
    can_delete = True

@admin.register(ClientDetails)
class ClientDetailsAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'client_profile', 'rating', 'is_active', 'client_ID')
    search_fields = ('first_name', 'last_name', 'client_profile__email_address', 'client_ID')
    list_filter = ('is_active',)
    inlines = [ClientAddressInline]

# -----------------------------
# Address Admin
# -----------------------------
class ClientAddressInlineForAddress(admin.TabularInline):
    model = ClientAddress
    extra = 0
    readonly_fields = ('client', 'is_owner', 'house_administrator', 'is_super_user', 'is_default')
    can_delete = False

@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ('formatted_address', 'locality', 'administrative_area_level_1', 'country', 'postal_code')
    search_fields = ('formatted_address', 'locality', 'administrative_area_level_1', 'country', 'postal_code')
    inlines = [ClientAddressInlineForAddress]



# -----------------------------
# ClientAddress Admin
# -----------------------------
@admin.register(ClientAddress)
class ClientAddressAdmin(admin.ModelAdmin):
    list_display = ('client', 'address', 'is_owner', 'house_administrator', 'is_super_user', 'is_default')
    search_fields = ('client__first_name', 'client__last_name', 'address__formatted_address')
    list_filter = ('is_owner', 'house_administrator', 'is_super_user', 'is_default')
    readonly_fields = ('house_administrator', 'is_super_user')

# -----------------------------
# PendingAddressApproval Admin
# -----------------------------
@admin.register(PendingAddressApproval)
class PendingAddressApprovalAdmin(admin.ModelAdmin):
    list_display = ('address', 'requested_by', 'owner', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('requested_by__first_name', 'requested_by__last_name', 'owner__first_name', 'owner__last_name', 'address__formatted_address')

# -----------------------------
# ClientNotification Admin
# -----------------------------
@admin.register(ClientNotification)
class ClientNotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'title', 'is_read', 'created_at')
    list_filter = ('is_read',)
    search_fields = ('recipient__first_name', 'recipient__last_name', 'title', 'message')


# -----------------------------
# AddressSuperUserVerification Admin
# -----------------------------
@admin.register(AddressSuperUserVerification)
class AddressSuperUserVerificationAdmin(admin.ModelAdmin):
    list_display = (
        'client_address',
        'status',
        'submitted_at',
        'reviewed_at',
    )

    list_filter = ('status', 'submitted_at')

    search_fields = (
        'client_address__client__first_name',
        'client_address__client__last_name',
        'client_address__address__formatted_address',
    )

    readonly_fields = (
        'client_address',
        'proof_of_residence',
        'id_document',
        'submitted_at',
    )

    actions = ['approve_verifications', 'reject_verifications']

    def approve_verifications(self, request, queryset):
        queryset.update(status='approved')
    approve_verifications.short_description = "Approve selected verifications"

    def reject_verifications(self, request, queryset):
        queryset.update(status='rejected')
    reject_verifications.short_description = "Reject selected verifications"
