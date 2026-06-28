SHIPMENT_STATE_MACHINE = {
    "Pending": ["in_transit", "canceled","rescheduled"],
    "rescheduled": ["in_transit", "canceled"],
    
    "in_transit": ["arrived", "canceled",'rescheduled'],
    "arrived": ["Pending", "failed", "canceled", "delivered","rescheduled"],
    "delivered": ["awaiting_confirmation", "canceled", "in_session","rescheduled"],
    "in_session": ["completed"],

    "canceled": [],
    "failed": [],
}
