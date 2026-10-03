# film-radar 设计文档

- 日期：2026-10-03
- 状态：待用户审阅
- 仓库：`~/Projects/film-radar` → GitHub `AKASHA-R/film-radar`（公开）
- 页面：`https://akasha-r.github.io/film-radar/`

## 1. 目的与成功标准

**要解决的问题。** 多伦多院线的官方信息写得不清楚：类型标签很粗，简介是宣发文案。结果是好片子还不知道在讲什么就下映了，事后看影评博主的解析才发现错过。

**做什么。** 每两周抓一次 Cineplex 在大多伦多地区（GTA）的在映与即将上映片单，由 Claude 联网查证后，按个人口味挑出值得看的，输出一个中文网页，并通过 GitHub Issue 推送通知。

**成功标准。**

1. 两周打开一次页面，对口味的片不漏，并且是在它下映之前知道。
2. 每张推荐卡片能回答三个问题：这片子讲什么、为什么对我胃口、口碑怎么样。
3. 每一部进入候选的片都能在页面上查到去向（推荐、可以看、跳过、未能评估四者之一），没有被悄悄丢掉的。
4. 任何失败要么让运行明确报错，要么在页面上看得见。不产出"看起来正常其实是空的"页面。

## 2. 已确认的决策

| 项 | 决定 | 来源 |
|---|---|---|
| 地区 | 大多伦多地区 | 用户选定 |
| 影院范围 | 第一版只抓 Cineplex；来源层保持可替换 | 用户选定 |
| 通知方式 | 每期开一个 GitHub Issue，靠 GitHub 自带的邮件与 App 推送 | 用户选定 |
| 判断方案 | 两段式：程序过滤 → Claude 粗筛 → 逐片联网精评 | 用户选定 |
| 频率 | 两周一次，周四早上（多伦多时间） | 用户指定，设计确认 |
| 仓库可见性 | 公开（免费版 GitHub Pages 要求公开仓库） | 设计确认 |
| 口味类别 | 六类：科幻、惊悚、政治历史、中国电影、恐怖、日本电影（含经典动画电影重映） | 前五类为用户原定；第六类为用户审阅 spec 时追加 |
| 口味之外的片 | 六类加权而非排他；六类之外每期最多 2 个位置 | 设计确认 |
| 活动场的处理 | 只过滤非电影类活动（歌剧、演唱会、舞台剧、电视节目）；以活动形式放映的电影保留为候选 | 用户审阅时指出，实测数据确认（见附录 A） |
| 运行位置 | 全部在 GitHub Actions | 设计确认 |
| 模型 | `claude-opus-5-5` | claude-api 技能默认 |

## 3. 范围

**做：**

- Cineplex 片单、GTA 影院排片、单片详情的抓取
- 候选过滤、粗筛、逐片联网精评
- 静态页面渲染（当期页 + 往期存档）
- GitHub Pages 部署与 Issue 通知
- 手动触发重跑

**不做（第一版）：**

- Cineplex 以外的影院（TIFF Lightbox、独立影院、其他连锁）
- 具体场次时间表与购票（卡片只给 Cineplex 详情页链接）
- 已看 / 想看标记、评分反馈、个性化学习
- 本机定时任务与自动弹出浏览器
- 邮件直发（依赖 GitHub 自带通知）
- 跨期缓存精评结果（每期对入围片重新精评，见第 9 节）

## 4. 架构与数据流

```
cineplex      运行时取密钥；片单、GTA 影院、未来 7 天排片、单片详情
   ↓
candidates    程序过滤与同片多版本合并                    → 约 50–90 部
   ↓
triage        Claude 一次调用，只看元数据，逐片给去留      → 入围最多 15 部
   ↓
review        Claude 逐片调用 + 联网搜索，产出结构化卡片
   ↓
assemble      程序规则：名额上限、降档、"抓紧"标记、新旧标记、总数核对
   ↓
render        纯程序渲染静态 HTML
   ↓
publish       提交当期数据 → 部署 Pages → 开 Issue
```

### 模块

每个模块一个文件、一个职责。模块之间只传 JSON 可序列化的数据，除 `cineplex`、`triage`、`review` 外均为纯函数。

| 模块 | 职责 | 输入 | 输出 | 外部依赖 |
|---|---|---|---|---|
| `cineplex.py` | Cineplex 客户端：取密钥、片单、影院、排片、详情 | 配置 | 原始响应（已做结构校验） | 网络 |
| `candidates.py` | 过滤与合并 | 片单、影院、排片、运行日期、配置 | 候选列表 | 无 |
| `triage.py` | 粗筛 | 口味档案、候选列表 | 每部候选一条判定 | Claude API |
| `review.py` | 单片联网精评 | 口味档案、一部候选 | 一张卡片或失败记录 | Claude API + 联网搜索 |
| `assemble.py` | 程序侧规则与总数核对 | 候选、判定、卡片、上一期数据 | 当期数据（edition） | 无 |
| `render.py` | 渲染 HTML | 全部 edition 数据 | `site/` 目录 | 无 |
| `main.py` | 串联、双周门控、用量汇总、退出码 | 环境变量、配置 | 写文件、退出码 | 以上全部 |

