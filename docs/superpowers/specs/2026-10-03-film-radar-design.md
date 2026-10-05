# film-radar 设计文档

- 日期：2026-10-03
- 状态：已实施。首期 2026-10-03 上线；之后按实测与用户反馈多次更新（搜索额度、粗筛与精评分模型、页面改版与「我已经看过」），每处都注明了日期
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
| 仓库可见性 | 公开（免费版 GitHub Pages 只支持公开仓库）。**2026-10-03 执行计划时用户一度改选私有，实测本账号套餐不支持私有仓库的 Pages（HTTP 422），用户改回公开。** 即使选私有，Pages 站点本身也对互联网公开，私有只保护源码与数据 | 用户选定 |
| 口味类别 | 七类：科幻、惊悚、政治历史、中国电影、恐怖、日本电影（含经典动画电影重映）、犯罪 | 前五类为用户原定；第六类为用户审阅 spec 时追加；第七类（犯罪）为用户 2026-10-04 看过两期结果后追加 |
| 口味之外的片 | 七类加权而非排他；七类之外每期最多 2 个位置 | 设计确认 |
| 活动场的处理 | 只过滤非电影类活动（歌剧、演唱会、舞台剧、电视节目）；以活动形式放映的电影保留为候选 | 用户审阅时指出，实测数据确认（见附录 A） |
| 运行位置 | 全部在 GitHub Actions | 设计确认 |
| 模型 | **精评 `claude-sonnet-5-5`，粗筛 `claude-opus-5-5`（2026-10-04 起）。** 首期（2026-10-03）两个阶段都用 `claude-opus-5-5`，运行后用户嫌 token 费用太高，改为 Sonnet 5.5；随后对照实验发现粗筛换成 Sonnet 后选片会系统性地变（见第 8 节末尾），而粗筛一次调用只要一两毛钱，所以粗筛换回 Opus。单价（每百万 token）：Opus 5.5 输入 4 / 输出 20 美元，Sonnet 5.5 输入 2 / 输出 10 美元 | 用户选定 |

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
cineplex      运行时取密钥；片单、GTA 影院、未来 14 天排片、单片详情
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
| `llm.py` | 唯一调用 anthropic SDK 的地方：`pause_turn` 续跑、异常归一 | 提示词、schema、工具 | 停止原因、文本、内容块、token 数 | Claude API |
| `schema.py` | 极小的 JSON Schema 校验器，对模型输出在本地再校验一遍 | 值、schema | 通过或抛错 | 无 |

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

- 走官方 `anthropic` Python SDK。精评的模型取自 `config/settings.toml` 的 `model`（现为 `claude-sonnet-5-5`），粗筛的取自 `triage_model`（现为 `claude-opus-5-5`）；首期两者都是 `claude-opus-5-5`。每一期的 `models` 字段记下当时各阶段用的模型。
- 思考用 `thinking={"type": "adaptive"}`，不传 `budget_tokens`（这两个模型都会 400）；`effort` 显式设置，不依赖默认值（Opus 5.5 默认 `medium`，Sonnet 5.5 默认 `high`，档位含义随模型重新校准过，不显式写容易在换模型时悄悄变化）：粗筛 `medium`，精评 `high`。换成 Sonnet 5.5 时没有重新扫过 effort，沿用首期的取值。
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
3. 对每家 GTA 影院，先 `GET /v1/dates/bookable?language=en&locationId=<id>` 取该店已开放排片的日期，与"运行当天起 `showtime_days` 天"的窗口取交集；再对交集里的每一天 `GET /v1/showtimes?language=en&locationId=<id>&date=MM/DD/YYYY` → 该店当日在映影片。没有排片的日期返回 HTTP 204、响应体为空，按"当天无排片"处理，不算错误。

   **`showtime_days` 必须不小于两期的间隔（14 天）。** 天天有场的普通片查 7 天就够，但经典重映、限定放映这类零星放映的片不行：窗口只有 7 天时，一场排在第 10 天的放映在本期查不到，到下一期又已经放完，两期都漏。先查可订票日期再查排片，是为了不对还没开放排片的日期发空请求。
4. 过滤出候选后，对每部候选抓 `https://www.cineplex.com/movie/<filmUrl>`，解析 `__NEXT_DATA__` 里的 `props.pageProps.movieDetails` → 简介、导演、主演。

请求间隔不小于 0.3 秒。按 22 家影院、最多 14 天、约 90 部候选估算，单次运行最多约 450 个请求，耗时 3–4 分钟。

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

**是否活动场一律以片单为准。** 排片接口里每部片也带 `isEvent`，但它不可信：实测 `Ninja Scroll 4K` 在片单里是 `true`，在排片里是 `false`。

**排片里出现、片单里却没有的影片 id 要报出来。** 按 id 去片单里找不到的片无法进入候选，如果不声不响地跳过，就是一部正在 GTA 放映的片从页面上消失。这些 id 记入当期数据的 `orphan_ids` 并在页脚显示。2026-10-03 实测没有这种情况。

每部候选携带由程序计算的事实字段：

