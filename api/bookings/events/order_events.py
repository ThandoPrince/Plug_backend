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

class ProviderLocationUpdatedEvent(Event):
    name = "provider.location_updated"


class ProviderDeclinedInvitationEvent(Event):
    name = "provider.declined_invitation"

class NegotiationCreatedEvent(Event):
    name = "negotiation.created"

class ProviderOrderCancelledEvent(Event):
    name = "provider.order_cancelled"