### 目录

```
film-radar/
  config/
    settings.toml          半径、窗口、名额、模型等
    taste_profile.md       口味档案（提示词输入）
  src/film_radar/          上表各模块
  data/editions/           每期一份 JSON，提交进仓库，是事实源
  tests/
    fixtures/cineplex/     真实响应裁剪出的测试数据
  site/                    构建产物，不提交
  .github/workflows/
    edition.yml
  docs/superpowers/specs/
```

`data/editions/*.json` 是事实源，HTML 是派生物：每次运行由全部 edition 数据重建整个站点。

### 技术选型

- Python 3.11（本机已有 `python3.11`，Actions 用同一小版本，避免两边行为不一致）
- 依赖：`anthropic`、`requests`、`pytest`。`anthropic` 的具体版本在实施计划里查 PyPI 后钉死
- 配置读取用标准库 `tomllib`
- HTML 用标准库字符串模板生成，不引入模板引擎

### Claude 调用约定

`triage` 与 `review` 共用：

- 走官方 `anthropic` Python SDK，模型 `claude-opus-5-5`。
- 该模型的思考始终开启，不传 `budget_tokens`；`effort` 显式设置（它的默认值是 `medium`，不显式写容易在换模型时悄悄变化）：粗筛 `medium`，精评 `high`。
- 读取响应时只取 `type == "text"` 的内容块。
- 每次调用后先查 `stop_reason`，再读内容。`max_tokens` 与 `refusal` 都按失败处理。
- 启用服务端拒答回退（`fallbacks: "default"`，beta 功能）。回退后仍拒答才算失败。
- API 错误依赖 SDK 自带的重试（429、5xx、连接错误），用尽后才算失败。

## 5. 数据源：Cineplex

Cineplex 没有公开 RSS，也没有官方开放 API。网站前端调用 `apis.cineplex.com`，请求头带一把写在前端脚本里的订阅密钥。本项目用同一条路，只读。

**这是非官方用法**，Cineplex 改版或换密钥就会断。对策见第 13 节。接口结构的实测记录见附录 A。

### 取密钥

1. 抓取 `https://www.cineplex.com/` 首页，找出其引用的 `/_next/static/**.js`。
2. 在脚本里找 `"Ocp-Apim-Subscription-Key":"<32 位十六进制>"`。实测前端里有不止一把密钥（电影接口一把，个性化横幅接口另一把）。
3. 优先取与 `cpx/theatrical/api` 基址出现在同一语句里的那把；取不到时，对找到的每把不同密钥依次试调 `/v2/movies`，用第一把返回 200 的。
4. 密钥只在内存里用，不写入仓库、不写入数据文件、日志里只打前 4 位。

### 抓取步骤

1. `GET /v2/movies?language=en` → 全量片单。用 v2 而不是 v1，因为只有 v2 带 `filmCategories` 字段，第 6 节区分"电影"与"非电影活动"要靠它。
2. `GET /v1/theatres?language=en&latitude=..&longitude=..&range=..` → 全部影院及各自到中心点的距离（`location.distanceToOriginInMeters`）。取距离不超过 `radius_km` 的为 GTA 影院。
3. 对每家 GTA 影院、从运行当天起连续 `showtime_days` 天，`GET /v1/showtimes?language=en&locationId=<id>&date=MM/DD/YYYY` → 该店当日在映影片。
4. 过滤出候选后，对每部候选抓 `https://www.cineplex.com/movie/<filmUrl>`，解析 `__NEXT_DATA__` 里的 `props.pageProps.movieDetails` → 简介、导演、主演。

请求间隔不小于 0.3 秒。按 22 家影院、7 天、约 90 部候选估算，单次运行约 260 个请求，耗时 2 分钟左右。

所有请求带一个固定的浏览器 User-Agent。实测时是带着的，不带是否可行没有验证过。

### 结构校验

每个响应在使用前校验必需字段存在且类型正确。校验失败即抛出带接口名与缺失字段名的异常，由 `main.py` 转成运行失败。

## 6. 候选过滤（`candidates.py`）

输入是全量片单、GTA 影院、排片结果。规则按顺序执行：

