from decimal import Decimal

from rest_framework import serializers

from api.bookings.models import Payment, Session          # 1. add Session


class SelectPaymentMethodSerializer(serializers.Serializer):
    """Input only. Note: no amount field. The server always reads the price itself."""

    shipment_id = serializers.IntegerField(min_value=1)
    method = serializers.ChoiceField(choices=Payment.Method.choices)


class PaymentSerializer(serializers.ModelSerializer):
    shipment_id = serializers.IntegerField(read_only=True)
    amount = serializers.SerializerMethodField()
    platform_fee = serializers.SerializerMethodField()
    checkout = serializers.SerializerMethodField()
    session_status = serializers.SerializerMethodField()   # 2. add the field

    class Meta:
        model = Payment
        fields = [
            "payment_id",
            "shipment_id",
            "method",
            "status",
            "amount",
            "platform_fee",
            "created_at",
            "paid_at",
            "failure_reason",
            "checkout",
            "session_status",                               # 3. add it to the list
        ]
        read_only_fields = fields

    def get_amount(self, obj):
        return str(Decimal(obj.amount_cents) / 100)

    def get_platform_fee(self, obj):
        return str(Decimal(obj.platform_fee_cents) / 100)

    def get_checkout(self, obj):
        """Only populated once the card transaction has been initiated."""
        if obj.method != Payment.Method.CARD or not obj.vendor_access_code:
            return None
        return {
            "access_code": obj.vendor_access_code,
            "authorization_url": obj.vendor_checkout_url,
            "reference": obj.vendor_reference,
        }

    def get_session_status(self, obj):                      # 4. add this method
        return (
            Session.objects.filter(shipment_id=obj.shipment_id)
            .values_list("session_status", flat=True)
            .first()
        )


class ProviderPaymentSerializer(PaymentSerializer):
    """Providers see status and amounts, never the Paystack checkout details."""
 
    net_amount = serializers.SerializerMethodField()
    commission_percent = serializers.SerializerMethodField()
 
    class Meta(PaymentSerializer.Meta):
        fields = PaymentSerializer.Meta.fields + ["net_amount", "commission_percent"]
        read_only_fields = fields
 
    def get_checkout(self, obj):
        return None
 
    def get_net_amount(self, obj):
        return str(Decimal(obj.amount_cents - obj.platform_fee_cents) / 100)
 
    def get_commission_percent(self, obj):
        if not obj.amount_cents:
            return "0"
        pct = Decimal(obj.platform_fee_cents) * 100 / Decimal(obj.amount_cents)
        return str(pct.quantize(Decimal("0.01")))