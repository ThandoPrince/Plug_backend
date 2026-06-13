from django.core.exceptions import ObjectDoesNotExist

from api.clientsDB.models.models import ClientAuth, ClientDetails
from api.serviceProvidersDB.models import SPProfile, ServiceProvider

def get_client_auth(request):
    """
    Returns the authenticated ClientAuth.
    """
    try:
        return ClientAuth.objects.get(
            id=request.user.id
        )
    except ClientAuth.DoesNotExist:
        raise ObjectDoesNotExist(
            "Authenticated client not found."
        )
    
def get_client_details(request):
    """
    Returns the authenticated ClientDetails.
    """
    try:
        return ClientDetails.objects.select_related(
            "client_profile"
        ).get(
            client_profile=request.user
        )
    except ClientDetails.DoesNotExist:
        raise ObjectDoesNotExist(
            "Client profile not found."
        )
    
def get_sp_profile(request):
    """
    Returns the authenticated SPProfile.
    """
    try:
        return SPProfile.objects.get(
            id=request.user.id
        )
    except SPProfile.DoesNotExist:
        raise ObjectDoesNotExist(
            "Authenticated provider not found."
        )
    
def get_service_provider(request):
    """
    Returns the authenticated ServiceProvider.
    """
    try:
        return ServiceProvider.objects.select_related(
            "sp_profile"
        ).get(
            sp_profile=request.user
        )
    except ServiceProvider.DoesNotExist:
        raise ObjectDoesNotExist(
            "Service provider profile not found."
        )