1. **去非电影活动**：`isEvent == true` **且** `filmCategories` 与 `non_film_categories` 有交集的条目过滤掉。`non_film_categories` 默认为 `Opera`、`Concert`、`Stage`、`Stage Performance`、`Television Event`、`Sport`。

   **不能只看 `isEvent`。** Cineplex 把以特别放映形式上映的电影也标成活动。实测被标为活动的有：动画重映 `Ninja Scroll 4K`、日语动画新片 `Dive in Wonderland`、恐怖片 `Fresh Meat`、纪录片 `HANGING BY A WIRE`。只看 `isEvent` 会把它们全部丢掉。

   用排除名单而不用准入名单，是因为两者的出错方向不同：排除名单遇到没见过的活动类别时会放行，交给粗筛判断并留下理由；准入名单则会把它悄悄丢掉。

   规则只对活动生效。非活动的片即使带 `Sport` 这类类别（体育题材剧情片）也不受影响。

   被过滤的条目不进候选，但**片名与命中的类别记入当期数据的 `filtered_events`**，并在页面折叠区列出，这样误杀可以被看见。
2. **同片多版本合并**：片名去掉末尾括号后相同、**且上映日期相差不超过 60 天**的条目视为同一部片（实测：`Digger` 与 `Digger (Dubbed in Spanish)` 是不同 id，上映日相差 3 天）。日期条件用来防止把同名的翻拍与旧片重映误并。主条目取片名不带括号的那条；都带括号时取 id 最小的。被合并的条目记为主条目的 `variants`（语言版本），其排片并入主条目。状态、上映日期等字段一律取主条目的。
3. **入选条件**，满足任一即为候选：
   - **GTA 有排片**：该片（含其 variants）在任一 GTA 影院、未来 `showtime_days` 天内有排片。
   - **近期上映**：`isComingSoon == true`，且上映日期晚于运行日期、不超过运行日期后 `coming_soon_days` 天（第 14 天算，第 15 天不算）。

入选条件只决定进不进候选，不决定状态。状态取自 Cineplex 自己的标记，这样已开提前场但尚未正式上映的片不会被误标成在映。

每部候选携带由程序计算的事实字段：

| 字段 | 算法 |
|---|---|
| `title` | 主条目片名去掉末尾括号。语言与字幕另行显示 |
| `versions` | 主条目与全部 variants 各自的语言与字幕，如"英语配音""日语原声 / 英文字幕" |
| `status` | 主条目 `isComingSoon` 为真则 `coming_soon`，否则 `now_playing` |
| `is_event` | 主条目或任一 variant 的 `isEvent` 为真 |
| `gta_theatres` | 未来 `showtime_days` 天内有排片的 GTA 影院名列表，可为空（近期上映但排片未出） |
| `gta_dates` | 未来 `showtime_days` 天内在 GTA 有排片的日期列表，可为空 |
| `weeks_in_release` | 仅 `now_playing`：`(运行日期 − 上映日期).days // 7 + 1`，最小为 1 |
| `hurry` | 仅 `now_playing`：`weeks_in_release >= 3` 且 `len(gta_theatres) <= 2` |
| `rating_on` | `ratings` 里 `provinceCode == "ON"` 的那条，没有则为空 |

`hurry` 是推断，不是 Cineplex 给的下映日期。页面上标注为"推断"。

`is_event` 的片通常只放几场就没了，`hurry` 那条按周数算的规则对它不适用。这类片在页面上标"限定放映"，并直接列出 `gta_dates` 里的具体日期。日期是 Cineplex 排片的事实，不是推断。

## 7. 口味档案（`config/taste_profile.md`）

一份给模型读的中文档案，用户直接改它就能调口味，不用动代码。**它是提示词输入，不是工程文档**，里面只写口味，不写系统机制。

初稿内容：

1. **科幻**：正例《沙丘》系列。偏好有世界观、有作者表达的科幻。
2. **惊悚**：正例 A24 出品的那一路。氛围、心理、慢热优先于动作场面。
3. **政治、历史**。
4. **中国电影**：华语片，含港台。
5. **恐怖**：正例《仲夏夜惊魂》《遗传厄运》《着魔》。现代新恐怖、心理恐怖、民俗恐怖。**反例：美式 B 级砍杀片（slasher）**，这一类即使口碑好也不推荐。
6. **日本电影**：真人电影和动画电影都算。**特别想看经典动画电影的重映与修复版，正例《阿基拉》《攻壳机动队》。** 这类片在 Cineplex 常以"活动"或"限定放映"的形式出现，场次很少，不能因此降低优先级。

另写明：六类是加权不是排他。六类之外口碑特别强的片可以推荐，但要标为"口味之外"。

一部片可能同时属于多类（日本科幻动画既是日本电影也是科幻）。`category` 只填最主要的一类，其余在 `why_for_you` 里说明。

## 8. 粗筛（`triage.py`）

**一次调用**，不带工具。输入是口味档案和全部候选的元数据（id、片名、全部语言版本、类型、`filmCategories`、简介、导演、主演、发行方、上映日期、状态、是否活动场）。

语言必须给全部版本而不是只给主条目的。实测 `Ninja Scroll 4K` 的主条目是英语配音版，日语原声是它的 variant；只给主条目语言的话，模型看不出这是一部日本电影。

