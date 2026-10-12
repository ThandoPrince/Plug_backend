from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from bookings.models import OrderHistory, OrderService  # adjust to your app's import path

# Frozen "current time" used by every test.
NOW = timezone.make_aware(datetime(2026, 10, 8, 10, 0))


def make_order(offset, status="pending", reschedule_count=0):
    """
    Create an order scheduled at NOW + offset.

    The order is created without a date (so save() skips rescheduling) and the
    schedule is then written with .update(), which simulates real life: the
    order was valid when created, and time has passed since.
    """
    order = OrderService.objects.create(status=status)
    scheduled = NOW + offset
    OrderService.objects.filter(pk=order.pk).update(
        requested_date=scheduled.date(),
        requested_date_time=scheduled.time(),
        reschedule_count=reschedule_count,
    )
    order.refresh_from_db()
    return order


def scheduled_of(order):
    return timezone.make_aware(
        datetime.combine(order.requested_date, order.requested_date_time)
    )


class AutoRescheduleTests(TestCase):
    def setUp(self):
        patcher = patch("django.utils.timezone.now", return_value=NOW)
        patcher.start()
        self.addCleanup(patcher.stop)

    # --- no-op cases ---------------------------------------------------------

    def test_future_order_is_untouched(self):
        order = make_order(timedelta(hours=2))
        order.save()
        order.refresh_from_db()

        self.assertEqual(order.status, "pending")
        self.assertEqual(order.reschedule_count, 0)
        self.assertEqual(scheduled_of(order), NOW + timedelta(hours=2))

    def test_exactly_ten_minutes_away_is_untouched(self):
        order = make_order(timedelta(minutes=10))
        order.save()
        order.refresh_from_db()

        self.assertEqual(order.status, "pending")
        self.assertEqual(order.reschedule_count, 0)

    def test_ineligible_status_is_untouched(self):
        order = make_order(timedelta(hours=-1), status="accepted")
        order.save()
        order.refresh_from_db()

        self.assertEqual(order.status, "accepted")
        self.assertEqual(order.reschedule_count, 0)

    # --- rescheduling --------------------------------------------------------

    def test_inside_ten_minute_window_moves_forward_one_hour(self):
        order = make_order(timedelta(minutes=5))
        order.save()
        order.refresh_from_db()

        self.assertEqual(order.status, "rescheduled")
        self.assertEqual(order.reschedule_count, 1)
        self.assertEqual(scheduled_of(order), NOW + timedelta(minutes=65))

    def test_order_in_the_past_hops_multiple_times(self):
        # 3h in the past: 07:00 -> 08:00 -> 09:00 -> 10:00 -> 11:00 (4 hops)
        order = make_order(timedelta(hours=-3))
        order.save()
        order.refresh_from_db()

        self.assertEqual(order.status, "rescheduled")
        self.assertEqual(order.reschedule_count, 4)
        self.assertEqual(scheduled_of(order), NOW + timedelta(hours=1))

    # --- the 72 reschedule cap ----------------------------------------------

    def test_cap_already_reached_marks_overdue(self):
        order = make_order(timedelta(hours=-1), reschedule_count=72)
        order.save()
        order.refresh_from_db()

        self.assertEqual(order.status, "overdue")
        self.assertEqual(order.reschedule_count, 72)

    def test_cap_reached_mid_loop_marks_overdue(self):
        order = make_order(timedelta(hours=-5), reschedule_count=70)
        order.save()
        order.refresh_from_db()

        self.assertEqual(order.status, "overdue")
        self.assertEqual(order.reschedule_count, 72)

    # --- history -------------------------------------------------------------

    def test_first_reschedule_writes_history(self):
        order = make_order(timedelta(minutes=5))
        order.save()

        entry = OrderHistory.objects.get(order=order)
        self.assertEqual(entry.previous_status, "pending")
        self.assertEqual(entry.new_status, "rescheduled")

    def test_repeat_reschedule_is_not_logged(self):
        # Documents current behavior: status stays "rescheduled", so no new
        # history row is written for the 2nd, 3rd... automatic reschedule.
        order = make_order(timedelta(minutes=5), status="rescheduled")
        order.save()

        self.assertEqual(OrderHistory.objects.filter(order=order).count(), 0)

    # --- known pitfalls ------------------------------------------------------

    def test_save_with_update_fields_does_not_persist_reschedule(self):
        # Documents a bug: reschedule changes are made in memory but never
        # written, and a history row is still created.
        order = make_order(timedelta(minutes=5))
        order.notes = "changed"
        order.save(update_fields=["notes"])
        order.refresh_from_db()

        self.assertEqual(order.status, "pending")  # DB never updated
        self.assertEqual(order.reschedule_count, 0)
        self.assertEqual(OrderHistory.objects.filter(order=order).count(), 1)