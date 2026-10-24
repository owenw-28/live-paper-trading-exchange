"""WebSocket endpoint for a logged-in user's private updates: their orders as they settle."""

from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.trading.notifications import user_group


class UserConsumer(AsyncJsonWebsocketConsumer):
    group: str | None = None

    async def connect(self) -> None:
        user = self.scope.get("user")  # set by AuthMiddlewareStack from the session cookie
        if user is None or not user.is_authenticated:
            await self.close()  # before accept(): the handshake itself is refused
            return
        self.group = user_group(user.id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code: int) -> None:
        if self.group is not None:
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def user_order(self, message: dict) -> None:
        await self.send_json({"type": "order", "order": message["order"]})
