from django.contrib import admin
from django.urls import path
from django.http import JsonResponse
from api.clientsDB import views
from api.bookings import views as booking_views
from api.serviceProvidersDB import views as sp_views
from rest_framework.urlpatterns import format_suffix_patterns
from django.conf import settings
from django.conf.urls.static import static


def api_root(request):
    return JsonResponse({
        
    })

urlpatterns = [
    path('admin/', admin.site.urls),

  
    path('api/', api_root, name='api-root'),

    # Clients DB
    path('api/clientsDB/client-profiles/', views.clientProfile_list, name='client-profile-list'),
    path('api/clientsDB/clients/', views.client_list, name='client-list'),
    path('api/clientsDB/addresses/', views.address_list, name='address-list'),
    path('api/clientsDB/address-only/<str:email>', views.client_saved_addresses, name='address-only-list'),
    path('api/clientsDB/client-addresses/', views.client_address_list, name='client-address-list'),
    path('api/clientsDB/client-profiles/<str:email>', views.clientProfile_detail),
    path('api/clientsDB/clients/<str:email>/', views.client_detail, name='client-detail'),
    path('api/clientsDB/addresses/<int:id>', views.address_detail),
    path('api/clientsDB/client-addresses/<str:email>/', views.client_address_detail),
    path('api/clientsDB/default-address/<path:email>/', views.client_default_address),
    path("api/clientsDB/by-address/<int:address_id>/", views.clients_by_address, name="clients-by-address"),
    path("api/clientsDB/by-addresses/", views.clients_by_addresses, name="clients-by-addresses"),

    # Service Providers DB
    path('api/sp_profiles/', sp_views.sp_profile_list, name='sp_profile_list'),
    path('api/sp_profiles/<str:email>/', sp_views.sp_profile_detail, name='sp_profile_detail'),
    path('api/cost_of_service/<str:email>/', sp_views.costs_by_sp_email, name='cost_of_service'),
    path('api/service_groups/', sp_views.service_group_list, name='service_group_list'),
    path('api/service_groups/<str:group_id>/', sp_views.service_group_detail, name='service_group_detail'),
    path('api/services/', sp_views.service_list, name='service_list'),
    path('api/services/<int:pk>/', sp_views.service_detail, name='service_detail'),
    
    path('api/service_providers/', sp_views.service_provider_list_service, name='service_provider_list'),
    path('api/service_providers/<str:email>/', sp_views.service_provider_detail, name='service_provider_detail_by_email'),
    path('api/service_providers/by-service/<int:service_id>/', sp_views.providers_by_service, name='service_provider_detail_by_service'),
    path('api/serviceProvidersDB/address/<int:id>/', sp_views.service_provider_address_detail, name='service_provider_address'),
    path('api/serviceProvidersDB/address/', sp_views.service_provider_address, name='service_provider_address_detail'),
    path('api/service_providersDB/address-by-service/<int:service_id>/', sp_views.fetch_sp_addresses_by_service, name='service_provider_detail_by_service'),
    path('api/service_providersDB/sps_by_addresses/', sp_views.sps_by_addresses, name='service_provider_detail_by_service'),
    path('api/service_providers/sp/update-live-location/', sp_views.update_sp_live_location, name='service_provider_update_live_location'),
    path('api/service_providersDB/live-loc-by-service/<int:service_id>/', sp_views.fetch_sp_live_locations_by_service, name='fetch_service_provider_live_location_by_service'),
    path('api/service_providersDB/sps_by_live_location/', sp_views.sps_by_live_location, name='service_provider_by_live_location'),
    


    # Bookings
    path('api/bookings/service_orders/', booking_views.order_service_list, name='service_order_list'),
    path('api/bookings/service_orders/<int:pk>/', booking_views.order_service_detail, name='service_order_detail'),
    path('api/bookings/order_a_service/', booking_views.order_service_create, name='order_a_service'),
    path('api/bookings/get_shipment/by_sp_email/<str:provider_email>/', booking_views.get_shipments_by_provider, name='get_shipments_by_provider_email'),
    path('api/bookings/get_shipment/by_client_email/<str:client_email>/', booking_views.get_shipments_by_client, name='get_shipments_by_client_email'),
    path('api/bookings/shipment/<int:shipment_id>/route/', booking_views.shipment_routes_view, name='shipment_routes'),

    # Provider & Client endpoints
    path('api/bookings/sp_active_orders/<str:email>/', booking_views.bookings_by_invited_provider, name='sp_active_orders'),
    path('api/bookings/client_active_orders/<str:email>/', booking_views.pending_orders_by_client_email, name='client_active_orders'),

    # Negotiation endpoints
    path('api/bookings/service_orders/negotiations/', booking_views.negotiation_list, name='negotiation_list'),
    path('api/bookings/service_orders/negotiation/by-order/<int:order_id>/', booking_views.negotiations_by_order, name='negotiations_by_order'),
    path('api/bookings/negotiations/order/<int:order_id>/provider/<str:email>/', booking_views.negotiations_by_order_and_provider, name='negotiations_by_order_and_provider'),
    path('api/bookings/service_orders/negotiation/<int:pk>/', booking_views.negotiation_detail, name='negotiation_detail'),
    path('api/bookings/service_orders/negotiation/<int:negotiation_id>/provider_start_round/', booking_views.provider_start_round, name='negotiation_detail_provider_start_round'),
    path('api/bookings/service_orders/negotiation/rounds/<int:negotiation_id>/', booking_views.negotiation_rounds_by_negotiation, name='negotiation_round_list'),
    path('api/bookings/service_orders/negotiation/rounds/<int:negotiation_id>/client_start_round/', booking_views.client_start_round, name='negotiation_round_client_start_round'),
    path('api/bookings/service_orders/negotiation/provider_accepts_negotiation/<int:negotiation_id>/', booking_views.provider_accept_negotiation, name='provider_accepts_negotiation'),
    

  
]

urlpatterns = format_suffix_patterns(urlpatterns)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
