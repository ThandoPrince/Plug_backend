from django.contrib import admin
from .models import  Negotiation,  OrderService, ServicePicture, Shipment, OrderHistory, BookingItem, ShipmentRoute, ShipmentRouteHistory

admin.site.register(OrderService)

admin.site.register(Shipment)
admin.site.register(OrderHistory)
admin.site.register(ServicePicture)

admin.site.register(BookingItem)
admin.site.register(Negotiation)


admin.site.register(ShipmentRoute)
admin.site.register(ShipmentRouteHistory)

