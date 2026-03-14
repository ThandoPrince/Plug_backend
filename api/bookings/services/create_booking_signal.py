from django.db.models.signals import post_save
from django.dispatch import receiver
from ...audits.models import Negotiation, BookingItem

@receiver(post_save, sender=Negotiation)
def create_booking_item_on_accept(sender, instance, created, **kwargs):
    order = instance.service_order
    if not order:
        return

    if instance.status == "accepted" and instance.last_responder == "provider":

        if not order.booking_items.exists():
            BookingItem.objects.create(
                order=order,
            )
