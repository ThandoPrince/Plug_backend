ORDER_STATUS = [
    ('pending', 'Pending'),
    ('confirmed', 'Confirmed'),
    ('in_progress', 'In Progress'),
    ('resheduled','Rescheduled'),
    ('onhold', 'On Hold'),
    ('declined', 'Declined'),
    ('expired', 'Expired'),
    ('completed', 'Completed'),
    ('sheduled', 'Scheduled'),
    ('canceled', 'Canceled'),
    ('failed', 'Failed'),
    ('awaiting_payment', 'Awaiting Payment'),
    ('awaiting_confirmation', 'Awaiting Confirmation'),
    ('awaiting_review', 'Awaiting Review'),
    ('awaiting_rating', 'Awaiting Rating'),
    ('awaiting_service', 'Awaiting Service'),
    ('in_progress', 'In Progress'),
    ('awaiting_approval', 'Awaiting Approval'),
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
    ('completed', 'Completed'),
    ('returned', 'Returned'),
]

SESSION_STATUS = [
    ('on_break', 'On Break'),
    ('in_progress', 'In Progress'),
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