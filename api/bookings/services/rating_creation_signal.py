from django.db.models.signals import pre_save
from django.dispatch import receiver
from api.bookings.models import Session, Rating

@receiver(pre_save, sender=Session)
def create_ratings_on_completion(sender, instance, **kwargs):
    """
    Auto-create exactly 2 ratings when a session transitions to COMPLETED:
    1. Client rating the provider
    2. Provider rating the client
    """
    if not instance.pk:
        return  # New session, nothing to compare

    try:
        previous = Session.objects.get(pk=instance.pk)
    except Session.DoesNotExist:
        return

    # Only trigger when session_status changes to completed
    if previous.session_status != "completed" and instance.session_status == "completed":
        booking_item = instance.shipment.service_ordered  # BookingItem instance
        order = booking_item.order
        client = order.client
        provider = order.provider_for_service.provider

        if client and provider:
            # Create rating for provider by client
            Rating.objects.get_or_create(
                session=instance,
                rater_client=client,
                defaults={"score": 0, "review": ""}
            )

            # Create rating for client by provider
            Rating.objects.get_or_create(
                session=instance,
                rater_provider=provider,
                defaults={"score": 0, "review": ""}
            )
