from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from api.bookings.models import OrderHistory, OrderService
from api.bookings.services.celery_task import (
    auto_reschedule_orders,
    expire_overdue_orders,
)

# Frozen "current time" used by every test.
NOW = timezone.make_aware(datetime(2026, 10, 8, 10, 0))


def make_order(offset, status="pending", reschedule_count=0):
    """Create an order scheduled at NOW + offset."""
    scheduled = NOW + offset
    return OrderService.objects.create(
        status=status,
        requested_date=scheduled.date(),
        requested_date_time=scheduled.time(),
        reschedule_count=reschedule_count,
    )


def make_overdue(age):
    """An overdue order whose overdue clock started `age` ago."""
    order = make_order(timedelta(hours=-1), status="overdue", reschedule_count=18)
    OrderService.objects.filter(pk=order.pk).update(overdue_at=NOW - age)
    order.refresh_from_db()
    return order


def run_task(order):
    auto_reschedule_orders()  # call directly, no broker needed
    order.refresh_from_db()


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
        run_task(order)

        self.assertEqual(order.status, "pending")
        self.assertEqual(order.reschedule_count, 0)
        self.assertEqual(scheduled_of(order), NOW + timedelta(hours=2))

    def test_exactly_ten_minutes_away_is_untouched(self):
        order = make_order(timedelta(minutes=10))
        run_task(order)

        self.assertEqual(order.status, "pending")
        self.assertEqual(order.reschedule_count, 0)

    def test_ineligible_status_is_untouched(self):
        order = make_order(timedelta(hours=-1), status="accepted")
        run_task(order)

        self.assertEqual(order.status, "accepted")
        self.assertEqual(order.reschedule_count, 0)

    # --- rescheduling --------------------------------------------------------

    def test_inside_ten_minute_window_moves_forward_four_hours(self):
        order = make_order(timedelta(minutes=5))
        run_task(order)

        self.assertEqual(order.status, "rescheduled")
        self.assertEqual(order.reschedule_count, 1)
        self.assertEqual(scheduled_of(order), NOW + timedelta(hours=4, minutes=5))

    def test_order_in_the_past_hops_multiple_times(self):
        # 12h in the past: 22:00 -> 02:00 -> 06:00 -> 10:00 -> 14:00 (4 hops)
        order = make_order(timedelta(hours=-12))
        run_task(order)

        self.assertEqual(order.status, "rescheduled")
        self.assertEqual(order.reschedule_count, 4)
        self.assertEqual(scheduled_of(order), NOW + timedelta(hours=4))

    def test_crosses_midnight(self):
        # 23:55 the previous day is in the past relative to NOW (10:00)
        order = make_order(timedelta(hours=-10, minutes=-5))
        run_task(order)

        self.assertGreaterEqual(scheduled_of(order), NOW + timedelta(minutes=10))

    # --- the reschedule cap (18 x 4h = 3 days) -------------------------------

    def test_cap_already_reached_marks_overdue(self):
        order = make_order(timedelta(hours=-1), reschedule_count=18)
        run_task(order)

        self.assertEqual(order.status, "overdue")
        self.assertEqual(order.reschedule_count, 18)

    def test_cap_reached_mid_loop_marks_overdue(self):
        # 01:00 -> 05:00 (17) -> 09:00 (18), still in the past, so overdue
        order = make_order(timedelta(hours=-9), reschedule_count=16)
        run_task(order)

        self.assertEqual(order.status, "overdue")
        self.assertEqual(order.reschedule_count, 18)

    def test_capped_overdue_order_is_not_reprocessed(self):
        make_order(timedelta(hours=-1), status="overdue", reschedule_count=18)
        self.assertEqual(auto_reschedule_orders(), 0)

    # --- task behavior -------------------------------------------------------

    def test_task_is_idempotent(self):
        order = make_order(timedelta(minutes=5))
        run_task(order)
        run_task(order)

        self.assertEqual(order.reschedule_count, 1)

    def test_save_no_longer_reschedules(self):
        order = make_order(timedelta(minutes=5))
        order.notes = "changed"
        order.save()
        order.refresh_from_db()

        self.assertEqual(order.status, "pending")
        self.assertEqual(order.reschedule_count, 0)
        self.assertEqual(OrderHistory.objects.filter(order=order).count(), 0)

    # --- history -------------------------------------------------------------

    def test_first_reschedule_writes_history(self):
        order = make_order(timedelta(minutes=5))
        run_task(order)

        entry = OrderHistory.objects.get(order=order)
        self.assertEqual(entry.previous_status, "pending")
        self.assertEqual(entry.new_status, "rescheduled")

    def test_repeat_reschedule_is_not_logged(self):
        # Status stays "rescheduled", so no new history row is written.
        order = make_order(timedelta(minutes=5), status="rescheduled")
        run_task(order)

        self.assertEqual(OrderHistory.objects.filter(order=order).count(), 0)

    # --- overdue -> expired --------------------------------------------------

    def test_reaching_cap_starts_overdue_clock(self):
        order = make_order(timedelta(hours=-1), reschedule_count=18)  # pending, at cap
        run_task(order)

        self.assertEqual(order.status, "overdue")
        self.assertEqual(order.overdue_at, NOW)

    def test_overdue_for_more_than_a_day_expires(self):
        order = make_overdue(timedelta(hours=25))
        expire_overdue_orders()
        order.refresh_from_db()

        self.assertEqual(order.status, "expired")

    def test_overdue_exactly_one_day_expires(self):
        order = make_overdue(timedelta(days=1))
        expire_overdue_orders()
        order.refresh_from_db()

        self.assertEqual(order.status, "expired")

    def test_overdue_under_a_day_is_not_expired(self):
        order = make_overdue(timedelta(hours=23))
        expire_overdue_orders()
        order.refresh_from_db()

        self.assertEqual(order.status, "overdue")

    def test_expiry_writes_history(self):
        order = make_overdue(timedelta(hours=25))
        expire_overdue_orders()

        entry = OrderHistory.objects.get(order=order, new_status="expired")
        self.assertEqual(entry.previous_status, "overdue")

    def test_legacy_overdue_without_timestamp_starts_clock_instead_of_expiring(self):
        order = make_order(timedelta(hours=-1), status="overdue", reschedule_count=18)
        OrderService.objects.filter(pk=order.pk).update(overdue_at=None)

        expire_overdue_orders()
        order.refresh_from_db()

        self.assertEqual(order.status, "overdue")
        self.assertEqual(order.overdue_at, NOW)

    def test_expire_task_is_idempotent(self):
        make_overdue(timedelta(hours=25))
        self.assertEqual(expire_overdue_orders(), 1)
        self.assertEqual(expire_overdue_orders(), 0)
        