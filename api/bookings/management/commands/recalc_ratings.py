# management/commands/recalc_ratings.py

from django.core.management.base import BaseCommand
from api.serviceProvidersDB.models import ServiceProvider
from api.bookings.services.calculate_ratings_signal import update_provider_rating

class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        for sp in ServiceProvider.objects.all():
            update_provider_rating(sp)