输出为结构化数据，每部候选一条：

```
film_id   int
keep      bool
rank      int | null     入围片的优先顺序，1 最优先；未入围为 null
category  scifi | thriller | political_historical | chinese | horror | japanese | outside
reason    str            一句中文理由
```

提示词要点：宁多勿漏；入围最多 `shortlist_cap` 部；简介是宣发文案，信息不足但有可能对口味的片应入围交给精评。

**程序校验：**

- `stop_reason` 为 `max_tokens` 或 `refusal` → 本次调用失败。
- 返回的 `film_id` 不在候选里 → 丢弃并记日志。
- 候选里有 id 没出现在返回中 → 只带缺失的那几部重试一次；仍缺 → 运行失败。
- 入围数超过 `shortlist_cap` → 按 `rank` 取前 `shortlist_cap` 部，其余改为未入围，理由追加"超出本期精评名额"。

调用用流式并取最终消息，`max_tokens` 给足（约 80 条判定加思考），避免截断。

**防注入：** 简介等 Cineplex 文本放在明确的数据区，提示词声明其为不可信数据、不作为指令。

## 9. 精评（`review.py`）

对每部入围片**各一次调用**，带联网搜索工具 `web_search_20260209`，`max_uses` 取 `search_max_uses`。一部失败不影响其他片。

输入：口味档案、该片的全部元数据、粗筛给的类别与理由。

输出一张卡片：

```
film_id          int
tier             must | ok | skip
strength         int 1–5          同档内的排序依据
category         同粗筛的七个取值
one_liner        str   一句话定位
premise          str   讲什么（不剧透，说人话）
why_for_you      str   为什么对口味，可类比口味档案里的锚点片
reception        str   口碑：影评、电影节履历
background       str   导演前作、制片公司
caveats          str   可能踩雷的地方
skip_reason      str | null       tier 为 skip 时必填，一句中文理由
evidence         ample | thin | none
title_zh         str | null
title_zh_source  url | null
scores           [{name, value, source_url}]
sources          [{title, url}]
```

**每期重新精评，不做跨期缓存。** 一部片最多出现在两到四期里，重复精评的成本很小，换来的是代码简单，以及未上映时评论稀少的片在上映后能拿到真实口碑。

### 防编造

模型的文字无法由程序逐句核对。程序能守住的是：**凡是可核对的声明都必须挂一个来源，而来源必须真的出现在那次调用的搜索结果里。**

1. **来源白名单**：收集该次调用里所有搜索结果块返回的 URL，作为白名单（比较前去掉 fragment 与末尾斜杠）。
2. `sources` 里不在白名单的条目丢弃，卡片记 `sources_dropped` 计数。
3. `scores` 里 `source_url` 不在白名单的条目丢弃。
4. `title_zh_source` 不在白名单 → `title_zh` 置空。
5. 无有效来源的卡片，`evidence` 强制为 `none`。

**这套校验的边界**：它保证每个评分和中文片名都有一个真实被检索到的页面可以点开核对，但**不能保证数字和页面内容一致**（搜索结果正文对程序不可见）。因此页面上评分一律渲染成带来源的链接，而不是裸数字。

提示词另外要求：评分数字只在搜索结果里出现时才写；中文片名只写搜得到的通行译名，不自行翻译；评论稀少时 `evidence` 填 `thin` 并在 `reception` 里明说依据是什么。

### 联网搜索与结构化输出的组合

实施时先验证同一请求里能否同时使用联网搜索工具和结构化输出（`output_config.format`）。

- 能：一次调用完成。
- 不能：拆成两次调用。第一次带搜索工具，输出带来源的自由文本；第二次不带工具，把第一次的文本整理成结构化卡片。白名单取自第一次调用的搜索结果块。

两种实现对 `review.py` 的调用方接口相同。

### 失败判定

以下任一情况，该片记为 `review_failed`，附原因：

- API 错误（SDK 重试用尽后仍失败）
- `stop_reason` 为 `max_tokens` 或 `refusal`
- `stop_reason` 为 `pause_turn` 时续跑，最多 3 次，仍未完成
- 搜索工具返回的是错误对象而非结果列表，且全程没有一次成功搜索
- 输出无法解析为卡片结构，或 `tier` 为 `skip` 却没有 `skip_reason`

联网搜索工具的错误不会抛异常，而是以 HTTP 200 加错误对象的形式返回，必须显式判别。

## 10. 汇总规则（`assemble.py`）

输入：候选、粗筛判定、卡片与失败记录、上一期 edition（没有则为空）。按顺序执行：