| 字段 | 算法 |
|---|---|
| `title` | 主条目片名去掉末尾括号。语言与字幕另行显示 |
| `versions` | 主条目与全部 variants 各自的语言与字幕，如"英语配音""日语原声 / 英文字幕" |
| `status` | 主条目 `isComingSoon` 为真则 `coming_soon`，否则 `now_playing` |
| `is_event` | 主条目或任一 variant 的 `isEvent` 为真 |
| `gta_theatres` | 未来 `showtime_days` 天内有排片的 GTA 影院名列表，可为空（近期上映但排片未出） |
| `gta_dates` | 未来 `showtime_days` 天内在 GTA 有排片的日期列表，可为空 |
| `weeks_in_release` | 仅 `now_playing`：`(运行日期 − 上映日期).days // 7 + 1`，最小为 1。**超过 52 周视为老片重映，记为 `None`**：Cineplex 重映时沿用原来的上映日期，会算出「在映第 326 周」这种没有意义的数；页面上改显示「重映（2020 年上映）」（2026-10-03 终审补） |
| `hurry` | 仅 `now_playing` 且**非 `is_event`**：`weeks_in_release >= 3` 且 `len(gta_theatres) <= 2`。限定放映本来就只放几场，这条规则对它不适用（下文）；老片重映（`weeks_in_release` 为 `None`）也不算 |
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
7. **犯罪**：犯罪片也想看。口味档案里目前只有这一句，没有正例和反例；想收紧可以补，比如更爱黑色电影、犯罪惊悚还是黑帮片。

另写明：七类是加权不是排他。七类之外口碑特别强的片可以推荐，但要标为"口味之外"。

一部片可能同时属于多类（日本科幻动画既是日本电影也是科幻）。`category` 只填最主要的一类，其余在 `why_for_you` 里说明。

## 8. 粗筛（`triage.py`）

**一次调用**，不带工具。输入是口味档案和全部候选的元数据（id、片名、全部语言版本、类型、`filmCategories`、简介、导演、主演、发行方、上映日期、状态、是否活动场）。

语言必须给全部版本而不是只给主条目的。实测 `Ninja Scroll 4K` 的主条目是英语配音版，日语原声是它的 variant；只给主条目语言的话，模型看不出这是一部日本电影。

输出为结构化数据，每部候选一条：

```
film_id   int
keep      bool
rank      int | null     入围片的优先顺序，1 最优先；未入围为 null
category  scifi | thriller | political_historical | chinese | horror | japanese | crime | outside
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

**粗筛的稳定性（2026-10-04 实测，`scripts/triage_compare.py`）。** 同一份 70 部候选、同一份口味档案，Sonnet 5.5 与 Opus 5.5 各跑 3 次粗筛，名额 15：

- 同一个模型自己跑 3 次，两两重合 Sonnet 12–14、Opus 13–14（分别有 6 部、4 部时进时出）。70 选 15，排名 10–20 的片基本是抛硬币，稳定的「核心」约 12 部。
- 两个模型互相比只重合 10–12 部，比同一模型自己比（12–14）低：除了随机波动，还有系统性的模型差异。
- Atonement：Opus 4/5 入围（首期加实验 3 次入围；2026-10-04 晚的整期运行里同一个 Opus 没选它，理由「名额有限」），Sonnet 0/4。模型差异是主因，但名额边缘的片**同一模型内也会翻**。
- 一次粗筛：2.9 万输入、0.4–0.5 万输出，Sonnet 约 $0.10、Opus 约 $0.22。它是整条流水线里最便宜、也最关键的一步，所以单独用 Opus。

没做、留给用户决定的稳定化手段：粗筛跑多次按多数票入围（每期再 +$0.4）；调大 `shortlist_cap`。（粗筛单独用 Opus 已经做了，见第 14 节。）

## 9. 精评（`review.py`）

对每部入围片**两次调用**：第一次带联网搜索工具 `web_search_20260209`（`max_uses` 取 `search_max_uses`，**`allowed_callers` 设为 `["direct"]`，提示词里写明搜索预算**，见下面「搜索额度」一节），写一份带来源的中文调查笔记；第二次不带工具，把笔记整理成结构化卡片。一部失败不影响其他片。

输入：口味档案、该片的全部元数据、粗筛给的类别与理由。

输出一张卡片：

```
film_id          int
tier             must | ok | skip
strength         int 1–5          同档内的排序依据
category         同粗筛的八个取值
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

### 搜索额度（2026-10-04 实测，`scripts/research_compare.py`）

**现象：** Sonnet 版第一期里，Ninja Scroll 4K 一个有效来源都没有（证据 none），卡里自述「搜索工具调用次数超限」；潘神的迷宫只有 1 个来源；全期 `evidence=ample` 从 12 张掉到 2 张。

**机制（读完整时间线确认，不是推测）：** `web_search_20260209` 默认让模型在代码里调搜索（`allowed_callers` 默认是代码执行）。Ninja Scroll 4K 的基线运行里，模型先成功搜了 5 次（`max_uses` 用完），又在代码里试图多搜，两次都以 `Server tool use limit exceeded during code execution` 失败，于是它在笔记里写「联网搜索失败了」，把前面拿到的 5 次结果全扔掉。搜索结果其实都在，是模型自己放弃了它们。

**2×2 对照（Sonnet 5.5，3 部片 × 4 种配置，各跑 1 次）：**

| 配置 | 平均输入 token | 搜索 | 出错 | 代码执行失败 | 卡片来源 | 评分 | 证据 充/少/无 | 每部估算 |
|---|---|---|---|---|---|---|---|---|
| A 基线（默认调用，提示词不提预算） | 107,618 | 5.0 | 0.0 | 2.7 | 6.7 | 2.0 | 2/0/1 | $0.315 |
| B 只写明预算 | 120,371 | 4.3 | 1.7 | 1.3 | 10.0 | 3.3 | 3/0/0 | $0.332 |
| C 只改直接调用 | 58,919 | 4.7 | 0.3 | 0.0 | 10.7 | 3.3 | 2/1/0 | $0.211 |
| **D 直接调用 + 写明预算（采用）** | 61,852 | 3.0 | 0.0 | 0.0 | 10.3 | 3.0 | 3/0/0 | **$0.194** |

直接调用把代码执行失败降到 0，输入 token 少约 43%（搜索结果不再经过代码来回倒）；写明预算让模型少搜、少出错。两个改动叠加最好：D 比基线每部便宜约 38%，且没有一部掉到证据 none。

