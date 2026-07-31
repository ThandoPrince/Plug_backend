ACTIVE_PROVIDER_BOOKING_STATUSES = {
    "pending",
    "in_progress",
    "in-negotiation",
    "rescheduled",
    "overdue",
}


def is_visible_to_provider(order):
    return order.status in ACTIVE_PROVIDER_BOOKING_STATUSES