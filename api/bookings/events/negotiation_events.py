# api/bookings/events/negotiation_events.py

from .base import Event


class NegotiationRoundCreatedEvent(Event):
    name = "negotiation.round_created"