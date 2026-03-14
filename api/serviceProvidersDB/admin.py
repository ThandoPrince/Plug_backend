from django.contrib import admin
from .models import (
    Address, DeviceToken, ServiceGroup, Service, ServiceKeyword, ServiceProvider, SPProfile,
    ProviderService, CostOfService, SPLiveLocation, SPLocationHistory,
    ServiceProviderAvailability, SupportingDocument, ServiceCategory
)


# -----------------------------
# Address Admin
# -----------------------------
@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ('safe_formatted_address', 'locality', 'administrative_area_level_1', 'country', 'postal_code')
    search_fields = ('formatted_address', 'locality', 'administrative_area_level_1', 'country', 'postal_code')

    def safe_formatted_address(self, obj):
        return str(obj) or "Unnamed Address"
    safe_formatted_address.short_description = "Address"


@admin.register(ServiceKeyword)
class ServiceKeywordAdmin(admin.ModelAdmin):
    list_display = ('is_prohibited', 'risk_level', 'service', 'keyword', )
    search_fields = ('keyword', 'service')

    def safe_keyword(self, obj):
        return str(obj) or "Unknown Keyword"
    safe_keyword.short_description = "Keyword"

# -----------------------------
# Service Category Admin
# -----------------------------


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ('safe_name', 'category_id', 'safe_risk_level', 'requires_verification', 'requires_admin_approval')
    search_fields = ('name', 'category_id')

    def safe_name(self, obj):
        return obj.name or "Unnamed"
    safe_name.short_description = "Name"

    def safe_risk_level(self, obj):
        return str(obj.risk_level) if obj.risk_level else "UNKNOWN"
    safe_risk_level.short_description = "Risk Level"


# -----------------------------
# Service Group Admin
# -----------------------------
@admin.register(ServiceGroup)
class ServiceGroupAdmin(admin.ModelAdmin):
    list_display = ('safe_name', 'group_id', 'safe_category')
    search_fields = ('name', 'group_id')

    def safe_name(self, obj):
        return obj.name or "Unnamed"
    safe_name.short_description = "Name"

    def safe_category(self, obj):
        return str(obj.category) if obj.category else "No Category"
    safe_category.short_description = "Category"


# -----------------------------
# Service Admin
# -----------------------------
class ProviderServiceInline(admin.TabularInline):
    model = ProviderService
    extra = 0
    readonly_fields = ('safe_provider',)
    can_delete = False

    def safe_provider(self, obj):
        return str(obj.provider) if obj.provider else "No Provider"
    safe_provider.short_description = "Provider"

@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('service_name', 'safe_service_group', 'safe_active_provider_count', 'risk_level', 'review_status')
    search_fields = ('service_name',)
    list_filter = ('service_group', 'risk_level', 'review_status')
    inlines = [ProviderServiceInline]
    list_select_related = ('service_group',)

    def safe_service_group(self, obj):
        return str(obj.service_group) if obj.service_group else "No Group"
    safe_service_group.short_description = "Service Group"

    def safe_active_provider_count(self, obj):
        try:
            return obj.active_provider_count
        except Exception:
            return 0
    safe_active_provider_count.short_description = "Active Providers"


# -----------------------------
# ServiceProvider Admin
# -----------------------------
class CostOfServiceInline(admin.TabularInline):
    model = CostOfService
    extra = 0
    readonly_fields = ('base_price', 'negotiable', 'notes')
    can_delete = False

class SupportingDocumentInline(admin.TabularInline):
    model = SupportingDocument


    

class SPLocationHistoryInline(admin.TabularInline):
    model = SPLocationHistory
    extra = 0
    readonly_fields = ('latitude', 'longitude', 'recorded_at')
    can_delete = False