**样本很小：** 3 部片、每种配置 1 次，Sonnet 一个模型。方向明确，数字不能当精确值；D 的「少搜」（3.0 次）也可能意味着个别片查得不如基线深，整期运行后要看评分与来源数有没有整体下降。　**整期实测（同日 2026-10-04 第二次运行）支持了方向：** 证据 充/少/无 从 3/8/4 变成 10/5/0，平均来源 5.2→9.3，平均评分条数 1.1→3.5，没有一张卡是零来源；Ninja Scroll 4K 与潘神的迷宫从证据 none / 1 个来源变成 ample / 10、11 个来源。搜索次数平均每片 2.7 次（74→40 次），没有因为「少搜」而变浅。这些仍是结构性指标（来源数、证据档），**没有逐张核对卡片内容的事实准确性**，只有来源链接必在白名单内这一条由代码保证。

**别改回去：** `search_tool()` 的 `allowed_callers` 与 `SEARCH_BUDGET_PROMPT` 默认值各有测试守着。也不能换成 `web_search_20260318` 的 `response_inclusion: "excluded"`：它会把搜索结果块从响应里删掉，来源白名单就取不到网址了。


### 防编造

模型的文字无法由程序逐句核对。程序能守住的是：**凡是可核对的声明都必须挂一个来源，而来源必须真的出现在那次调用的搜索结果里。**

1. **来源白名单**：取调查那次调用里**搜索结果块**（`web_search_tool_result`）中出现的网址，加上 API 附在文本块上的引用网址（比较前去掉 fragment、末尾斜杠与末尾标点，协议与域名转小写）。模型自己写的正文、它发出的搜索请求、思考块，以及**代码执行结果块**（`code_execution_tool_result` 等）都不算——取了等于让模型给自己作证。白名单为空即判该片精评失败。

   **为什么代码执行结果块不算（2026-10-03 任务 4 真实响应实测）：** 带动态过滤的搜索工具会让模型写代码去调用搜索。那些代码的执行结果里，stdout 是加密字段，stderr 是明文且会回显模型自己写的代码，所以是模型自己产出的内容。搜索结果的网址仍然完整出现在 `web_search_tool_result` 块里（实测 3 次搜索共 30 条、15 个不重复网址，代码执行结果块里一个都没有），收紧不丢任何真实网址。代价：若将来搜索工具把结果放进别的块类型，白名单会为空，该片精评失败，是响亮的失败而不是静默放行。
2. `sources` 里不在白名单的条目丢弃，卡片记 `sources_dropped` 计数。
3. `scores` 里 `source_url` 不在白名单的条目丢弃。
4. `title_zh_source` 不在白名单 → `title_zh` 置空。
5. 无有效来源的卡片，`evidence` 强制为 `none`。

**这套校验的边界**：它保证每个评分和中文片名都有一个真实被检索到的页面可以点开核对，但**不能保证数字和页面内容一致**（搜索结果正文对程序不可见）。因此页面上评分一律渲染成带来源的链接，而不是裸数字。

提示词另外要求：评分数字只在搜索结果里出现时才写；中文片名只写搜得到的通行译名，不自行翻译；评论稀少时 `evidence` 填 `thin` 并在 `reception` 里明说依据是什么。

### 为什么是两次调用

最初的设计是先验证"同一请求里能否同时用联网搜索和结构化输出"，能就一次调用，不能再拆。写实施计划时改为**直接采用两次调用，不做那项验证**：

- 结构化输出与引用不兼容，而搜索结果自带引用。两次调用在任何情况下都成立。
- 计划里不必留一条"验证不通过就重写"的分支。
- 调查与整理分开后，第二次调用只看笔记和白名单，接触不到网页原文，少一条被网页内容带偏的路。

代价是每部片多一次很便宜的调用（输入只有笔记和白名单）。

第二次调用时把白名单原样列给模型，要求来源只能从中挑选；模型返回后程序再按白名单过一遍。

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

- `edition_id`、`generated_at`、`next_edition_date`（**下一次真正会运行的日期**：从 `anchor_date` 起每 14 天一次、晚于运行日的第一个。不是「运行日 + 14 天」：手动跑的那天不在双周节奏上，首期在锚点前五天手动跑，下期是 10-08 而不是 10-17）
- `settings` 快照（半径、窗口、名额）
- `films`：每部候选一条，含 Cineplex 事实字段、粗筛判定、卡片或失败记录、最终去向（`must` / `ok` / `skip` / `review_failed`）及去向理由
- `filtered_events`：被第 6 节规则 1 过滤掉的非电影活动，每条含片名与命中的类别。它们不是候选，不计入总数核对
- `orphan_ids`：排片里出现但片单里没有的影片 id（见第 6 节）
- `usage`：各次调用的输入输出 token 数与搜索次数；token 部分按配置里的单价折算出估算费用，搜索次数按 `search_price_per_search` 折算（`estimated_token_cost_usd` / `estimated_search_cost_usd` / `estimated_cost_usd`）。2026-10-04 之前的期数据没有后两项，渲染时保持原说法「token 费用估算…（不含搜索费）」
- `counts`：各去向的数量

期数序号 N 是该期在 `data/editions/` 下按日期排序的位置，从 1 开始。

## 11. 页面（`render.py`）

单个静态 HTML，样式内联，无外部依赖。海报直接引用 Cineplex 的图片地址。

**当期页，从上到下：**

