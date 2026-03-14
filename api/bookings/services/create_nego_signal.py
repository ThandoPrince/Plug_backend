from django.db.models.signals import post_save, m2m_changed
from django.dispatch import receiver
from ..models import BookingItem, OrderService, Negotiation, NegotiationRound, Shipment
from api.serviceProvidersDB.models import ProviderService


def create_negotiation_with_initial_round(order: OrderService, provider: ProviderService):
    """
    Creates a negotiation for the order and provider.
    Only creates a client-initiated round for record-keeping, 
    does NOT move order to 'in-negotiation'.
    """
    negotiation, created = Negotiation.objects.get_or_create(
        service_order=order,
        provider_for_negotiation=provider,
        defaults={
            "proposed_price": order.proposal_price,
            "base_price": order.base_price,
            "last_responder": "client",
        }
    )
    if created:
        # Initial client round for record-keeping; does NOT trigger in-negotiation status
        NegotiationRound.objects.create(
            negotiation=negotiation,
            sender_type="client",
            offered_price=order.proposal_price,
            message="Initial proposal"
        )


@receiver(post_save, sender=OrderService)
def create_negotiations_for_new_order(sender, instance, created, **kwargs):
    if created and instance.is_negotiated:
        for provider in instance.invited_providers.all():
            create_negotiation_with_initial_round(instance, provider)


@receiver(m2m_changed, sender=OrderService.invited_providers.through)
def create_negotiation_for_added_providers(sender, instance, action, pk_set, **kwargs):
    if action == "post_add" and instance.is_negotiated:
        new_providers = ProviderService.objects.filter(pk__in=pk_set)
        for provider in new_providers:
            create_negotiation_with_initial_round(instance, provider)


@receiver(post_save, sender=NegotiationRound, dispatch_uid="handle_negotiation_round")
def handle_negotiation_round(sender, instance, created, **kwargs):
    if created:
        negotiation = instance.negotiation
        order = negotiation.service_order

        #  Only trigger in-negotiation if provider starts the round
        if instance.sender_type == "provider":
            if order.status != "in-negotiation":
                order.status = "in-negotiation"
                order.is_negotiated = True
                order.save(update_fields=["status", "is_negotiated"])

        #  If provider accepts during the round, finalize price
        if negotiation.status == "accepted" and instance.sender_type == "provider":
            order.final_price = instance.offered_price
            order.status = "accepted"
            order.save(update_fields=["final_price", "status"])

@receiver(post_save, sender=Negotiation)
def create_booking_item_and_shipment(sender, instance, **kwargs):
    negotiation = instance
    order = negotiation.service_order

    # Only proceed if negotiation accepted by provider
    if negotiation.status != "accepted" or negotiation.last_responder != "provider":
        return

    # ------- 1. Create BookingItem if missing -------
    booking_item, created_item = BookingItem.objects.get_or_create(order=order)

    # ------- 2. Create Shipment only if none exists for this booking item -------
    if not booking_item.shipments.exists():
        Shipment.objects.create(
            
            service_ordered=booking_item,  # keep if you still need it
            shipment_schedule_date=order.requested_date,
            shipment_schedule_time=order.requested_date_time,
            shipment_status="Pending",
            shipment_confirmation=False,
        )

    # ------- 3. Update order status & price -------
    if order.status != "accepted":
        order.status = "accepted"
        order.final_price = negotiation.provider_response_price or negotiation.proposed_price
        order.save(update_fields=["status", "final_price"])
