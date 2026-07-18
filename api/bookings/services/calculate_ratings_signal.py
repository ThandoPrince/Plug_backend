from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db.models import Q, Avg, Count
from api.bookings.models import Rating


def update_provider_rating(provider):
    ratings = Rating.objects.filter(
        session__shipment__service_ordered__order__provider_for_service__provider=provider,
        rater_client__isnull=False,
        score__isnull=False
    )

    stats = ratings.aggregate(
        avg=Avg('score'),
        one_star=Count('id', filter=Q(score=1)),
        two_star=Count('id', filter=Q(score=2)),
    )

    avg = stats["avg"]

    if avg is None:
        provider.rating = None
    else:
        penalty = (
            (stats["two_star"] * 0.07) +
            (stats["one_star"] * 0.14)
        )

        provider.rating = round(max(1.0, avg - penalty), 2)

    provider.save(update_fields=["rating"])


def update_client_rating(client):
    ratings = Rating.objects.filter(
        session__shipment__service_ordered__order__client=client,
        rater_provider__isnull=False,
        score__isnull=False
    )

    stats = ratings.aggregate(
        avg=Avg('score'),
        one_star=Count('id', filter=Q(score=1)),
        two_star=Count('id', filter=Q(score=2)),
    )

    avg = stats["avg"]

    if avg is None:
        client.rating = None
    else:
        penalty = (
            (stats["two_star"] * 0.05) +
            (stats["one_star"] * 0.10)
        )

        client.rating = round(max(1.0, avg - penalty), 2)

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
