# film-radar

每两周看一遍 Cineplex 在大多伦多地区放什么，挑出对我口味的，写成一页中文推荐。

页面：https://akasha-r.github.io/film-radar/

## 它做什么

```
cineplex      运行时取密钥；片单、GTA 影院、未来 14 天排片、单片详情
   ↓
candidates    程序过滤：去掉歌剧演唱会，合并配音版，留 GTA 有排片或 14 天内上映的
   ↓
triage        Claude 一次调用，只看元数据，逐片给去留
   ↓
review        Claude 逐片联网查证，写推荐卡片
   ↓
assemble      程序规则：名额、降档、新旧标记、总数核对
   ↓
render        静态 HTML
```

每周四早上在 GitHub Actions 上触发，隔周真正运行一次。跑完部署到 GitHub Pages，并开一个 Issue，标题就是这一期的重点推荐。

每一部进入候选的片都能在页面上找到去向：重点推荐、可以看、跳过，或者"本期未能评估"。没有哪部是被悄悄丢掉的。

## 调口味

改 `config/taste_profile.md`，提交，推送。下一期生效。这个文件原样喂给模型，只写口味，不要写别的。

## 调参数

`config/settings.toml`。半径、名额上限、要过滤的活动类别都在里面。

`showtime_days` 不能小于 14：排片窗口比两期间隔短的话，只放一两场的片会两期都查不到。

## 手动跑一期

GitHub 仓库的 Actions 页面 → edition → Run workflow。或者：

```bash
gh workflow run edition.yml
```

手动触发不受隔周限制。同一天重跑会覆盖当天那一期。

## 本地开发

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q
```

测试不访问网络，也不调 Claude。本机不需要配 API 密钥。

只想改页面样式时，不用重跑流水线：

```bash
.venv/bin/python -m film_radar.main build-site
open site/index.html
```

## 出了问题

运行失败时会开一个带 `failure` 标签的 Issue，写明失败在哪个环节。失败时已发布的页面不会被改动；页面超过 16 天没更新会自己在顶部提示过期。

最可能坏的地方是 Cineplex 抓取。Cineplex 没有公开 API，这里用的是它网站前端自带的订阅密钥，属于非官方用法，它改版就会断。先在 Actions 里手动跑 `probe` 工作流，看报告里 `cineplex` 那一半报什么错，再对照 `tests/fixtures/cineplex/README.md` 里记录的接口形状去查。

流水线跑成功、但后面的推送 / 部署 / 开 Issue 失败时，这一期的数据在那次运行的 `edition-backup` 产物里（Actions 运行页面底部，保留 14 天），可以手工提交，不用再付一次钱重跑。

重跑请用 Run workflow（手动触发）。在运行页面点 Re-run 会沿用原来的触发类型：一次失败的定时运行，如果在跳过周被重跑，会被当成跳过周，什么也不做。

## 费用

粗筛（便宜、关键）用 Opus，精评（量大）用 Sonnet，模型与单价都在 `config/settings.toml`，换模型时单价要一起改。每期的 `models` 字段记下当时各阶段用的模型。

每期的模型调用次数、token 数、搜索次数写在页脚和 Actions 的运行摘要里。页面上的美元数 = token 费用 + 联网搜索费（每千次 10 美元，按搜索请求次数折算，出错的搜索不计费，所以是上限），实际花费以 Anthropic 控制台账单为准。2026-10-04 之前的期没有搜索费这一项，页脚仍写「不含搜索费」。

精评的联网搜索用直接调用并在提示词里写明搜索预算：默认的动态过滤会让模型在代码里批量搜索，用光 `search_max_uses` 后误以为「联网搜索失败」而扔掉已查到的结果。实测与取舍见 spec 第 9 节「搜索额度」。

## 文档

- 设计：`docs/superpowers/specs/2026-10-03-film-radar-design.md`
- 实施计划：`docs/superpowers/plans/2026-10-03-film-radar.md`