1. **无来源不得重点推荐**：`tier == must` 且有效来源数为 0 → 降为 `ok`，卡片标注"无有效来源"。
2. **口味之外名额**：`category == outside` 且 `tier` 为 `must` 或 `ok` 的，按（档位、`strength`）排序保留前 `outside_cap` 部，其余改为 `skip`，理由"口味之外名额已满"。
3. **重点推荐名额**：`must` 超过 `must_cap` 部时，按 `strength` 降序、上映日期降序保留前 `must_cap` 部，其余降为 `ok`。
4. **新旧标记**：上一期里已在 `must` 或 `ok` 的片标"上期已推荐"，否则标"新"。没有上一期时都不标。
5. **总数核对**：`must + ok + skip + review_failed == 候选总数`，其中 `skip` 包含粗筛未入围、精评判为跳过、名额溢出三种。对不上即抛异常，运行失败。

不凑数：`must` 为 0 是合法结果，页面如实显示"本期没有重点推荐"。

### edition 数据（`data/editions/<YYYY-MM-DD>.json`）

期号是运行日期（`America/Toronto` 时区）。同一天重跑覆盖同一期。内容：

- `edition_id`、`generated_at`、`next_edition_date`
- `settings` 快照（半径、窗口、名额）
- `films`：每部候选一条，含 Cineplex 事实字段、粗筛判定、卡片或失败记录、最终去向（`must` / `ok` / `skip` / `review_failed`）及去向理由
- `filtered_events`：被第 6 节规则 1 过滤掉的非电影活动，每条含片名与命中的类别。它们不是候选，不计入总数核对
- `usage`：各次调用的输入输出 token 数与搜索次数；token 部分按配置里的单价折算出估算费用，搜索只记次数
- `counts`：各去向的数量

期数序号 N 是该期在 `data/editions/` 下按日期排序的位置，从 1 开始。

## 11. 页面（`render.py`）

单个静态 HTML，样式内联，无外部依赖。海报直接引用 Cineplex 的图片地址。

**当期页，从上到下：**

1. 页头：期号、覆盖范围（GTA、Cineplex、半径）、数据抓取时间、下期日期。
2. **重点推荐**：大卡片。海报、英文片名（始终保留）、中文片名（有则显示）、类别、状态徽标（在映第 N 周 / X 月 X 日上映）、`hurry` 徽标"抓紧（推断）"、`is_event` 徽标"限定放映"及具体放映日期、新旧徽标、放映影院、片长、全部语言版本、安省分级；一句话定位、讲什么、为什么对你胃口、口碑、创作背景、可能踩雷；带来源的评分；来源链接；Cineplex 详情页链接。`evidence` 为 `thin` 或 `none` 时在口碑上方显示提示。
3. **可以看**：紧凑卡片，字段同上，正文默认收起。
4. **本期未能评估**：仅在有 `review_failed` 时出现。列出片名、粗筛理由、失败原因。
5. **跳过**：折叠区。每部一行：片名、理由。
6. **已过滤的非电影活动**：折叠区。只列片名与命中的类别（歌剧、演唱会等），不做任何评估。用途是让误杀看得见：如果某部电影被错归到这里，一眼能发现。
7. 页脚：往期存档链接、本期用量、"推荐由模型生成，评分请点来源核对"。

**过期提示**：页面内联一小段脚本，比较当前日期与 `generated_at`，超过 `stale_after_days` 天就在页头显示"这一期已过期，新一期可能生成失败"。

**视觉**：灰白极简，手机优先（通知会在手机上点开），徽标文字不小于 10.5px。

**安全**：所有来自模型和 Cineplex 的文本做 HTML 转义后再写入页面；链接只接受 `http`/`https` 协议。

**产物**：`site/index.html`（最新一期）、`site/editions/<id>.html`（每期一页）。

## 12. 调度、发布与通知（`.github/workflows/edition.yml`）

**触发：**

- 定时：每周四 11:00 UTC（多伦多 7:00 夏令时 / 6:00 冬令时），赶在周五新片上映之前。
- 手动：`workflow_dispatch`，随时可重跑。

**双周门控**：GitHub 的定时语法表达不了"每两周"。`main.py` 用配置里的 `anchor_date`（2026-10-08，周四）计算 `(运行日期 − anchor_date).days // 7 % 2`，为 0 才执行，否则正常退出、在日志里说明是跳过周，并通过步骤输出让后面的提交、部署、开 Issue 步骤一并跳过。按距离锚点的天数算，跨年不会错位。手动触发不受门控限制。

**步骤：**

1. 检出仓库，装 Python 3.11 与依赖。
2. 运行流水线，生成当期 edition。
3. 提交 `data/editions/<id>.json`。
4. 构建 `site/` 并部署到 GitHub Pages。
5. 开 Issue：标题为"第 N 期 M/D：片名一、片名二、片名三"（没有重点推荐时写明"本期没有重点推荐"），正文每部重点推荐一行（片名、一句话定位、状态）加页面链接，标签 `edition`。
6. 把用量与各去向数量写进 Actions 运行摘要。

