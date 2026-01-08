from django.contrib import admin
from .models import CostOfService, ProviderService, SPLiveLocation, SPLocationHistory, Service
from .models import ServiceProvider
from .models import ServiceGroup
from .models import Address
from .models import SPProfile, ServiceProviderAvailability

admin.site.register(Service)
admin.site.register(ServiceProvider)
admin.site.register(ServiceGroup)
admin.site.register(Address)
admin.site.register(SPProfile)
admin.site.register(CostOfService)
admin.site.register(ServiceProviderAvailability)
admin.site.register(ProviderService)
admin.site.register(SPLiveLocation)
admin.site.site_header = "Plug Service Providers Admin" 
admin.site.register(SPLocationHistory)


