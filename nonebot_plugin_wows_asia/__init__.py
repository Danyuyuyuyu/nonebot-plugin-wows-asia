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

# nonebot-plugin-aigf-master 把 metadata.description 原样写进每次对话的提示词（“- wows - 说明”），
# 所以这里写给 LLM 看：选哪个指令、参数怎么写、结果怎么理解。每个例子都由测试交给解析器检查。
AI_GUIDE = """窝窝/WoWS 亚服战绩查询。用户明确要查战绩时才调用，参数空格分隔、顺序随意；一个请求只调用一次。
  选指令：总战绩/生涯→wows [谁]；近况/最近战绩→wows 最近 [谁]；某艘船整体打得怎样→wows 单船 船名 [谁]（船名放第一个，看生涯数据）；某段时间/打了哪些场（可限定船）→wows 场次 [谁] [筛选]（列出全部，默认近7天）；只要其中一把的细节→wows 单场 [谁] [筛选] [第N把]（默认最新一把，第N把=从最新往前数）；拿不准时用 场次。
  谁：查提问者本人时不写（传其 user_id，插件按绑定查找，不要自己填昵称）；@群友；玩家完整昵称；id 账号ID。不要猜测或编造昵称。
  筛选：今天 昨天 前天 近N天 本周 10-15 10-12~10-15｜上午 下午 晚上 凌晨 今天下午 14点后 14-18点｜船=船名（错字、同音字会自动纠正）｜随机 排位 单野 组队 双排 三排｜胜 负｜按伤害/击沉/经验/侦察/潜在（从高到低），伤害最低、击沉最少等（从低到高），最好/最差（按经验）｜前N。
  例：查查我最近的战绩→wows 最近；我昨天打得怎么样→wows 场次 昨天；看看张三今天下午打的伊吹→wows 场次 张三 今天下午 船=伊吹；张三伤害最高的一把→wows 单场 张三 按伤害；近3天最差的5把→wows 场次 近3天 最差5把；张三总战绩→wows 张三；张三的大和打得怎么样→wows 单船 大和 张三；绑定我的号 ABC→wows 绑定 ABC。
  看结果：卡片会直接发到群里，简短点评即可，不用逐项复述；“按时间第2/共2场”指发生顺序。最近战绩显示还没有数据时卡片已附生涯概要，不要再自动查总战绩；提示未绑定时请用户发“wows 绑定 昵称”（只有用户给出昵称并要求绑定才代为绑定）；提示“是不是想查”时可换成建议的船名重查一次；只能查到开始记录之后的场次。"""

__plugin_meta__ = PluginMetadata(
    name="WoWS 亚服战绩",
    description=AI_GUIDE,
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
                description="查询 WoWS 亚服总战绩、单船战绩、最近战绩、场次列表和单场详情，可按时间、时段、船、模式、胜负筛选和排序",
                params=["谁：不写=自己（需先绑定）/ 玩家昵称 / id 账号ID / @群友",
                        "筛选：今天 下午 近3天 船=大和 排位 胜 按伤害 最差 前5 等，详见 /wows 帮助",
                        "单船：wows 单船 船名 [谁]，船名支持错字、同音字"],
                examples=[
                    Example(exec="wows 最近", description="查询自己绑定账号的最近战绩"),
                    Example(exec="wows 张三", description="查询亚服玩家张三的总战绩"),
                    Example(exec="wows id 2000000001", description="按账号 ID 查询总战绩"),
                    Example(exec="wows 单场 今天 按伤害", description="自己今天伤害最高的一场的详情"),
                    Example(exec="wows 场次 昨天 船=大和", description="自己昨天打的所有大和"),
                    Example(exec="wows 场次 张三 今天下午 船=伊吹", description="张三今天下午打的所有伊吹"),
                    Example(exec="wows 场次 近3天 排位", description="近 3 天的排位场次列表"),
                    Example(exec="wows 场次 近3天 最差5把", description="近 3 天经验最低（打得最差）的 5 场"),
                    Example(exec="wows 单船 大和", description="自己的大和生涯数据（胜率、场均、同级对比）"),
                    Example(exec="wows 战舰 伊吹 张三", description="张三的伊吹生涯数据"),
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
