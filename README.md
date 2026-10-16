# nonebot-plugin-wows-asia

NoneBot2 战舰世界（WoWS）**亚服**战绩查询插件：图片战绩卡、最近战绩（逐场记录）、账号绑定。

- 只使用 WG 公开 API（`https://api.worldofwarships.asia/wows/`），只需要 `application_id`，不需要玩家密码或 OAuth。
- 卡片为本地 HTML 模板 + 无头 Chromium 截图，不加载任何外部网络资源；渲染失败时自动降级为文字。
- 通过 [nonebot-plugin-alconna](https://github.com/nonebot/plugin-alconna) 发送图片，支持其覆盖的适配器（OneBot V11/V12、QQ、Telegram、Kook 等）。

## 指令

| 指令 | 说明 |
| --- | --- |
| `/wows 玩家昵称` | 总战绩卡（随机战斗生涯） |
| `/wows id 账号ID` | 按账号 ID 查询（纯数字昵称仍按昵称处理） |
| `/wows 绑定 昵称`（或 `绑定 id 账号ID`） | 绑定自己的账号，并立即开始记录快照 |
| `/wows` / `/wows 我` | 查自己的总战绩（需先绑定） |
| `/wows 最近 [昵称]` | 最近 7 天汇总 + 每日战况 + 最近两天逐场列表 |
| `/wows 解绑` | 取消绑定 |
| `/wows 帮助` | 帮助 |

别名 `/窝窝战绩`；指令前缀以 NoneBot 的 `COMMAND_START` 为准。昵称精确匹配失败时最多返回 5 个候选，不会擅自使用第一个候选。

## 卡片内容

**总战绩卡**：随机胜率环图（胜/负/平）、场数、场均伤害/击沉/经验、存活率、主炮命中率；舰种表现（使用占比 + 胜率条，0–100% 刻度）；随机 vs 排位对比；单野/双排/三排胜率；单场最高伤害/击沉/经验/侦察及对应战舰。

**最近战绩卡**：近 7 天汇总（对比生涯）；按天的胜负堆叠柱；最近两天的逐场列表（时间、胜负、战舰、舰种/等级/模式、伤害及与本船生涯场均的对比、击沉、经验、存活）。

**状态卡**：隐藏战绩、刚开始记录 / 近 7 天无战斗、追踪名额已满、随机场次少于 `WOWS_MIN_BATTLES`（默认 50）的新号。

## 最近战绩的原理与限制

WG 公开 API **没有逐场战斗记录接口**。插件定时保存每艘船的累计数据快照，两次快照之间的差值就是这段时间打的战斗：

- 只能记录**开始记录之后**的战斗。绑定账号或第一次查询 `/wows 最近 某人` 时开始记录，之前的场次查不到。
- 定时任务每 `WOWS_POLL_MINUTES` 分钟先批量检查 `last_battle_time`，有变化才拉取战舰数据，请求量很小。
- 同一艘船在两次快照之间打了多场时只能合并成一行显示（灰底，标注“N 场合计”，数值为场均）。显示的时间是快照时间，可能比实际结束晚几分钟。
- 记录随机（pvp）和单人排位（rank_solo）；行动、剧情等模式不计入。
- 绑定账号会一直记录；未绑定账号在 `WOWS_TRACK_DAYS` 天内没人查询就停止记录；逐场记录保留 `WOWS_RECORD_DAYS` 天。

## 安装

在**运行机器人的同一个 Python 环境**中：

```bash
# 从 GitHub 安装
pip install "git+https://github.com/Danyuyuyuyu/nonebot-plugin-wows-asia.git"
# 或安装发布的 wheel
pip install nonebot_plugin_wows_asia-0.2.0-py3-none-any.whl

# 安装截图用的 Chromium（Linux 服务器可加 --with-deps 自动装系统依赖）
playwright install chromium
```

然后在 `pyproject.toml` 的 `[tool.nonebot]` 中加入插件：

```toml
plugins = ["nonebot_plugin_wows_asia"]
```

**中文字体**：服务器需要有中文字体，否则卡片中文会显示成方块。Debian/Ubuntu：`apt install fonts-noto-cjk`；CentOS/RHEL：`yum install google-noto-sans-cjk-ttc-fonts`。

不想装浏览器时设置 `WOWS_RENDER_MODE=text`，所有功能以文字回复。

## 配置（.env）

先在 [WG 开发者中心](https://developers.wargaming.net/) 用亚服账号创建应用获取 `application_id`（选 Server 类型）。

| 配置项 | 默认 | 说明 |
| --- | --- | --- |
| `WOWS_APPLICATION_ID` | 空 | **必填**。未配置时插件可加载，但查询会提示管理员配置，定时任务不启动 |
| `WOWS_RENDER_MODE` | `image` | `image` 图片卡片 / `text` 纯文字 |
| `WOWS_RENDER_SCALE` | `1.5` | 截图倍率（1–3），越大越清晰、图片越大 |
| `WOWS_BROWSER_PATH` | 空 | 使用系统已有 Chromium/Chrome 的可执行文件路径 |
| `WOWS_POLL_MINUTES` | `10` | 快照检查间隔（3–720 分钟） |
| `WOWS_TRACK_DAYS` | `14` | 未绑定账号多少天无人查询后停止记录 |
| `WOWS_MAX_TRACKED` | `200` | 最多同时记录的账号数（绑定账号不受限） |
| `WOWS_RECORD_DAYS` | `30` | 逐场记录保留天数（≥15） |
| `WOWS_MIN_BATTLES` | `50` | 随机场次低于此值显示新号状态卡 |
| `WOWS_TIMEOUT_SECONDS` | `15` | 单次 API 请求超时 |
| `WOWS_CACHE_SECONDS` | `60` | 账号数据缓存时间 |
| `WOWS_COMMAND_PRIORITY` | `10` | 事件响应器优先级 |

示例见 [.env.example](.env.example)。数据（绑定、快照、记录）保存在 nonebot-plugin-localstore 的插件数据目录下 `wows_asia.sqlite3`。

## 说明

- 统计以随机战斗 `statistics.pvp` 为主；排位为 `rank_solo`；组队为 `pvp_solo/pvp_div2/pvp_div3`。WG 如不支持某个 `extra` 字段，插件会自动去掉重试，缺失数据显示为 `—`。
- 不计算 PR 评分（需要第三方期望值数据）。时间统一按 UTC+8 显示。
- 错误提示不会包含 application_id 或请求 URL。
- 卡片配色借鉴《别当欧尼酱了！》绪山真寻的樱粉 + 薰衣草紫，不含任何官方立绘或素材。

## 开发

```bash
pip install -e ".[test]"
pytest
```

测试使用模拟的 WG API，覆盖指令解析、API 参数与错误处理、快照差值、定时任务、绑定流程、HTML 转义和真实 Chromium 渲染（检测到 `chromium` 时运行，可用 `WOWS_TEST_CHROMIUM` 指定路径）。

## 许可

MIT