**失败时**：流水线任一步失败则后续步骤不执行，已发布的页面保持不变。末尾有一个仅在失败时执行的步骤，开一个标签为 `failure` 的 Issue，写明失败环节与运行日志链接。

`edition` 与 `failure` 两个标签在建仓库时创建一次。

**权限**：`contents: write`、`pages: write`、`id-token: write`、`issues: write`。提交、部署、开 Issue 都用 Actions 自带令牌。

**密钥**：只有 `ANTHROPIC_API_KEY`，存仓库 Secrets。由用户本人执行 `gh secret set ANTHROPIC_API_KEY` 录入，密钥不经过对话与日志。

每次运行都会向仓库提交数据，因此不会触发 GitHub 对长期无活动仓库停用定时任务的规则。

## 13. 失败处理

原则：**不允许静默失败。**

| 情况 | 处理 |
|---|---|
| 取不到密钥；接口返回 401/403；响应结构校验失败 | 运行失败，不动已发布页面，开失败 Issue |
| 片单少于 20 部；在映片为 0；GTA 影院为 0；GTA 排片为 0；候选为 0 | 按失败处理。这些"0"更可能是接口变了而不是真的没片 |
| 超过一半候选的详情页抓取或解析失败 | 运行失败 |
| 个别候选的详情页失败 | 该片保留为候选，标 `details_missing`，粗筛只凭片单字段判断 |
| 粗筛截断、拒答、漏判 | 见第 8 节：重试一次，仍缺则运行失败 |
| 单片精评失败 | 该片进"本期未能评估"区，不丢弃、不降成跳过 |
| 超过一半入围片精评失败 | 运行失败，不发布 |
| 来源未通过白名单校验 | 丢弃该来源并标注；无有效来源不得重点推荐 |
| 总数核对不通过 | 运行失败 |
| 部署或开 Issue 失败 | 工作流失败，GitHub 发工作流失败邮件 |
| 新一期没生成 | 旧页面在超过 16 天后自行显示过期提示 |

粗筛入围为 0 不算失败：每部候选都有带理由的明确判定，页面如实显示。

## 14. 成本护栏

- 入围上限 `shortlist_cap`（15）；每片搜索次数上限 `search_max_uses`（5）。
- 每次运行记录实际 token 用量与搜索次数，写入 edition 数据、页脚和 Actions 摘要。
- 费用估算只算 token 部分，单价写在配置里（`claude-opus-5-5`：输入每百万 token 4 美元，输出 20 美元）。联网搜索另按次计费，其单价本设计没有核实过，所以只记次数、不折算金额，实际花费以 Anthropic 控制台账单为准。
- 设计阶段的估算是每期 2–5 美元量级，**未经实测**。首跑后以实际用量为准，并据此决定是否调整上限。

## 15. 配置（`config/settings.toml`）

| 键 | 默认值 | 含义 |
|---|---|---|
| `home_lat` / `home_lon` | 43.6532 / −79.3832 | GTA 中心点（多伦多市中心） |
| `radius_km` | 40 | GTA 半径。实测覆盖 22 家影院，含 Markham、Richmond Hill、Mississauga |
| `showtime_days` | 7 | 排片查询天数 |
| `coming_soon_days` | 14 | 即将上映窗口 |
| `non_film_categories` | `Opera`、`Concert`、`Stage`、`Stage Performance`、`Television Event`、`Sport` | 活动场里要过滤的类别。只对 `isEvent` 为真的条目生效 |
| `shortlist_cap` | 15 | 精评名额 |
| `must_cap` | 6 | 重点推荐上限 |
| `outside_cap` | 2 | 口味之外名额 |
| `search_max_uses` | 5 | 每片搜索次数上限 |
| `anchor_date` | 2026-10-08 | 双周门控锚点 |
| `stale_after_days` | 16 | 页面过期提示阈值 |
| `model` | `claude-opus-5-5` | 模型 |
| `price_input_per_mtok` / `price_output_per_mtok` | 4.00 / 20.00 | 费用估算用的 token 单价（美元） |
| `timezone` | `America/Toronto` | 期号与日期计算所用时区 |

## 16. 测试策略

