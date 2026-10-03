# Cineplex 测试数据

2026-10-03 从 Cineplex 真实接口抓取后裁剪。**每条记录保留全部字段，只减少条数**，不手写、不改字段。测试里需要变体时，在测试代码里复制一条真实记录再改单个字段。

| 文件 | 来源 | 裁剪方式 |
|---|---|---|
| `movies_v2.json` | `GET /v2/movies?language=en`（原 258 条） | 留 29 条，覆盖：普通在映片、配音版与原版、活动场电影、歌剧/演唱会/舞台剧/电视活动、华语片、日语片、类型为空的片 |
| `theatres.json` | `GET /v1/theatres?...&latitude=43.6532&longitude=-79.3832&range=30`（原 152 家） | 最近 10 家全留；其余留 60 公里内全部，外加最远的 3 家 |
| `showtimes_7130_2026-10-04.json` | `GET /v1/showtimes?...&locationId=7130&date=10/04/2026`（原 17 部） | 留 5 部，每部只留第一种放映规格的第一场 |
| `dates_bookable_7130.json` | `GET /v1/dates/bookable?...&locationId=7130` | 未裁剪，92 天 |
| `movie_detail_digger.html` | `https://www.cineplex.com/movie/digger` | 只留 `__NEXT_DATA__` 脚本标签，其中只留 `props.pageProps.movieDetails`；竞赛条款正文截到 200 字符 |
| `homepage.html` | `https://www.cineplex.com/` | 只留 15 个 `_next/static` 脚本标签，原样 |
| `chunk_theatrical.js` | 首页引用的 `chunks/1401-*.js` | 密钥所在语句前后各两百多字符 |
| `chunk_banner.js` | 首页引用的 `chunks/pages/_app-*.js` | 同上，另一把密钥所在的语句 |

**两份 `chunk_*.js` 里的订阅密钥已替换为假值**（`0123456789abcdef0123456789abcdef` 与 `fedcba9876543210fedcba9876543210`）。真实密钥不进仓库。

## 抓取时观察到、但没有对应文件的行为

- 查询一个没有排片的日期，`/v1/showtimes` 返回 **HTTP 204、响应体为空**，不是空数组。
- `/v1/showtimes` 里每部片的 `isEvent` **不可信**：`Ninja Scroll 4K` 在片单里是 `true`，在排片里是 `false`。是否活动场一律以片单为准。
- 不带 `filmId` 的排片查询会包含活动场影片。
- 片单里 258 条有 97 条的三个海报字段是 `null`，其余 21 个字段类型稳定。
- 只有 62 条带安省（`ON`）分级。

## 测试约定的运行日期

用这批数据的测试一律以 **2026-10-03** 为运行日期，这样片单里的 `isNowPlaying` / `isComingSoon` 与日期是自洽的。
