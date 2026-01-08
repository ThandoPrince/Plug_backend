from django.contrib import admin

from .models import ClientDetails, ClientAddress
from .models import ClientAuth
from .models import Address

admin.site.register(ClientDetails)
admin.site.register(ClientAuth)
admin.site.register(Address)
admin.site.register(ClientAddress)