- 测试不访问真实网络与 API。Claude 调用与 HTTP 请求全部 mock。
- **Cineplex 测试数据用真实响应裁剪**，不手写。实施的第一步就是抓一份真实响应存为 fixture。
- `candidates`：表驱动测试。第 14 天与第 15 天的边界；半径边界；多版本合并及排片并入；预售中的未上映片；`hurry` 的两个阈值。
- 活动过滤单列，用附录 A 的真实条目做用例：歌剧与演唱会被过滤并进入 `filtered_events`；动画重映（`Ninja Scroll 4K`）、活动场恐怖片（`Fresh Meat`）保留为候选；类别不在排除名单里的未知活动保留；非活动的 `Sport` 类片不受影响；英配与日语原声两个版本合并后 `versions` 里两种语言都在、`is_event` 为真。
- `triage`：截断、拒答、未知 id、漏判后重试成功、漏判后重试仍缺、入围超额。
- `review`：第 9 节每一种失败判定各一条；白名单对 `sources`、`scores`、`title_zh` 的处理；搜索错误对象的判别。
- `assemble`：三条名额与降档规则；新旧标记；总数核对在人为制造不一致时抛异常。
- `render`：每部候选在页面上恰好出现一次；`review_failed` 区在有失败时出现；模型文本里的 HTML 被转义；过期提示脚本存在。
- `main`：双周门控的奇偶周与跨年；第 13 节每一行失败模式的退出码。
- **护栏验红**：每条护栏写完后注入一次对应的缺陷，确认测试变红。测不红的护栏不算完成。
- **端到端**：收尾前在 Actions 上手动触发一次真实运行，人工检查渲染出的页面（桌面与手机两种宽度），并确认通知到达。

## 17. 必须先验证的前提

以下前提不成立会改变架构，放在实施计划最前面，验证通过才继续。

| # | 前提 | 当前状态 | 不成立时的退路 |
|---|---|---|---|
| 1 | GitHub Actions 的机房 IP 能访问 Cineplex 网站与接口 | **未验证**。只在用户本机测过 | 抓取改在本机 launchd 执行，把原始数据推到仓库，由 Actions 接手后半段 |
| 2 | Actions 机器人开的 Issue 会给仓库所有者发邮件与 App 推送 | **未验证** | 改用邮件直发，或在 Issue 里 @ 用户 |
| 3 | 用户的 GitHub 套餐允许公开仓库使用 Pages 与定时 Actions | 公开仓库免费可用，属常识但未在本账号实测 | 无需退路，首次部署即可确认 |
| 4 | 联网搜索与结构化输出可在同一请求中使用 | **未验证** | 第 9 节已定义两次调用的实现 |
| 5 | 联网搜索对新片、华语片能搜到足够的评论 | **未验证** | `evidence` 机制已覆盖评论稀少的情况；若普遍稀少，需重新评估精评的价值 |

已实测通过的前提见附录 A。

## 18. 风险

- **Cineplex 接口随时可能失效。** 非官方用法，无法根治。能做到的是失效时明确报错而不是出空页。若频繁失效，需要重新考虑数据源。
- **防编造的边界。** 程序只保证声明有来源，不保证声明与来源一致。页面以"带来源的链接"呈现并在页脚提示。
- **两周一次的残余漏洞。** 临时加映且放映不满两周的片可能在两期之间出现又消失。改为每周运行可消除，成本翻倍。
- **`hurry` 是启发式。** 可能把一次性的经典重映也标为"抓紧"，页面已注明为推断。
- **活动过滤靠 Cineplex 的类别标签。** 一部电影如果被 Cineplex 错标了 `Concert` 之类的类别，会被过滤。对策是过滤清单在页面上可见，以及排除名单写在配置里可以随时调。反方向的代价是：没见过的活动类别会放行进粗筛，多花一点 token。
- **限定放映的片可能赶不上。** 活动场常常只放一两天。两周一次的节奏下，排片公布得晚的限定场次仍可能在两期之间出现又消失。这是"两周一次的残余漏洞"在活动场上的加重版，改为每周运行同样能缓解。
- **公开仓库。** 口味档案与每期推荐公开可见。

## 附录 A：Cineplex 接口实测记录（2026-10-03，用户本机）

基址：`https://apis.cineplex.com/prod/cpx/theatrical/api`。请求头 `Ocp-Apim-Subscription-Key`。响应为 gzip 压缩的 JSON。不带密钥返回 401。

**`GET /v2/movies?language=en`** → `{items: [...], totalCount}`。实测 258 条。单条字段：

`filmCategories`、`id`、`releaseDate`、`name`、`runtimeInMinutes`、`filmUrl`、`smallPosterImageUrl`、`mediumPosterImageUrl`、`largePosterImageUrl`、`brightcoveVideoId`、`language`、`subtitleLanguage`、`marketLanguageCode`、`genres`、`ratings`、`distributor`、`detailPageUrl`、`hasPosterImage`、`isNowPlaying`、`isRelevant`、`isComingSoon`、`hasShowtimes`、`isEvent`、`isEarlyAccess`

实测观察：

- `isNowPlaying` 与 `isComingSoon` 互斥且必有其一。在映 50，即将上映 208。
- `isEvent` 为真的 47 条（Metropolitan Opera、Trafalgar Releasing 等）。
- 在映且非活动 46 部；14 天内上映且非活动 31 部。
- `language` 取值含 `English`、`Mandarin`、`Cantonese`、`Chinese`、`Korean`、`Hindi`、`Spanish (Dubbed)` 等。华语片 4 部，片名带括号如 `(Mandarin w/Chinese and e.s.t.)`，发行方为 CMC、Well Go USA、Niu Vision。
- `marketLanguageCode` 全部为 `EN`，不能用来区分版本。
- `genres` 很粗且可能为空数组。
- `distributor` 是加拿大本地发行商，不出现 A24 等制片公司。
- 配音版是独立条目、独立 id，片名为原片名加括号后缀。
- `ratings` 是按省的数组，每项含 `provinceCode`、`rating`、`warnings`、`ratingDescription`。