1. 页头（浅色英雄区）：期号、覆盖范围（GTA、Cineplex、半径）、数据抓取时间、下期日期，以及三个计数（重点推荐 / 可以看 / 跳过，有失败时加「未能评估」）。下面是吸顶的章节导航（速览、重点推荐、可以看、跳过、历史期数，只链接存在的章节）。
1a. **本期速览**（仅在有重点推荐或可以看时出现）：一张表，每部片一行——分类色点、片名与中文名、类别、状态（在映第 N 周 / X 月 X 日上映）、限定放映与「抓紧（推断）」标记、推荐力度条；点一行跳到对应卡片。目的是一屏看完这期有什么、哪几部放映时间紧。
2. **重点推荐**：大卡片。海报、英文片名（始终保留）、中文片名（有则显示）、类别、状态徽标（在映第 N 周 / X 月 X 日上映）、`hurry` 徽标"抓紧（推断）"、`is_event` 徽标"限定放映"及具体放映日期、新旧徽标、放映影院、片长、全部语言版本、安省分级；一句话定位、讲什么、为什么对你胃口、口碑、创作背景、可能踩雷；带来源的评分；来源链接；Cineplex 详情页链接。`evidence` 为 `thin` 或 `none` 时在口碑上方显示提示。
3. **可以看**：紧凑卡片（桌面两栏），字段同上，正文默认收起。**影院多于 4 家时首屏只写「N 家影院」，完整名单放进展开里**（名单常常就是全部 Cineplex，会比正文还长）；重点推荐的卡片始终完整列出影院。
4. **本期未能评估**：仅在有 `review_failed` 时出现。列出片名、粗筛理由、失败原因。
5. **跳过**：折叠区。每部一行：片名、理由。
6. **已过滤的非电影活动**：折叠区。只列片名与命中的类别（歌剧、演唱会等），不做任何评估。用途是让误杀看得见：如果某部电影被错归到这里，一眼能发现。
7. 页脚：往期存档链接、本期用量、"推荐由模型生成，评分请点来源核对"。

**过期提示**：页面内联一小段脚本，比较当前日期与 `generated_at`，超过 `stale_after_days` 天就在页头显示"这一期已过期，新一期可能生成失败"。

**视觉（2026-10-04 至 05 三次改版）**：原来的版式是一列 760px 的白卡片，每张卡片七段文字加十几条链接，所有片一个样。第一次改版加了层次与暗色模式；第二次按用户要求补了配色，走瑞士（国际主义）风格的原色体系；第三次按用户反馈**去掉了暗色**（见下）：

- **层次**：浅色英雄区 → 速览表 → 重点推荐的大卡片（海报 156px；片名用粗体无衬线；一句话定位放大；「为什么对你胃口」做成着色色块；口碑 / 创作背景 / 可能踩雷在桌面分三栏）→ 可以看的双栏紧凑卡片。章节标题用 CSS 计数器生成红色序号（01、02……），上面一道 5px 粗线。
- **四个品牌色，各有职责**：**信号红**＝行动与紧迫（购票按钮、限定放映标签、可能踩雷的边线）；**钴蓝**＝结构与链接（「可以看」计数块、链接）；**信号黄**＝高亮（「重点」标签、「新」徽标、重点推荐计数块、章节计数、悬停）；**绿**＝已完成（「已看过」角标与按钮）。每个品牌色配一个文字色 `--on-*`，用在它的底色上；红色作为文字（章节序号）时单独用更深的 `--red-ink`，链接用 `--link`。只有一套令牌（页面始终是浅色）。
- **英雄区**：与页面同一个暖白底（不再是黑底）、胶片边（浅灰虚线）、右侧几何构图（红圆、黄方、蓝四分之一圆、绿点，纯 CSS，`aria-hidden`；手机上收成一排小色块）、底部四色条，下面是三个计数块（黄 / 蓝 / 描边）。
- **七个类别色**（`HUES`）：用在分类色点、卡片左边条、类别徽标、力度条、没海报时的占位块上；口味之外用灰。**刻意比品牌色更沉**（饱和度 50%），好让「类别」和「状态」一眼分得开。已看过的状态因此**不用色相**表达：灰色边条、空心圆点、删除线，只有「已看过」的文字角标和按钮用绿色。
- **推荐力度条**：五格，数据是卡片的 `strength`。
- **链接**：评分与来源做成方角胶囊（评分的胶囊用类别色 2px 描边），Cineplex 购票是独立的红色按钮，紧凑卡片不展开也能点。按钮、导航、标签、卡片都是方角。
- **始终浅色，不跟随系统暗色**（2026-10-05）：用户的系统是暗色，页面曾经会整页变成黑底白字，反馈「黑的对比度有点高，看着不舒服」，所以英雄区改成浅色、整页去掉 `prefers-color-scheme: dark`，`color-scheme` 固定为 **`only light`**（CSS 和 `<meta>` 各一处）。**光写 `light` 不够**：浏览器的「网页自动暗色」（Chrome 的 Auto Dark Mode）会把浅色页面照样变黑，实测背景从 `(244,242,236)` 变成 `(18,18,18)`；`only light` 是明确拒绝被强制变暗，同样的强制暗色下背景保持浅色。有测试守着：样式里不能再有暗色媒体查询，英雄区、页面、导航、卡片、速览的底色亮度都要够高，不能出现深底专用的半透明白。以后若要再加暗色，应作为用户可选的开关，而不是自动跟随系统。支持 `prefers-reduced-motion`；键盘焦点有可见轮廓（3px 蓝）；吸顶导航在手机上可横向滑动；触控目标（`.seen`、`.buy`、导航按钮）高度不小于 44px；锚点跳转留出 76px，不被吸顶导航盖住。
- 手机优先（通知会在手机上点开），**文字不小于 11.5px**。零外部依赖：字体用系统字体，图标是内联 SVG，没有任何外部请求。

