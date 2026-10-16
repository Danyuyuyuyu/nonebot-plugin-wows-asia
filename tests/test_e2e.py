"""End-to-end through NoneBot + OneBot V11 (runs when nonebug and the OneBot adapter are installed)."""
import pytest

nonebug = pytest.importorskip("nonebug")
v11 = pytest.importorskip("nonebot.adapters.onebot.v11")

from nonebot_plugin_wows_asia.app import WowsApp  # noqa: E402
from nonebot_plugin_wows_asia.storage import Storage  # noqa: E402
from nonebot_plugin_wows_asia.tracker import Tracker  # noqa: E402

from .fakes import Clock, FakeWG, make_api  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\nfake"


class StaticRenderer:
    async def render(self, html):
        return PNG


def event(text: str) -> "v11.GroupMessageEvent":
    return v11.GroupMessageEvent(
        time=1792130400, self_id=1, post_type="message", sub_type="normal", user_id=10001,
        message_type="group", message_id=1, message=v11.Message(text), original_message=v11.Message(text),
        raw_message=text, font=0, sender=v11.event.Sender(user_id=10001, nickname="u"), group_id=123,
        to_me=False)


@pytest.fixture
def plugin(monkeypatch):
    import nonebot
    import nonebot_plugin_wows_asia as m
    from nonebot.adapters.onebot.v11 import Adapter
    try:
        nonebot.get_adapter(Adapter)
    except ValueError:
        nonebot.get_driver().register_adapter(Adapter)
    fake, clock = FakeWG(), Clock()
    api, storage = make_api(fake), Storage(":memory:")
    tracker = Tracker(api, storage, clock=clock)
    monkeypatch.setattr(m, "app", WowsApp(api, storage, StaticRenderer(), tracker=tracker, cache_seconds=0,
                                          clock=clock))
    return m


async def test_group_image_and_text_reply(app, plugin):
    from nonebot.adapters.onebot.v11 import Adapter, Bot
    async with app.test_matcher(plugin.wows) as ctx:
        adapter = ctx.create_adapter(base=Adapter)
        bot = ctx.create_bot(base=Bot, adapter=adapter, self_id="1")
        ev = event("/wows Example_Player")
        ctx.receive_event(bot, ev)
        from nonebot_plugin_alconna.uniseg import UniMessage
        # Under nonebug, alconna exports through its test exporter; compare against the same export.
        expected = await UniMessage.image(raw=PNG, mimetype="image/png").export(bot)
        ctx.should_call_send(ev, expected, result={"message_id": 2})
        ctx.should_finished(plugin.wows)
    async with app.test_matcher(plugin.wows) as ctx:
        adapter = ctx.create_adapter(base=Adapter)
        bot = ctx.create_bot(base=Bot, adapter=adapter, self_id="1")
        ev = event("/wows 解绑")
        ctx.receive_event(bot, ev)
        ctx.should_call_send(ev, "你还没有绑定账号。", result=None)
        ctx.should_finished(plugin.wows)
