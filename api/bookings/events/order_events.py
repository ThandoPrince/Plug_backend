from .base import Event


class OrderCreatedEvent(Event):
    name = "order.created"


class OrderCancelledEvent(Event):
    name = "order.cancelled"


class OrderAcceptedEvent(Event):
    name = "order.accepted"


class OrderInTransitEvent(Event):
    name = "order.in_transit"


class OrderArrivedEvent(Event):
    name = "order.arrived"


class OrderRescheduledEvent(Event):
    name = "order.rescheduled"