@admin.register(ServiceProvider)
class ServiceProviderAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'id_number', 'safe_gender', 'dob', 'is_active', 'safe_rating', 'safe_location')
    search_fields = ('full_name', 'id_number')
    list_filter = ('is_active', 'gender')
    inlines = [ SupportingDocumentInline, SPLocationHistoryInline]
    list_select_related = ('location',)

    def safe_gender(self, obj):
        return obj.gender or "Not specified"
    safe_gender.short_description = "Gender"

    def safe_rating(self, obj):
        return obj.rating or 0.0
    safe_rating.short_description = "Rating"

    def safe_location(self, obj):
        return str(obj.location) if obj.location else "No Location"
    safe_location.short_description = "Location"

@admin.register(DeviceToken)
class DeviceTokenAdmin(admin.ModelAdmin):
    list_display = ('owner_email_or_username', 'device_type', 'device_name', 'os_version', 'app_version', 'last_seen')
    search_fields = ('service_provider__email_address', 'admin__username', 'device_name', 'fcm_token')
    list_filter = ('device_type', 'last_seen')

    readonly_fields = ('fcm_token', 'device_type', 'device_name', 'os_version', 'app_version', 'last_seen')

    def owner_email_or_username(self, obj):
        if obj.service_provider:
            return obj.service_provider.email_address
        elif obj.admin:
            return obj.admin.username
        return "Unknown"
    owner_email_or_username.short_description = "Owner"


# -----------------------------
# SPProfile Admin
# -----------------------------
@admin.register(SPProfile)
class SPProfileAdmin(admin.ModelAdmin):
    list_display = ('email_address',)
    search_fields = ('email_address',)


# -----------------------------
# ProviderService Admin
# -----------------------------
@admin.register(ProviderService)
class ProviderServiceAdmin(admin.ModelAdmin):
    list_display = ('safe_provider', 'safe_service')
    search_fields = ('provider__full_name', 'service__service_name')

    def safe_provider(self, obj):
        return str(obj.provider) if obj.provider else "No Provider"
    safe_provider.short_description = "Provider"

    def safe_service(self, obj):
        return str(obj.service) if obj.service else "No Service"
    safe_service.short_description = "Service"


# -----------------------------
# CostOfService Admin
# -----------------------------
@admin.register(CostOfService)
class CostOfServiceAdmin(admin.ModelAdmin):
    list_display = ( 'base_price', 'negotiable')
    list_filter = ('negotiable',)

   

# -----------------------------
# SPLiveLocation Admin
# -----------------------------
@admin.register(SPLiveLocation)
class SPLiveLocationAdmin(admin.ModelAdmin):
    list_display = ('safe_provider', 'latitude', 'longitude', 'updated_at')
    search_fields = ('provider__full_name',)
    readonly_fields = ('latitude', 'longitude', 'updated_at')

    def safe_provider(self, obj):
        return str(obj.provider) if obj.provider else "No Provider"
    safe_provider.short_description = "Provider"


# -----------------------------
# SPLocationHistory Admin
# -----------------------------
@admin.register(SPLocationHistory)
class SPLocationHistoryAdmin(admin.ModelAdmin):
    list_display = ('safe_provider', 'latitude', 'longitude', 'recorded_at')
    search_fields = ('provider__full_name',)
    readonly_fields = ('latitude', 'longitude', 'recorded_at')
    list_filter = ('provider',)

    def safe_provider(self, obj):
        return str(obj.provider) if obj.provider else "No Provider"
    safe_provider.short_description = "Provider"


# -----------------------------
# ServiceProviderAvailability Admin
# -----------------------------
@admin.register(ServiceProviderAvailability)
class ServiceProviderAvailabilityAdmin(admin.ModelAdmin):
    list_display = ('safe_provider', 'get_day_of_week', 'start_time', 'end_time')
    list_filter = ('day_of_week',)
    search_fields = ('provider__full_name',)

    def safe_provider(self, obj):
        return str(obj.provider) if obj.provider else "No Provider"
    safe_provider.short_description = "Provider"

    def get_day_of_week(self, obj):
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        return days[obj.day_of_week] if obj.day_of_week in range(7) else "Unknown"
    get_day_of_week.short_description = "Day"