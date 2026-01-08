from django.apps import AppConfig


class BookingsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api.bookings'
    
    def ready(self):
        import api.bookings.signals 