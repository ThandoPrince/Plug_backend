from django.contrib import admin
from .models import  Negotiation,  OrderService, ServicePicture, Session, SessionToken, Shipment, OrderHistory, BookingItem, ShipmentRoute, ShipmentRouteHistory

admin.site.register(OrderService)

admin.site.register(Shipment)
admin.site.register(OrderHistory)
admin.site.register(ServicePicture)

admin.site.register(BookingItem)
admin.site.register(Negotiation)
admin.site.register(Session)
admin.site.register(SessionToken)

admin.site.register(ShipmentRoute)
admin.site.register(ShipmentRouteHistory)

