from django.contrib import admin
from django.urls import path
from django.http import JsonResponse
from api.clientsDB import views
from api.bookings import views as booking_views
from api.clientsDB.urls import media_debug
from api.serviceProvidersDB import views as sp_views
from rest_framework.urlpatterns import format_suffix_patterns
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from django.urls import re_path
from rest_framework_simplejwt.views import TokenRefreshView


def api_root(request):
    return JsonResponse({
        
    })

urlpatterns = [
    path('admin/', admin.site.urls),

  
    path('api/', api_root, name='api-root'),

    # Clients DB
  

    path(
        'api/client-auth/',
        views.get_my_auth,
        name='client-auth-by-email'
    ), ##used
    path(
        "api/sp/token/refresh/",
        TokenRefreshView.as_view(),
        name="token_refresh",
    ),

    path(
        "api/client/token/refresh/",
        TokenRefreshView.as_view(),
        name="client_token_refresh",
    ),
    path('api/clientsDB/addresses/', views.address_list, name='address-list'),
    path('api/clientsDB/address-only/<int:client_id>', views.client_saved_addresses, name='address-only-list'),
    path('api/clientsDB/client-addresses/', views.client_address_list, name='client-address-list'),
    path("api/client_devices/register-device-token/", views.register_device_token, name="register-device-token"), ##used
    path('api/clientsDB/client-profiles/', views.clientProfile_detail, name='client-profile-detail'),
    path('api/clientsDB/clients/', views.client_detail, name='client-detail'),
    path('api/clientsDB/addresses/<int:id>/', views.address_detail), ##used
    path('api/clientsDB/client-addresses/<int:client_id>/', views.client_address_detail),
    path('api/clientsDB/default-addresses/', views.client_default_address, name='client-default-addresses'),
    path("api/clientsDB/by-address/<int:address_id>/", views.clients_by_address, name="clients-by-address"),
    path("api/clientsDB/by-addresses/", views.clients_by_addresses, name="clients-by-addresses"),
    path("api/clientsDB/client/register/", views.register_client, name="client-register"), 
    path("api/address-client/set-default/<int:address_id>/", views.set_default_address, name="set-default-address"),
    path("api/clientsDB/client/", views.get_my_profile, name="get-my-profile"),
    path("api/clientsDB/client/profile/complete/", views.complete_profile, name="complete-client-profile"), ##used
    path("api/clientsDB/client/add-residential-address/", views.add_residential_address, name="add-residential-address"), ##used
    path("api/clientsDB/login/", views.client_login, name="client-login"),  ##used
    path("clientsDB/address/verify/<int:client_address_id>/", views.submit_address_verification, name="client-address-verification"),
    path(
    "api/client/reset-password/",
    views.reset_client_password,
    name="reset_client_password"
),
path('api/client/get-sp-ratings/<int:sp_id>/', booking_views.get_sp_ratings, name='service_provider_address_detail'),
    

    # Service Providers DB
    path('api/sp_profile/register/', sp_views.sp_register, name='sp_profile_register'),
    path('api/sp_login/', sp_views.sp_login, name='sp_login'),
    path('api/sp_service/cost/<int:service_id>/', sp_views.update_cost_of_service, name='sp_cost_of'),
    
    path('api/sp_details/upload/', sp_views.patch_sp_profile, name='sp_details_upload'),
    path('api/sp/upload/address_document/', sp_views.sp_add_address_document, name='sp_details_upload'),
    path('api/service/upload_or_create/<int:provider_id>/', sp_views.submit_service, name='sp_service_create  '),
    path('api/sp_profiles/', sp_views.sp_profile_list, name='sp_profile_list'),
    path('api/sp-profile/', sp_views.sp_profile_detail, name='sp_profile_detail'),
    path('api/cost_of_service/<int:provider_id>/', sp_views.costs_by_sp, name='cost_of_service'),
    path(
        'api/cost_of_service/<int:provider_id>/<int:service_id>/',
        sp_views.costs_by_sp,
        name='cost_by_sp_email_and_service'
    ),
    path(
        'api/cost_of_service/<int:cost_id>/images/',
        sp_views.get_cost_of_service_images_by_cost_id,
        name='get_cost_of_service_images_by_cost_id'
    ),
    # path('api/service_groups/', sp_views.service_group_list, name='service_group_list'),
    # path('api/service_groups/<str:group_id>/', sp_views.service_group_detail, name='service_group_detail'),
    # path('api/services/<int:pk>/', sp_views.service_detail, name='service_detail'),
    path('api/services/', sp_views.service_list, name='service_list'), ##NEEDS TO BE CACHED
    path('api/approved_services/', sp_views.approved_services_list, name='service_list'),
    

path(
    'api/service_providerDB/sps_by_live_location/',
    sp_views.sps_by_live_location,
    name='service_provider_by_live_location'
),


    
    path('api/service_providers/', sp_views.service_provider_list_service, name='service_provider_list'),
    path('api/service_providers/<int:provider_id>/', sp_views.service_provider_detail, name='service_provider_detail_by_email'),
    path('api/service_provider_my/<int:id>/', sp_views.service_provider_details, name='service_provider_details_by_email'),
    path('api/service_providers/by-service/<int:service_id>/', sp_views.providers_by_service, name='service_provider_detail_by_service'),
    path('api/serviceProvidersDB/address/<int:id>/', sp_views.service_provider_address_detail, name='service_provider_address'),
    path('api/serviceProvidersDB/address/', sp_views.service_provider_address, name='service_provider_address_detail'),

  
    path('api/service_providers/sp/update-live-location/', sp_views.update_sp_live_location, name='service_provider_update_live_location'),
    path('api/service_providersDB/live-loc-by-service/<int:service_id>/', sp_views.fetch_sp_live_locations_by_service, name='fetch_service_provider_live_location_by_service'),
    
    
    path('api/service_provider/services/<int:provider_id>/',sp_views.get_provider_services,name='get_provider_services_by_email'),
    path('api/serviceProvider/cost/<int:cost_id>/images/',sp_views.upload_service_images,name='upload_service_images'),
    path('api/providers/toggle-active/',sp_views.toggle_provider_active,name='toggle-provider-active'),
    path('api/sp/register/device-token/', sp_views.register_device_token, name='register-device-token'),
    
    


    # Bookings
    path('api/bookings/service_orders/', booking_views.order_service_list, name='service_order_list'),
    path('api/bookings/service_orders/<int:pk>/', booking_views.order_service_detail, name='service_order_detail'),
    path('api/bookings/provider_service_orders/<int:pk>/', booking_views.provider_order_service_detail, name='service_order_detail'),
    path('api/bookings/order_a_service/', booking_views.order_service_create, name='order_a_service'),
    path('api/bookings/get_shipment/by_sp_email/<str:provider_email>/', booking_views.get_shipments_by_provider, name='get_shipments_by_provider_email'),
    path('api/bookings/get_shipment/by_shipment_id/<int:shipment_id>/', booking_views.get_shipment_by_id, name='get_shipment_by_id'),
    path('api/bookings/get_shipment/by_client_email/<int:client_id>/', booking_views.get_shipments_by_client, name='get_shipments_by_client_email'),
    path('api/bookings/shipment/<int:shipment_id>/route/', booking_views.shipment_routes_view, name='shipment_routes'),
    path('api/bookings/shipment/<int:shipment_id>/change_status/', booking_views.change_shipment_status, name='change_shipment_status'),
    path('api/bookings/shipment/<int:shipment_id>/confirm/', booking_views.confirm_shipment, name='confirm_shipment'),
    path(
        'api/bookings/<int:order_id>/final-price/',
        booking_views.patch_order_final_price,
        name='patch_order_final_price'
    ),

     # Session  endpoints
    path('api/bookings/sessions/confirm_checkin/', booking_views.confirm_checkin, name='confirm_checkin'),
    path('api/bookings/sessions/get_checkin_token/<int:shipment_id>/', booking_views.get_checkin_token, name='get_checkin_token'),
    path('api/bookings/sessions/get_session_by_shipment/<int:shipment_id>/', booking_views.get_session_by_shipment, name='get_session_by_shipment'),
    path('api/bookings/sessions/geofence_check/<int:session_id>/', booking_views.session_geofence_check, name='session_geofence_check'),
    path('api/bookings/sessions/<int:session_id>/pings/', booking_views.session_location_pings, name='session_location_pings'),
    path('api/bookings/sessions/<int:session_id>/latest-ping/', booking_views.session_latest_ping, name='session_latest_ping'),
    path('api/bookings/sessions/<int:session_id>/update_status/', booking_views.update_session_status, name='update_session_status'),
    path('api/bookings/sessions/<int:session_id>/check_status/', booking_views.check_session_status, name='check_session_status'),
  

    # Provider & Client endpoints
    path('api/bookings/sp_active_orders/<int:id>/', booking_views.bookings_by_invited_provider, name='sp_active_orders'),
    path('api/bookings/client_active_orders/<int:client_id>/', booking_views.pending_orders_by_client_id, name='client_active_orders'),
    path('api/bookings/get_ratings/by_client_email/<int:client_id>/', booking_views.get_ratings_by_client_email, name='client_ratings'),
    path('api/bookings/get_ratings/by_provider_email/<str:email>/', booking_views.get_ratings_by_provider_email, name='provider_ratings'),
    path('api/bookings/<int:session_id>/rate-provider/<str:client_email>/', booking_views.submit_client_rating, name='client_submit_rating'),
    path('api/bookings/<int:session_id>/rate-client/<str:provider_email>/', booking_views.submit_provider_rating, name='provider_submit_rating'),
    path('api/bookings/cancel_order/', booking_views.cancel_order, name='client_cancel_order'),

    # Negotiation endpoints
    path('api/bookings/service_orders/negotiations/', booking_views.negotiation_list, name='negotiation_list'),
    path('api/bookings/service_orders/negotiation/by-order/<int:order_id>/', booking_views.negotiations_by_order, name='negotiations_by_order'),
    path('api/bookings/negotiations/order/<int:order_id>/provider/<str:email>/', booking_views.negotiations_by_order_and_provider, name='negotiations_by_order_and_provider'),
    path('api/bookings/service_orders/negotiation/<int:pk>/', booking_views.negotiation_detail, name='negotiation_detail'),
    path('api/bookings/service_orders/negotiation/<int:negotiation_id>/provider_start_round/', booking_views.provider_start_round, name='negotiation_detail_provider_start_round'),
    path('api/bookings/service_orders/negotiation/rounds/<int:negotiation_id>/', booking_views.negotiation_rounds_by_negotiation, name='negotiation_round_list'),
    path('api/bookings/service_orders/negotiation/rounds/<int:negotiation_id>/client_start_round/', booking_views.client_start_round, name='negotiation_round_client_start_round'),
    path('api/bookings/service_orders/negotiation/provider_accepts_negotiation/<int:negotiation_id>/', booking_views.provider_accept_negotiation, name='provider_accepts_negotiation'),
    path(
        "api/bookings/service_orders/<int:order_id>/update/",
        booking_views.update_order_service,
        name="update_order_service"
    ),
    path("media-debug/", media_debug),

  
]

urlpatterns = format_suffix_patterns(urlpatterns)
urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
