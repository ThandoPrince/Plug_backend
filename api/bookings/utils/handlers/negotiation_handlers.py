


from django.db import transaction

from api.bookings.services.celery_task import send_negotiation_round_notification




def handle_negotiation_round_created(payload):
    round_id = payload["round"].pk
    # on_commit: the worker must never run before the round exists in the DB.
    # Outside a transaction this fires immediately.
    transaction.on_commit(
        lambda: send_negotiation_round_notification.delay(round_id)
    )