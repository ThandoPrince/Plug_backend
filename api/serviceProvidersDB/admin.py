from django.contrib import admin
from .models import (
    Address, ServiceGroup, Service, ServiceProvider, SPProfile,
    ProviderService, CostOfService, SPLiveLocation, SPLocationHistory,
    ServiceProviderAvailability, SupportingDocument
)

# -----------------------------
# Address Admin
# -----------------------------
@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ('formatted_address', 'locality', 'administrative_area_level_1', 'country', 'postal_code')
    search_fields = ('formatted_address', 'locality', 'administrative_area_level_1', 'country', 'postal_code')

# -----------------------------
# Service Group Admin
# -----------------------------
@admin.register(ServiceGroup)
class ServiceGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'group_id')
    search_fields = ('name', 'group_id')

# -----------------------------
# Service Admin
# -----------------------------
class ProviderServiceInline(admin.TabularInline):
    model = ProviderService
    extra = 0
    readonly_fields = ('provider',)
    can_delete = False

@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('service_name', 'service_group', 'active_provider_count')
    search_fields = ('service_name',)
    list_filter = ('service_group',)
    inlines = [ProviderServiceInline]

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
    extra = 0
    readonly_fields = ('document_name', 'document_file', 'uploaded_at')
    can_delete = True

class SPLocationHistoryInline(admin.TabularInline):
    model = SPLocationHistory
    extra = 0
    readonly_fields = ('latitude', 'longitude', 'recorded_at')
    can_delete = False

@admin.register(ServiceProvider)
class ServiceProviderAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'id_number', 'gender', 'dob', 'is_active', 'is_discoverable', 'mobile_number', 'rating', 'location')
    search_fields = ('full_name', 'id_number', 'mobile_number')
    list_filter = ('is_active', 'is_discoverable', 'gender')
    inlines = [CostOfServiceInline, SupportingDocumentInline]

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
    list_display = ('provider', 'service')
    search_fields = ('provider__full_name', 'service__service_name')

# -----------------------------
# CostOfService Admin
# -----------------------------
@admin.register(CostOfService)
class CostOfServiceAdmin(admin.ModelAdmin):
    list_display = ('service', 'provider', 'base_price', 'negotiable')
    search_fields = ('service__service_name', 'provider__full_name')
    list_filter = ('negotiable',)

# -----------------------------
# SPLiveLocation Admin
# -----------------------------
@admin.register(SPLiveLocation)
class SPLiveLocationAdmin(admin.ModelAdmin):
    list_display = ('provider', 'latitude', 'longitude', 'updated_at')
    search_fields = ('provider__full_name',)
    readonly_fields = ('latitude', 'longitude', 'updated_at')

# -----------------------------
# SPLocationHistory Admin
# -----------------------------
@admin.register(SPLocationHistory)
class SPLocationHistoryAdmin(admin.ModelAdmin):
    list_display = ('provider', 'latitude', 'longitude', 'recorded_at')
    search_fields = ('provider__full_name',)
    readonly_fields = ('latitude', 'longitude', 'recorded_at')
    list_filter = ('provider',)

# -----------------------------
# ServiceProviderAvailability Admin
# -----------------------------
@admin.register(ServiceProviderAvailability)
class ServiceProviderAvailabilityAdmin(admin.ModelAdmin):
    list_display = ('provider', 'day_of_week', 'start_time', 'end_time')
    list_filter = ('day_of_week',)
    search_fields = ('provider__full_name',)
    readonly_fields = ()
