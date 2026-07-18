def handle_provider_location_updated(payload):
    provider = payload["provider"]

    notify_provider_location(
        provider_id=provider.id,
        payload={
            "provider_id": provider.id,
            "latitude": payload["latitude"],
            "longitude": payload["longitude"],
            "timestamp": payload["timestamp"],
        },
    )