class SessionHandler:

    async def route_update(self, event):
        await self.send_json({
            "type": "route_update",
            "data": event["data"],
        })