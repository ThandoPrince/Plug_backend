from django.contrib import admin
from .models import (
    Negotiation, OrderService, Rating, ServicePicture, Session,
    SessionLocationPing, SessionToken, Shipment, OrderHistory,
    BookingItem, ShipmentRoute, ShipmentRouteHistory
)

# -----------------------------
# OrderService Admin
# -----------------------------
@admin.register(OrderService)
class OrderServiceAdmin(admin.ModelAdmin):
    list_display = (
        'order_id', 'title', 'client', 'provider_for_service', 'status', 'requested_date'
    )
    list_filter = ('status', 'is_broadcasted')
    search_fields = (
        'client__first_name', 'client__last_name', 'provider_for_service__sp_profile__full_name'
    )
    readonly_fields = ('date_and_time_created',)

# -----------------------------
# BookingItem Admin
# -----------------------------
@admin.register(BookingItem)
class BookingItemAdmin(admin.ModelAdmin):
    list_display = ('item_id', 'order', 'get_service_name', 'get_provider_name')

    def get_service_name(self, obj):
        return obj.order.service_required.service_name if obj.order.service_required else "N/A"
    get_service_name.short_description = "Service"

    def get_provider_name(self, obj):
        return str(obj.order.provider_for_service) if obj.order.provider_for_service else "N/A"
    get_provider_name.short_description = "Provider"

# -----------------------------
# Shipment Admin
# -----------------------------
@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = (
        'shipment_id', 'service_ordered', 'shipment_schedule_date', 'shipment_schedule_time', 'shipment_status'
    )
    list_filter = ('shipment_status', 'shipment_confirmation')
    search_fields = ('service_ordered__order__client__first_name',)

# -----------------------------
# ShipmentRoute & History Admin
# -----------------------------
@admin.register(ShipmentRoute)
class ShipmentRouteAdmin(admin.ModelAdmin):
    list_display = ('route_id', 'shipment', 'is_active', 'recalculated', 'created_at')

@admin.register(ShipmentRouteHistory)
class ShipmentRouteHistoryAdmin(admin.ModelAdmin):
    list_display = ('history_id', 'shipment', 'reason', 'created_at')
    list_filter = ('reason',)
    ordering = ('-created_at',)

# -----------------------------
# Session Admin & Rating Inline
# -----------------------------
class RatingInline(admin.TabularInline):
    model = Rating
    extra = 0
    max_num = 2
    readonly_fields = ('rater_client', 'rater_provider', 'score', 'review')
    can_delete = False

@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ('session_id', 'shipment', 'session_status', 'checkin_time', 'checkout_time')
    list_filter = ('session_status',)
    search_fields = ('shipment__service_ordered__order__client__first_name', 'shipment__service_ordered__order__provider_for_service__sp_profile__full_name')
    inlines = [RatingInline]

# -----------------------------
# Ratings Admin (optional separate view)
# -----------------------------
@admin.register(Rating)
class RatingAdmin(admin.ModelAdmin):
    list_display = (
        'id',  # use 'id' instead of 'rating_id'
        'session',
        'score',
        'review',
        'rater_client',
        'rater_provider',
        'created_at',
    )
    list_filter = ('session', 'rater_client', 'rater_provider')
    search_fields = ('session__shipment__shipment_id', 'rater_client__first_name', 'rater_provider__full_name')

# -----------------------------
# Negotiation Admin
# -----------------------------
@admin.register(Negotiation)
class NegotiationAdmin(admin.ModelAdmin):
    list_display = ('negotiation_id', 'service_order', 'provider_for_negotiation', 'status', 'round_count', 'created_at')
    list_filter = ('status',)
    search_fields = ('service_order__client__first_name', 'provider_for_negotiation__sp_profile__full_name')

# -----------------------------
# ServicePicture Admin
# -----------------------------
@admin.register(ServicePicture)
class ServicePictureAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'uploaded_at')
    readonly_fields = ('uploaded_at',)

# -----------------------------
# SessionToken Admin
# -----------------------------
@admin.register(SessionToken)
class SessionTokenAdmin(admin.ModelAdmin):
    list_display = ('token_id', 'session', 'shipment', 'checkin_token', 'token_expiry', 'created_at')
    readonly_fields = ('checkin_token', 'token_expiry', 'created_at')

# -----------------------------
# SessionLocationPing Admin
# -----------------------------
@admin.register(SessionLocationPing)
class SessionLocationPingAdmin(admin.ModelAdmin):
    list_display = ('ping_id', 'session', 'latitude', 'longitude', 'inside_geofence', 'created_at')
    list_filter = ('inside_geofence',)
    readonly_fields = ('created_at',)

# -----------------------------
# OrderHistory Admin
# -----------------------------
@admin.register(OrderHistory)
class OrderHistoryAdmin(admin.ModelAdmin):
    list_display = ('history_id', 'order', 'previous_status', 'new_status', 'status_change_date')
    readonly_fields = ('status_change_date',)