**对比度由测试守着（WCAG AA，正文 4.5、大字 3）：** 每个品牌色与其 `--on-*` 各校验一次；**样式规则**里凡是以品牌色做底色的，必须同时用配套的文字色，品牌底色不能直接当文字色（只查令牌不查规则，把 `.stat.must` 的字改成白色测试照样全绿——评审时用缺陷注入发现的）；七个类别色相的文字对卡片底色、对自己的淡底都要 ≥4.5，链接对淡底 ≥4.5。

**「我已经看过」（2026-10-04）**

- 每张**重点推荐和可以看**的卡片一个按钮（跳过、未能评估的没有）；点一下标记，再点撤销。标记后：速览行标题加删除线并换空心圆点、卡片左边条变灰、海报转灰度、出现绿色「✓ 已看过」角标，导航里出现「隐藏已看过 N」开关。
- **状态只存在这台设备的浏览器里**（`localStorage`，键 `film-radar:seen:v1`，按 `film_id` 记，所以同一部片出现在别的期也认得；开关状态键 `film-radar:hide-seen:v1`）。**换设备、换浏览器或清缓存就没了，也不会反馈给推荐流水线**（下一期仍可能推荐你看过的片）。要做到跨设备或反馈给流水线，需要一个服务端存储（比如仓库里的一份名单），这个设计没有做。
- 脚本是 `render.py` 里的常量 `SEEN_SCRIPT`，所有页面共用，**不拼任何页面数据**；按钮和开关默认带 `hidden`，只有脚本能让它们出现，没有脚本就没有死按钮。
- **内存为准，存储只负责持久化**：存储读不了、写不了（配额满、无痕模式）时，这次访问里照常能标记和切换（评审时用真实 Chrome 复现了两种失灵，各有测试）。数据损坏（不是合法 JSON）当作「没看过」，下一次点击写回合法 JSON。多个标签页之间用 `storage` 事件同步（含 `clear()`），页面从后退缓存恢复时重读存储。
- **无障碍**：按钮的无障碍名称固定为「我已经看过」，状态只由 `aria-pressed` 表达；每次标记或撤销通过 `role="status"` 的播报区读出「已把「片名」标为已看过」；在「隐藏已看过」开启时标记一部片，卡片会消失，焦点移到开关上而不是掉到 `body`；上次留下的「隐藏」偏好不会让这一页**第一部**被标记的片立刻消失。
- **有意接受的两个取舍：** ①脚本在 `</body>` 前执行，**慢速网络下会先闪一下**已看过的片再收起（实测：把 112KB 的页面分两段发、间隔 1.5 秒才复现；正常加载几乎看不出）。要根治得在 `<head>` 里再放一小段读存储、按 id 注入隐藏样式的脚本，复杂度不值。②「隐藏已看过」之后，章节标题和导航里的计数不变（例如「重点推荐 1」下面一张卡片都不显示）；这是用户自己打开的开关，导航里的开关写着「显示已看过」。

**改版时被测试钉住、以后改版也不能破坏的约定：** 每部片的 `data-film` 在整页只出现一次（速览用 `id="film-N"` 锚点和 `data-fid`，不用 `data-film`；按钮用 `data-seen`）；`<img` 总数就是有海报的片数（速览里不放缩略图）；章节按**首次出现的位置**排序，所以导航和统计里不能提前出现「本期未能评估」「往期」「跳过的片」这些字样；过期提示靠 `hidden` 属性，样式里必须有 `[hidden]{display:none!important}`；**往期页没有过期提示脚本，但有「我已经看过」的脚本**；`_STYLE_BASE` 是原始字符串（`r"""`），否则 CSS 的 `\2713`、`\2212` 会被 Python 当成八进制，「已看过」角标会变成「¹3 已看过」、展开后的符号会变成「2」（上一版就是这样坏的，评审时发现）。

**安全**：所有来自模型和 Cineplex 的文本做 HTML 转义后再写入页面；链接只接受 `http`/`https` 协议。Issue 的标题和正文里，`@` 后面插一个零宽空格，避免模型写的文字通知到不相干的 GitHub 用户。

**海报**：片单里约四成的片没有海报（实测 258 条里 97 条为空）。没有海报或海报地址失效时显示按类别着色、带片框图标的占位块，不显示破图标。

**产物**：`site/index.html`（最新一期）、`site/editions/<id>.html`（每期一页）。

## 12. 调度、发布与通知（`.github/workflows/edition.yml`）

**触发：**

- 定时：每周四 11:00 UTC（多伦多 7:00 夏令时 / 6:00 冬令时），赶在周五新片上映之前。
- 手动：`workflow_dispatch`，随时可重跑。

**双周门控**：GitHub 的定时语法表达不了"每两周"。`main.py` 用配置里的 `anchor_date`（2026-10-08，周四）计算 `(运行日期 − anchor_date).days // 7 % 2`，为 0 才执行，否则正常退出、在日志里说明是跳过周，并通过步骤输出让后面的提交、部署、开 Issue 步骤一并跳过。按距离锚点的天数算，跨年不会错位。手动触发不受门控限制。

**步骤：**

1. 检出仓库，装 Python 3.11 与依赖。
2. 运行流水线，生成当期 edition。
3. 把 `data/editions` 与 `out/` 备份成产物（保留 14 天），再提交 `data/editions/<id>.json`。备份在前：这一期花了几块钱，只存在临时机器上，推送、部署、开 Issue 任何一步失败，数据都还能手工提交。推送前先 `pull --rebase`，最多三次，因为跑一期要十几分钟，期间 `main` 可能有别的提交。
4. 构建 `site/` 并部署到 GitHub Pages。
5. 开 Issue：标题为"第 N 期 M/D：片名一、片名二、片名三"（没有重点推荐时写明"本期没有重点推荐"），正文每部重点推荐一行（片名、一句话定位、状态）加页面链接，标签 `edition`。
6. 把用量与各去向数量写进 Actions 运行摘要。

