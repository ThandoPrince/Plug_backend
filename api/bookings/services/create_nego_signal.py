import logging
from django.db import transaction
from django.db.models.signals import post_save, m2m_changed
from django.dispatch import receiver
from ..models import BookingItem, OrderService, Negotiation, NegotiationRound, Shipment
from api.serviceProvidersDB.models import ProviderService

logger = logging.getLogger(__name__)

def create_negotiation_with_initial_round(order: OrderService, provider: ProviderService):
    """
    Creates a negotiation tracking slot for the order and target provider.
    Initializes a client-initiated proposal round for state integrity.
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
        NegotiationRound.objects.create(
            negotiation=negotiation,
            sender_type="client",
            offered_price=order.proposal_price,
            message="Initial proposal"
        )
        logger.info(f"[Signal] Created negotiation loop for Order {order.pk}, ProviderService {provider.pk}")


@receiver(m2m_changed, sender=OrderService.invited_providers.through)
def create_negotiation_for_added_providers(sender, instance, action, pk_set, **kwargs):
    """
    Listens to the M2M compilation bridge between OrderService and SPProfile.
    Uses the exact provider_for_service linked on the order to prevent duplicate creation.
    """
    if action == "post_add" and instance.is_negotiated:
        if not pk_set:
            return

        # Core Fix: Match the profile IDs AND target the explicit ProviderService requested
        new_providers = ProviderService.objects.filter(
            provider__sp_profile_id__in=pk_set,
            pk=getattr(instance, "provider_for_service_id", None)
        )

        # Fallback: If no single specific service matches, fallback to distinct entries to prevent duplication
        if not new_providers.exists():
            new_providers = ProviderService.objects.filter(
                provider__sp_profile_id__in=pk_set,
                service=getattr(instance, "service_required", None)
            ).distinct('provider')

        for provider in new_providers:
            create_negotiation_with_initial_round(instance, provider)


@receiver(post_save, sender=NegotiationRound, dispatch_uid="handle_negotiation_round")
def handle_negotiation_round(sender, instance, created, **kwargs):
    """
    Manages internal status lifecycles based on structural negotiation rounds.
    """
    if created:
        negotiation = instance.negotiation
        order = negotiation.service_order

        if instance.sender_type == "provider":
            if order.status != "in-negotiation":
                order.status = "in-negotiation"
                order.is_negotiated = True
                order.save(update_fields=["status", "is_negotiated"])

        if negotiation.status == "accepted" and instance.sender_type == "provider":
            order.final_price = instance.offered_price
            order.status = "accepted"
            order.save(update_fields=["final_price", "status"])


@receiver(post_save, sender=Negotiation)
def create_booking_item_and_shipment(sender, instance, **kwargs):
    """
    Fires shipment workflows and operations only when negotiation reaches a binding 'accepted' state.
    """
    negotiation = instance
    order = negotiation.service_order

    if negotiation.status != "accepted" or negotiation.last_responder != "provider":
        return

    booking_item, created_item = BookingItem.objects.get_or_create(order=order)

    if not booking_item.shipments.exists():
        Shipment.objects.create(
            service_ordered=booking_item,
            shipment_schedule_date=order.requested_date,
            shipment_schedule_time=order.requested_date_time,
            shipment_status="Pending",
            shipment_confirmation=False,
        )

    if order.status != "accepted":
        order.status = "accepted"
        order.final_price = negotiation.provider_response_price or negotiation.proposed_price
        order.save(update_fields=["status", "final_price"])