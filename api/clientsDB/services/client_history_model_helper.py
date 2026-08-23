from api.clientsDB.models.models import ClientAddressHistory


def create_client_address_history(
    *,
    client_address,
    action,
    performed_by=None,
    reason=None,
    metadata=None,
):
    return ClientAddressHistory.objects.create(
        client_address=client_address,
        performed_by=performed_by,
        action=action,
        reason=reason,
        metadata=metadata,
    )