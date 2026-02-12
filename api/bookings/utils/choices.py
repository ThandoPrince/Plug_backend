ORDER_STATUS = [
    ('pending', 'Pending'),
    ('accepted', 'Accepted'),
    ('in_delivery', 'In Delivery'),
    ('resheduled','Rescheduled'),
    ('onhold', 'On Hold'),
    ('declined', 'Declined'),
    ('awaiting_confirmation', 'Awaiting Confirmation'),
    ('expired', 'Expired'),
    ('completed', 'Completed'),
    ('canceled', 'Canceled'),
    ('failed', 'Failed'),
    ('awaiting_payment', 'Awaiting Payment'),
    ('in_session', 'In Session'),
    ('awaiting_rating', 'Awaiting Rating'),

]

SHIPMENT_STATUS = [
    ('pending', 'Pending'),
    ('shipped', 'Shipped'),
    ('scheduled', 'Scheduled'),
    ('delivered', 'Delivered'),
    ('failed', 'Failed'),
    ('resheduled', 'Rescheduled'),
    ('canceled', 'Canceled'),
    ('in_transit', 'In Transit'),
    ('out_for_delivery', 'Out for Delivery'),
    ('returned_to_sender', 'Returned back home'),
    ('delayed', 'Delayed'),
    ('awaiting_pickup', 'Awaiting Pickup'),
    ('arrived', 'Arrived'),
    ('in_session', 'In Session'),
    ('completed', 'Completed'),
    ('returned', 'Returned'),
]

SESSION_STATUS = [
    ('on_break', 'On Break'),
    ('in_session', 'In Session'),
    ('completed', 'Completed'),
    ('canceled', 'Canceled'),
]

PAYMENT_STATUS = [
    ('pending', 'Pending'),
    ('paid', 'Paid'),
    ('failed', 'Failed'),
    ('refunded', 'Refunded'),
    ('partially_refunded', 'Partially Refunded'),
    ('canceled', 'Canceled'),
    ('partially_paid', 'Partially Paid'),
    ('overpaid', 'Overpaid'),
    ('underpaid', 'Underpaid'),
]