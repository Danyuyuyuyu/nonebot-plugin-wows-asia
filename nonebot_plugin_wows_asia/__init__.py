from nonebot import get_driver, get_plugin_config, logger, on_command, require
from nonebot.adapters import Bot, Event, Message
from nonebot.params import CommandArg
from nonebot.plugin import PluginMetadata, inherit_supported_adapters

from zhenxun.configs.utils import Command, Example, PluginExtraData

require("nonebot_plugin_alconna")
require("nonebot_plugin_apscheduler")
require("nonebot_plugin_localstore")

import nonebot_plugin_localstore as localstore  # noqa: E402
from nonebot_plugin_alconna.uniseg import UniMessage  # noqa: E402
from nonebot_plugin_apscheduler import scheduler  # noqa: E402

from .api import WowsApi  # noqa: E402
from .app import WowsApp  # noqa: E402
from .commands import HELP  # noqa: E402
from .config import Config  # noqa: E402
from .renderer import CardRenderer  # noqa: E402
from .storage import Storage  # noqa: E402
from .tracker import Tracker  # noqa: E402

__plugin_meta__ = PluginMetadata(
    name="WoWS 亚服战绩",
    description="查询 WoWS 亚服战绩：总战绩卡、最近战绩卡（含逐场记录）、账号绑定",
    usage=HELP,
    type="application",
    homepage="https://github.com/Danyuyuyuyu/nonebot-plugin-wows-asia",
    config=Config,
    supported_adapters=inherit_supported_adapters("nonebot_plugin_alconna"),
    extra=PluginExtraData(
        author="Danyuyuyuyu",
        version="1.0.0",
        commands=[
            Command(
                command="wows",
                description=(
                    "查询 WoWS 亚服总战绩或最近战绩；AI 调用时把查询参数放入 parts，"
                    "不要把 /wows 前缀放进 command。"
                    "如果当前调用身份没有绑定账号，或者插件返回帮助信息/未绑定提示，"
                    "不要重复调用 wows，应先引导用户绑定 WoWS 亚服账号。"
                    "只有用户明确提供昵称或账号 ID 并要求绑定时，才调用绑定命令，"
                    "不能猜测或编造玩家昵称。"
                ),
                params=[
                    "未绑定处理：如果查询自己的战绩时发现没有绑定，回复用户："
                    "请先发送「wows 绑定 你的亚服昵称」，或发送「wows 绑定 id 账号ID」；"
                    "绑定成功后再说「查我的 WoWS 战绩」或「查我最近的战绩」。"
                    "没有昵称或账号 ID 时，不要自动调用绑定。",
                ],
                examples=[
                    Example(exec="wows 最近", description="查询当前调用身份绑定账号的最近战绩"),
                    Example(exec="wows 张三", description="查询亚服玩家张三的总战绩"),
                    Example(exec="wows id 2000000001", description="按账号 ID 查询总战绩"),
                ],
            )
        ],
    ).to_dict(),
)

config = get_plugin_config(Config)
api = WowsApi(config.wows_application_id.get_secret_value(), timeout=config.wows_timeout_seconds)
storage = Storage(localstore.get_plugin_data_file("wows_asia.sqlite3"))
tracker = Tracker(api, storage, track_days=config.wows_track_days, max_tracked=config.wows_max_tracked,
                  record_days=config.wows_record_days)
renderer = CardRenderer(config.wows_browser_path, config.wows_render_scale) \
    if config.wows_render_mode == "image" else None
app = WowsApp(api, storage, renderer, tracker=tracker, cache_seconds=config.wows_cache_seconds,
              min_battles=config.wows_min_battles, poll_minutes=config.wows_poll_minutes, logger=logger)

wows = on_command("wows", aliases={"窝窝战绩"}, priority=config.wows_command_priority, block=True)


def user_key(bot: Bot, event: Event) -> str | None:
    try:
        return f"{bot.adapter.get_name()}:{event.get_user_id()}"
    except Exception:
        return None


@wows.handle()
async def handle_wows(bot: Bot, event: Event, args: Message = CommandArg()):
    reply = await app.handle(user_key(bot, event), args.extract_plain_text())
    if isinstance(reply, bytes):
        await UniMessage.image(raw=reply, mimetype="image/png").send()
        await wows.finish()
    await wows.finish(reply)


async def poll_job() -> None:
    try:
        count = await tracker.poll_all()
        if count:
            logger.debug(f"WoWS snapshot poll recorded {count} new battle rows")
    except Exception as exc:
        logger.warning(f"WoWS snapshot poll failed: {type(exc).__name__}")


if api.configured:
    scheduler.add_job(poll_job, "interval", minutes=config.wows_poll_minutes, id="wows_asia_snapshot_poll",
                      max_instances=1, coalesce=True, misfire_grace_time=120, replace_existing=True)

driver = get_driver()


@driver.on_shutdown
async def _close() -> None:
    if renderer is not None:
        await renderer.close()
    await api.close()
    storage.close()
