from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Avg
from api.bookings.models import Rating


def update_provider_rating(provider):
    avg = Rating.objects.filter(
        session__shipment__service_ordered__order__provider_for_service__provider=provider,
        rater_client__isnull=False,
        score__isnull=False
    ).aggregate(avg=Avg('score'))['avg']

    provider.rating = round(avg, 2) if avg else None
    provider.save(update_fields=["rating"])


def update_client_rating(client):
    avg = Rating.objects.filter(
        session__shipment__service_ordered__order__client=client,
        rater_provider__isnull=False,
        score__isnull=False
    ).aggregate(avg=Avg('score'))['avg']

    client.rating = round(avg, 2) if avg else None
    client.save(update_fields=["rating"])


@receiver(post_save, sender=Rating)
def rating_saved(sender, instance, **kwargs):
    booking_item = getattr(getattr(instance.session, 'shipment', None), 'service_ordered', None)
    if not booking_item:
        return

    if instance.rater_client:
        provider_service = getattr(booking_item.order, 'provider_for_service', None)
        provider = getattr(provider_service, 'provider', None)
        if provider:
            update_provider_rating(provider)


    elif instance.rater_provider:
        client = getattr(booking_item.order, 'client', None)
        if client:
            update_client_rating(client)


@receiver(post_delete, sender=Rating)
def rating_deleted(sender, instance, **kwargs):
    booking_item = getattr(getattr(instance.session, 'shipment', None), 'service_ordered', None)
    if not booking_item:
        return

    if instance.rater_client:
        provider_service = getattr(booking_item.order, 'provider_for_service', None)
        provider = getattr(provider_service, 'provider', None)
        if provider:
            update_provider_rating(provider)

    elif instance.rater_provider:
        client = getattr(booking_item.order, 'client', None)
        if client:
            update_client_rating(client)
