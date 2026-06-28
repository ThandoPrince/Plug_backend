class EventBus:
    _handlers = {}

    @classmethod
    def register(cls, event_name, handler):
        cls._handlers.setdefault(event_name, []).append(handler)

    @classmethod
    def emit(cls, event):
        handlers = cls._handlers.get(event.name, [])

        for handler in handlers:
            handler(event.payload)