**失败时**：流水线任一步失败则后续步骤不执行，已发布的页面保持不变。末尾有一个仅在失败时执行的步骤，开一个标签为 `failure` 的 Issue，写明失败环节与运行日志链接。**失败环节按各步骤的实际结果写**，不只看 `out/failure.txt` 在不在：流水线失败（读 `failure.txt`）、环境准备失败、推送被拒、页面部署失败、页面已更新但通知 Issue 没开成，是五种不同的处境，措辞不同（尤其最后一种，页面其实已经更新了，不能写「页面没有被改动」）。

`edition` 与 `failure` 两个标签在建仓库时创建一次。

**诊断工作流（只能手动触发；不提交、不部署、不开 Issue，不属于流水线）：** `probe.yml`（探针：Cineplex 抓取与 Claude 联网搜索是否可用；`notify` 开关打开才会开测试 Issue）；`triage-compare.yml`（同一份候选让各模型各跑几次粗筛，比较入围名单的稳定性，见第 8 节；每次约 $0.1（Sonnet）/ $0.2（Opus））；`research-compare.yml`（同一部片用不同的搜索调用方式与提示词各跑一次精评，见第 9 节「搜索额度」；默认 3 部片 × 4 种配置约 $3）。结果以 artifact 保存。

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
- 费用估算 = token 部分 + 搜索部分。**粗筛与精评的 token 各按各自模型的单价算**，单价写在配置里（精评 `claude-sonnet-5-5`：输入每百万 token 2 美元，输出 10 美元；粗筛 `claude-opus-5-5`：4 / 20 美元；首期两个阶段都是 Opus，4 / 20 美元）。**联网搜索每千次 10 美元（Anthropic 文档 2026-10-04 核实，返回错误的搜索不计费）**，配置项 `search_price_per_search = 0.01`；代码按搜索请求次数折算，包含了出错的次数，所以搜索费是上限。2026-10-04 之前的期没有搜索费字段，页脚仍写「不含搜索费」。实际花费以 Anthropic 控制台账单为准。
- **首期实测（2026-10-03，70 部候选、15 部入围）：** 32 次模型调用（粗筛 2 次，其中 1 次是漏判重试；精评 15 部 × 2 次），输入 1,684,232 / 输出 88,449 token，联网搜索 75 次；token 费用估算 **$8.51**（不含搜索费，搜索单价没有核实过，以账单为准）。设计阶段估的是每期 2–5 美元，实际 token 部分就已是估算上限的 1.7 倍，加上搜索费更高。每部入围片的精评平均约 11 万输入 token，主要是联网搜索结果灌进上下文。每期约 $8.5 以上、每两周一次，是否调整 `shortlist_cap` / `search_max_uses` 由用户决定，代码没有改。　**补：** 搜索 75 次按每千次 10 美元折算约 $0.75，首期总估算约 $9.26（这是折算，不是账单）。
- **2026-10-03 起精评改用 `claude-sonnet-5-5`**（用户嫌首期费用太高），单价正好是 Opus 5.5 的一半。**实测见下面两条**：全 Sonnet 版 token $3.29、搜索默认调用时精评质量明显变差（第 9 节「搜索额度」），修掉后加上 Opus 粗筛整期 $2.88。输入 token 占了费用的大头（首期 168 万输入 vs 8.8 万输出），要再降主要看 `search_max_uses` 与 `shortlist_cap`，不是 `effort`。
- **2026-10-04 整期实测（粗筛 Opus 5.5 + 精评 Sonnet 5.5 + 搜索直接调用并写明预算，2026-10-04 第二次运行覆盖了当天第一版）：** 31 次调用，输入 857,973 / 输出 65,771 token，联网搜索 40 次；估算 **$2.88**（token $2.48 + 搜索 ≤ $0.40）。对照同日第一版（全 Sonnet、搜索默认调用）：输入 1,302,408 / 输出 68,262，搜索 74 次，token $3.29，加搜索折算 ≤ $0.74 约 $4.03；首期全 Opus 为 $8.51 + 搜索 ≤ $0.75 约 $9.26。重点推荐 6 / 2 / 4（首期 / 全 Sonnet / 本版）。**同一个 Opus 粗筛这次把 Atonement 排除了**（`rank` 为空，理由「名额有限」），而之前对比实验里它 4 次都入选：名额边缘的片在同一模型内也会翻，第 8 节关于「第 10–20 名是抛硬币」的结论再次得到印证。若要稳定，只有粗筛多跑几次取多数一票（每期约 +$0.4），尚未做。这些数字都是代码折算的估算，实际花费以 Anthropic 控制台账单为准。
- **未决事项（未排期，触发条件=用户提出）：** ①是否调整 `shortlist_cap` / `search_max_uses`（现在输入 token 约 86 万，费用杠杆已小很多）；②收紧卡片里「没查到」这类否定断言的写法（首期 Opus 版 15 张卡里 4 张有错误的否定断言，现在的提示词没有约束）；③粗筛跑 3 次取多数票，稳定名额边缘（每期约 +$0.4）；④口味档案「犯罪」一类只有一句话，没有正反例；⑤「我已经看过」跨设备、并让流水线不再推荐看过的片（需要仓库里的服务端名单，第 11 节）。

## 15. 配置（`config/settings.toml`）

