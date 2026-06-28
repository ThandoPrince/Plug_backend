class Event:
    name: str
    payload: dict

    def __init__(self, payload=None):
        self.payload = payload or {}