from django.db.models.signals import post_save
from django.dispatch import receiver
from ...audits.models import Negotiation, BookingItem

@receiver(post_save, sender=Negotiation)
def create_booking_item_on_accept(sender, instance, created, **kwargs):
    """
    Automatically create a BookingItem when a negotiation is accepted by the provider.
    """
    order = instance.service_order
    if not order:
        return

    # Only act if negotiation is accepted and last responder is provider
    if instance.status == "accepted" and instance.last_responder == "provider":
        # Check if a BookingItem already exists to avoid duplicates
        if not order.booking_items.exists():
            BookingItem.objects.create(
                order=order,
            )