| 键 | 默认值 | 含义 |
|---|---|---|
| `home_lat` / `home_lon` | 43.6532 / −79.3832 | GTA 中心点（多伦多市中心） |
| `radius_km` | 40 | GTA 半径。实测覆盖 22 家影院，含 Markham、Richmond Hill、Mississauga |
| `showtime_days` | 14 | 排片查询天数。不得小于两期间隔，否则零星放映的片会落进盲区（见第 5 节） |
| `coming_soon_days` | 14 | 即将上映窗口 |
| `non_film_categories` | `Opera`、`Concert`、`Stage`、`Stage Performance`、`Television Event`、`Sport` | 活动场里要过滤的类别。只对 `isEvent` 为真的条目生效 |
| `shortlist_cap` | 15 | 精评名额 |
| `must_cap` | 6 | 重点推荐上限 |
| `outside_cap` | 2 | 口味之外名额 |
| `search_max_uses` | 5 | 每片搜索次数上限 |
| `anchor_date` | 2026-10-08 | 双周门控锚点 |
| `stale_after_days` | 16 | 页面过期提示阈值 |
| `model` | `claude-sonnet-5-5` | 精评模型（首期是 `claude-opus-5-5`） |
| `triage_model` | `claude-opus-5-5` | 粗筛模型。粗筛便宜却决定哪 15 部进入精评，所以用更强的 |
| `price_input_per_mtok` / `price_output_per_mtok` | 2.00 / 10.00 | 精评的 token 单价（美元）。**换模型时必须同步改**，否则页脚的费用数字是错的 |
| `triage_price_input_per_mtok` / `triage_price_output_per_mtok` | 4.00 / 20.00 | 粗筛的 token 单价，同上 |
| `search_price_per_search` | 0.01 | 联网搜索单价（美元 / 次），每千次 10 美元。按搜索请求次数折算，出错的搜索不计费，所以是上限 |
| `timezone` | `America/Toronto` | 期号与日期计算所用时区 |
| `page_url` | `https://akasha-r.github.io/film-radar/` | 写进 Issue 正文的页面地址 |

## 16. 测试策略

- 测试不访问真实网络与 API。Claude 调用与 HTTP 请求全部 mock。
- **Cineplex 测试数据用真实响应裁剪**，不手写。实施的第一步就是抓一份真实响应存为 fixture。
- `candidates`：表驱动测试。第 14 天与第 15 天的边界；半径边界；多版本合并及排片并入；预售中的未上映片；`hurry` 的两个阈值。
- 活动过滤单列，用附录 A 的真实条目做用例：歌剧与演唱会被过滤并进入 `filtered_events`；动画重映（`Ninja Scroll 4K`）、活动场恐怖片（`Fresh Meat`）保留为候选；类别不在排除名单里的未知活动保留；非活动的 `Sport` 类片不受影响；英配与日语原声两个版本合并后 `versions` 里两种语言都在、`is_event` 为真。
- `triage`：截断、拒答、未知 id、漏判后重试成功、漏判后重试仍缺、入围超额。
- `review`：第 9 节每一种失败判定各一条；白名单对 `sources`、`scores`、`title_zh` 的处理；搜索错误对象的判别。
- `assemble`：三条名额与降档规则；新旧标记；总数核对在人为制造不一致时抛异常。
- `render`：每部候选在页面上恰好出现一次；`review_failed` 区在有失败时出现；模型文本里的 HTML 被转义；过期提示脚本存在。另有：**对比度测试**（令牌、样式规则、七个类别色相）、**大块底色都是浅色的测试**；**真实浏览器端到端测试**（headless Chrome，走本机 http 服务；预置 `localStorage`、点击、读回状态，覆盖存储损坏、读不了、写不了、跨标签页与后退缓存同步、隐藏开关与焦点、播报文字、伪元素文字）。浏览器测试需要本机装有 Chrome，没有就跳过；`--dump-dom` 打印完不会自己退出，测试辅助函数读到 `</html>` 就杀掉整个进程组。
- `main`：双周门控的奇偶周与跨年；第 13 节每一行失败模式的退出码；启动时校验 `showtime_days` 不小于 14，小于则拒绝运行（这条约束横跨配置与调度两处，靠文字约定守不住）。
- 排片窗口单列一条用例：一部只在第 10 天有一场的在映片必须成为候选。
- **护栏验红**：每条护栏写完后注入一次对应的缺陷，确认测试变红。测不红的护栏不算完成。
- **端到端**：收尾前在 Actions 上手动触发一次真实运行，人工检查渲染出的页面（桌面与手机两种宽度），并确认通知到达。

## 17. 必须先验证的前提

以下前提不成立会改变架构，放在实施计划最前面，验证通过才继续。

