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
    # nonebot-plugin-aigf-master 把这一行原样写进 LLM 的“可用功能”清单，所以写成调用说明
    description=(
        "窝窝(WoWS)亚服战绩。参数空格分隔、顺序随意。wows [谁] 总战绩；wows 最近 [谁] 近7天汇总；"
        "wows 场次 [谁] [筛选] 列出场次；wows 单场 [谁] [筛选|序号] 单场详情（取排序后第1场，默认最近一场）。"
        "谁=我(默认,需传 user_id)/玩家昵称/id 账号ID/@群友。"
        "筛选：今天|昨天|前天|近N天|MM-DD|MM-DD~MM-DD；船=船名；随机|排位|单野|组队|双排|三排；胜|负；"
        "按伤害|按击沉|按经验|按侦察|按潜在（从高到低），伤害最低|击沉最少|经验最低 等（从低到高）；"
        "最好|最差（按经验高低）；前N。"
        "例：今天伤害最高的一把→wows 单场 今天 按伤害；昨天打的大和→wows 场次 昨天 船=大和；"
        "近3天打得最差的5把→wows 场次 近3天 最差5把。"
        "只能查到绑定/首次查询之后记录的场次；未绑定时先让用户发 wows 绑定 昵称"
    ),
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
                    "用户说最近/近期时必须保留“最近”参数，用户说总战绩/生涯时不要添加“最近”；"
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
                    Example(exec="wows 单场 今天 按伤害", description="当前调用身份今天伤害最高的一场的详情"),
                    Example(exec="wows 场次 昨天 船=大和", description="当前调用身份昨天打的所有大和"),
                    Example(exec="wows 场次 近3天 排位", description="近 3 天的排位场次列表"),
                    Example(exec="wows 场次 近3天 最差5把", description="近 3 天经验最低（打得最差）的 5 场"),
                ],
            )
        ],
    ).to_dict(),
)

config = get_plugin_config(Config)
api = WowsApi(config.wows_application_id.get_secret_value(), timeout=config.wows_timeout_seconds)
storage = Storage(localstore.get_plugin_data_file("wows_asia.sqlite3"))
tracker = Tracker(api, storage, track_days=config.wows_track_days, max_tracked=config.wows_max_tracked,
                  record_days=config.wows_record_days, poll_minutes=config.wows_poll_minutes,
                  fast_minutes=config.wows_fast_poll_minutes)
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


def mention_keys(bot: Bot, args: Message) -> list[str]:
    """@-segments in the arguments -> user keys, so "/wows 最近 @某人" reads that user's binding."""
    keys = []
    try:
        for seg in args:
            qq = seg.data.get("qq") if seg.type == "at" and isinstance(seg.data, dict) else None
            if qq and str(qq) != "all":
                keys.append(f"{bot.adapter.get_name()}:{qq}")
    except Exception:
        return []
    return keys


@wows.handle()
async def handle_wows(bot: Bot, event: Event, args: Message = CommandArg()):
    # nonebot-plugin-aigf-master marks the events it synthesises; add a text line so the LLM gets exact numbers
    ai = bool(getattr(event, "aigf_synthetic", False)) and config.wows_ai_caption
    reply = await app.handle(user_key(bot, event), args.extract_plain_text(), mentions=mention_keys(bot, args), ai=ai)
    if isinstance(reply, tuple):
        image, caption = reply
        await (UniMessage.image(raw=image, mimetype="image/png") + UniMessage.text("\n" + caption)).send()
        await wows.finish()
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
    scheduler.add_job(poll_job, "interval", minutes=tracker.tick_minutes, id="wows_asia_snapshot_poll",
                      max_instances=1, coalesce=True, misfire_grace_time=120, replace_existing=True)

driver = get_driver()


@driver.on_shutdown
async def _close() -> None:
    if renderer is not None:
        await renderer.close()
    await api.close()
    storage.close()
