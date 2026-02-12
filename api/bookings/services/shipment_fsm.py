SHIPMENT_STATE_MACHINE = {
    "Pending": ["in_transit", "canceled"],
    "in_transit": ["arrived", "canceled"],
    "arrived": ["Pending", "failed", "canceled", "delivered"],
    "delivered": ["in_session"],
    "in_session": ["completed"],
    "canceled": [],
    "failed": [],
}