`/v1/movies` 返回同样的 258 条，只是没有 `filmCategories` 字段。

**`isEvent` 与 `filmCategories` 的实测关系**（第 6 节规则 1 的依据）：

- `filmCategories` 全部取值：`Action`、`Adventure`、`Alt Prog Film Event`、`Animation`、`Anime`、`Biography`、`Classic`、`Comedy`、`Concert`、`Crime`、`Documentary`、`Drama`、`Event`、`FRCE Feature Release`、`Family`、`Fantasy`、`Film Presentation`、`Horror`、`International`、`Music`、`Mystery`、`Opera`、`Romance`、`Science Fiction`、`Sport`、`Stage`、`Stage Performance`、`Suspense`、`Television Event`、`Thriller`。
- 47 条活动的 `filmCategories` 都非空。
- 按排除名单过滤掉 41 条：`Opera` 19、`Concert` 16、`Stage` 3、`Television Event` 2、`Stage Performance` 1。其中没有日语片，也没有带 `Anime`、`Horror`、`Classic`、`Animation` 的。
- 保留 6 条：`Ninja Scroll 4K`（英配）、`Ninja Scroll 4K (Japanese w.e.s.t.)`、`Dive in Wonderland (Japanese w.e.s.t)`（三者均为 `Anime` + `FRCE Feature Release`）、`Fresh Meat`（`Horror` + `FRCE Feature Release`）、`E.T. the Extra-Terrestrial - Family Favourites`（`Classic` + `Alt Prog Film Event`）、`HANGING BY A WIRE`（`Documentary`）。
- 非活动片里只有 1 部带排除名单里的类别（`Thaapi`，`Sport`），规则不对它生效。
- 日语片共 4 部，2 部是活动（上面两部动画），2 部不是（`Godzilla Minus Zero`、`Yuri!!! on ICE 10th Anniversary`）。
- `Music` 不在排除名单里，因为它也是普通电影的类型标签。实测带 `Music` 的活动同时都带 `Concert`。

**`GET /v1/theatres?language=en&latitude=43.6532&longitude=-79.3832&range=30`** → `{favouriteTheatres, nearbyTheatres, otherTheatres}`。`nearbyTheatres` 固定只给最近 10 家，`otherTheatres` 142 家。两者单条字段相同：`theatreId`、`theatreName`、`shortTheatreName`、`theatreUrl`、`hasFreeParking`、`alertMessages`、`location`。

`location` 含 `geoLocation {latitude, longitude}`、`distanceToOriginInMeters`、`hasDistanceToOrigin`、`address`、`city`、`provinceCode`、`postalCode`。全部 152 家都带距离。

以多伦多市中心为原点：30 公里内 19 家，40 公里内 22 家（Toronto 12、Mississauga 3、Vaughan、Richmond Hill、Markham、Oakville、Pickering、Brampton、Ajax 各 1），50 公里内 27 家。

**`GET /v1/showtimes?language=en&locationId=<theatreId>&date=MM/DD/YYYY`** → `[{theatre, theatreId, dates: [{startDate, movies: [...]}]}]`。一次请求只返回所请求的那一天。影片字段含 `id`、`name`、`filmUrl`、`isEvent`、`genres`、`experiences`、`language`、`subtitleLanguage`、`localRating`、`detailPageUrl`。`experiences[].sessions[]` 含 `showStartDateTime` 等。可加 `filmId` 参数只查一部片。

**`GET /v1/dates/bookable?language=en&locationId=<theatreId>`** → 该影院可订票日期的字符串数组，实测覆盖未来 12 天以上。

**详情页 `https://www.cineplex.com/movie/<filmUrl>`** → HTML 内 `<script id="__NEXT_DATA__">`，路径 `props.pageProps.movieDetails`。字段含 `id`、`parentFilmId`、`isParentFilm`、`name`、`synopsis`、`starring`、`director`、`producers`、`writers`、`genres`、`distributor`、`movieLanguage`、`movieSubtitleLanguage`、`releaseDate`、`runtimeInMinutes`、`isNowPlaying`、`isComingSoon`、`hasShowtimes`、`slug`。实测 `producers`、`writers` 可能为空串。

**走不通的路**：首页 `__NEXT_DATA__` 里的 `initialPostersV2` 片单为空（片单由浏览器端调接口加载），不能靠解析首页 HTML 拿片单。`/movies`、`/now-playing` 等路径返回 404。