| # | 前提 | 当前状态 | 不成立时的退路 |
|---|---|---|---|
| 1 | GitHub Actions 的机房 IP 能访问 Cineplex 网站与接口 | **已验证（2026-10-03，任务 4 闸门 A）**：Actions 上片单 258、影院 152、可订票日期 92，与本机一致 | 抓取改在本机 launchd 执行，把原始数据推到仓库，由 Actions 接手后半段 |
| 2 | Actions 机器人开的 Issue 会给仓库所有者发邮件与 App 推送 | **已验证（2026-10-03，任务 4 闸门 C）**：用户确认收到 | 改用邮件直发，或在 Issue 里 @ 用户 |
| 3 | 用户的 GitHub 套餐允许公开仓库使用 Pages 与定时 Actions | **私有仓库的 Pages 已实测不支持**：`POST /repos/AKASHA-R/film-radar/pages` 返回 422「Your current plan does not support GitHub Pages for this repository」。**公开仓库已验证**：同一条命令返回 `workflow https://akasha-r.github.io/film-radar/`。**手动触发的完整运行已验证**（2026-10-03，首期成功，页面部署、Issue 到达）；**定时触发（每周四 11:00 UTC）尚未验证**，第一次是 2026-10-08 | 无需退路。Step 4a 若对公开仓库也返回套餐类错误，停下来报告用户 |
| 4 | 联网搜索与结构化输出可在同一请求中使用 | **不再需要验证**：直接采用两次调用（第 9 节） | — |
| 6 | `llm.py` 的请求形状（流式、结构化输出、拒答回退 beta、联网搜索工具）在真实 API 上可用 | **已验证（2026-10-03，任务 4 闸门 B）**：结构化输出与联网搜索都 `end_turn`；`thinking`、`output_config`、`betas`、`fallbacks` 参数 API 都接受。**只验证了探针里的两个简单 schema**，粗筛与卡片的真实 schema（含 `anyOf` 可空、整数 `enum`）在任务 11 首跑才第一次过真实 API | 首跑若返回 400，按报错改 schema |
| 7 | 联网搜索的真实响应里，结果网址落在工具结果块或引用里 | **已验证（2026-10-03，任务 4）**：网址落在 `web_search_tool_result` 块里；text 块的 `citations` 为空，白名单只能靠搜索结果块。同时发现代码执行结果块不能收，见第 9 节 | 真实响应已存为 `tests/fixtures/claude/research.json` |
| 5 | 联网搜索对新片、华语片能搜到足够的评论 | **已验证，基本成立（2026-10-03 首期）**：华语/日语 6 部里 4 部 `evidence` 为 `ample`、1 部 `thin`（Keep Real，10 月 16 日才上映）、1 部 `none`（V，10 月 9 日上映，只查到影院简介）。还没上映的片评论少是预期内的 | `evidence` 机制已覆盖评论稀少的情况；若普遍稀少，需重新评估精评的价值 |

已实测通过的前提见附录 A。

## 18. 风险

- **Cineplex 接口随时可能失效。** 非官方用法，无法根治。能做到的是失效时明确报错而不是出空页。若频繁失效，需要重新考虑数据源。
- **防编造的边界。** 程序只保证声明有来源，不保证声明与来源一致。页面以"带来源的链接"呈现并在页脚提示。
  **首期实测（2026-10-03）：** 派 15 个独立核查员对 15 张推荐卡逐条核对，全部确实是在讲这部片。41 条评分里 34 条与来源页一致，1 条轻微漂移（豆瓣 8.7，页面现为 8.6），1 条数字对但来源页里没有（Dear You 的豆瓣 9.3），5 条因来源打不开无法核对；9 个中文片名里能查的全部正确。
  **真正的问题是错误的"没查到"：** 15 张卡里 4 张含有这类断言，而它引用的来源里其实有。Obsession 写"只查到入围、没查到获奖"，它引用的维基百科列了 Sitges 评审团特别奖等一串奖；Resident Evil 写"没有电影节记录"，实际在 Fantastic Fest 首映；Keep Real 写"导演以前的作品没查到"，实际他导过 26 亿票房的《这个杀手不太冷静》；Atonement 写"烂番茄、Metacritic 都没有分数"，它引用的烂番茄页面显示 89%。另有 Dear You 的出品公司名写错一个（"宇光影业"查无此名）。白名单只验证"有来源"，验证不了"没查到"这种否定断言。提示词对此没有约束，是否收紧留给用户决定。
- **两周一次的残余漏洞。** 临时加映且放映不满两周的片可能在两期之间出现又消失。改为每周运行可消除，成本翻倍。
- **`hurry` 是启发式。** 可能把一次性的经典重映也标为"抓紧"，页面已注明为推断。
- **活动过滤靠 Cineplex 的类别标签。** 一部电影如果被 Cineplex 错标了 `Concert` 之类的类别，会被过滤。对策是过滤清单在页面上可见，以及排除名单写在配置里可以随时调。反方向的代价是：没见过的活动类别会放行进粗筛，多花一点 token。
- **限定放映的片仍可能赶不上。** 活动场常常只放一两天。排片窗口与两期间隔对齐后，已公布排片的场次不会漏；漏的只剩一种：排片在上一期之后才公布、又在下一期之前放完。实测可订票日期能看到 12 天以上，活动场通常提前数周挂出（`Dive in Wonderland` 提前六周已在片单里），所以这种情况应当少见，但没有数据能证明它不发生。改为每周运行可消除。
- **公开仓库。** 源码、口味档案、每期推荐页与 `data/editions/` 里的数据都公开可见，git 提交里的作者姓名与邮箱也随历史公开。页面网址是 `akasha-r.github.io/film-radar/`，不带随机串。若将来要私密，GitHub Pages 做不到（私有访问控制只有 Enterprise Cloud 才有），需要换托管方式，本设计没有覆盖。

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

**写实施计划时补充的实测（2026-10-03）**

- `/v1/showtimes` 查一个没有排片的日期：返回 **HTTP 204、响应体为空**，不是空数组。
- `/v1/showtimes` 不带 `filmId` 时会包含活动场影片；但其中每部片的 `isEvent` 不可信（`Ninja Scroll 4K` 两个版本在片单里是 `true`，在排片里都是 `false`）。排片里出现的 id 全部能在片单里找到。
- `/v1/dates/bookable` 对影院 7130 返回 92 个日期，最远到 2027-06-26，且中间有空档。未来 14 天全部可订票。所以必须与排片窗口取交集，不能直接全查。
- 片单 258 条里，24 个字段每条都有；类型不稳定的只有三个海报字段，97 条为 `null`。`releaseDate` 一律是 `YYYY-MM-DDT00:00:00`。只有 62 条带安省分级。
- 首页的脚本标签 `src` 是绝对地址，形如 `https://www.cineplex.com/next-static-files/_next/static/chunks/….js`，共 15 个。
- 40 公里边界：`Cineplex Odeon Ajax Cinemas` 37801.9 米在内，`Cineplex Odeon Aurora Cinemas` 40002.2 米在外。
