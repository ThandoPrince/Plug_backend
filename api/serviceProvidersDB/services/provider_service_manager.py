from django.db import transaction
from api.serviceProvidersDB.models import Service, ProviderService
from .service_validator import validate_service_submission


@transaction.atomic
def register_provider_service(provider, service_name, description="", service_group=None):
    """
    Link an existing service to a provider, or create a new service with a required group.
    """
    result = validate_service_submission(service_name, description)

  
    if result["status"] == "exists":
        service = result["service"]
        ProviderService.objects.get_or_create(provider=provider, service=service)
        return {"status": "linked_existing", "service": service}

 
    if result["status"] == "rejected":
        return result

   
    if result["status"] in ["auto_approve", "requires_review"]:
        if not service_group:
            raise ValueError("service_group is required for new services") 

        service = Service.objects.create(
            service_name=service_name.strip().title(),
            description=description,
            service_group=service_group,
            risk_level=service_group.category.risk_level,
            review_status="PENDING" if result["status"] == "requires_review" else "APPROVED"
        )

        ProviderService.objects.create(provider=provider, service=service)

        return {
            "status": result["status"],
            "service": service,
            "risk_level": result.get("risk_level")
        }