from typing import TYPE_CHECKING, Any, Union, Optional

from nonebot.typing import overrides
from nonebot.message import handle_event

from nonebot.adapters import Bot as BaseBot

from .utils import log
from .config import BotInfo
from .api import User, ApiClient
from .message import Message, MessageSegment
from .event import Event, ReadyEvent, MessageEvent, DirectMessageCreateEvent

if TYPE_CHECKING:
    from .adapter import Adapter


async def _check_reply(bot: "Bot", event: MessageEvent) -> None:
    """检查消息中存在的回复，赋值 `event.reply`, `event.to_me`。

    参数:
        bot: Bot 对象
        event: MessageEvent 对象
    """
    if event.message_reference is None:
        return
    try:
        event.reply = await bot.get_message_of_id(
            channel_id=event.channel_id, message_id=event.message_reference.message_id  # type: ignore
        )
        if event.reply.message.author.id == bot.self_info.id:  # type: ignore
            event.to_me = True
    except Exception as e:
        log("WARNING", f"Error when getting message reply info: {repr(e)}", e)


def _check_at_me(bot: "Bot", event: MessageEvent):
    if event.mentions is not None and bot.self_info.id in [
        user.id for user in event.mentions
    ]:
        event.to_me = True

    def _is_at_me_seg(segment: MessageSegment) -> bool:
        return segment.type == "mention_user" and segment.data.get("user_id") == str(
            bot.self_info.id
        )

    message = event.get_message()

    # ensure message is not empty
    if not message:
        message.append(MessageSegment.text(""))

    deleted = False
    if _is_at_me_seg(message[0]):
        message.pop(0)
        deleted = True
        if message and message[0].type == "text":
            message[0].data["text"] = message[0].data["text"].lstrip("\xa0").lstrip()
            if not message[0].data["text"]:
                del message[0]

    if not deleted:
        # check the last segment
        i = -1
        last_msg_seg = message[i]
        if (
            last_msg_seg.type == "text"
            and not last_msg_seg.data["text"].strip()
            and len(message) >= 2
        ):
            i -= 1
            last_msg_seg = message[i]

        if _is_at_me_seg(last_msg_seg):
            deleted = True
            del message[i:]

    if not message:
        message.append(MessageSegment.text(""))


class Bot(BaseBot, ApiClient):
    @overrides(BaseBot)
    def __init__(self, adapter: "Adapter", self_id: str, bot_info: BotInfo):
        super().__init__(adapter, self_id)
        self.bot_info: BotInfo = bot_info
        self._session_id: Optional[str] = None
        self._self_info: Optional[User] = None
        self._sequence: Optional[int] = None

    @property
    def ready(self) -> bool:
        return self._session_id is not None

    @property
    def session_id(self) -> str:
        if self._session_id is None:
            raise RuntimeError(f"Bot {self.self_id} is not connected!")
        return self._session_id

    @session_id.setter
    def session_id(self, session_id: str) -> None:
        self._session_id = session_id

    @property
    def self_info(self) -> User:
        if self._self_info is None:
            raise RuntimeError(f"Bot {self.bot_info} is not connected!")
        return self._self_info

    @self_info.setter
    def self_info(self, self_info: User) -> None:
        self._self_info = self_info

    @property
    def has_sequence(self) -> bool:
        return self._sequence is not None

    @property
    def sequence(self) -> int:
        if self._sequence is None:
            raise RuntimeError(f"Bot {self.bot_info.id} is not connected!")
        return self._sequence

    @sequence.setter
    def sequence(self, sequence: int) -> None:
        self._sequence = sequence

    def clear(self) -> None:
        self._session_id = None
        self._sequence = None

    async def handle_event(self, event: Event) -> None:
        if isinstance(event, ReadyEvent):
            self.session_id = event.session_id
            self.self_info = event.user
        elif isinstance(event, MessageEvent):
            await _check_reply(self, event)
            _check_at_me(self, event)
        await handle_event(self, event)

    @overrides(BaseBot)
    async def send(
        self,
        event: Event,
        message: Union[str, Message, MessageSegment],
        **kwargs,
    ) -> Any:
        if not isinstance(event, MessageEvent) or not event.channel_id or not event.id:
            raise RuntimeError("Event cannot be replied to!")
        message = MessageSegment.text(message) if isinstance(message, str) else message
        message = message if isinstance(message, Message) else Message(message)

        content = message.extract_content() or None
        if embed := (message["embed"] or None):
            embed = embed[-1].data["embed"]
        if ark := (message["ark"] or None):
            ark = ark[-1].data["ark"]
        if image := (message["attachment"] or None):
            image = image[-1].data["url"]
        if file_image := (message["file_image"] or None):
            file_image = file_image[-1].data["content"]
        if markdown := (message["markdown"] or None):
            markdown = markdown[-1].data["markdown"]
        if reference := (message["reference"] or None):
            reference = reference[-1].data["reference"]

        # 私信需要使用 post_dms_messages
        # https://bot.q.qq.com/wiki/develop/api/openapi/dms/post_dms_messages.html#%E5%8F%91%E9%80%81%E7%A7%81%E4%BF%A1
        if isinstance(event, DirectMessageCreateEvent):
            return await self.post_dms_messages(
                guild_id=event.guild_id,
                msg_id=event.id,
                content=content,
                embed=embed,  # type: ignore
                ark=ark,  # type: ignore
                image=image,  # type: ignore
                file_image=file_image,  # type: ignore
                markdown=markdown,  # type: ignore
                message_reference=reference,  # type: ignore
            )

        return await self.post_messages(
            channel_id=event.channel_id,
            msg_id=event.id,
            content=content,
            embed=embed,  # type: ignore
            ark=ark,  # type: ignore
            image=image,  # type: ignore
            file_image=file_image,  # type: ignore
            markdown=markdown,  # type: ignore
            message_reference=reference,  # type: ignore
        )
