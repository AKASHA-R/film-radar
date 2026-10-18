# 「已看过」名单（watched）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal：** 把「已看过」从浏览器 `localStorage` 搬进仓库里的 `data/watched.json`：用户在 edition Issue 里打勾标记，同步工作流几分钟内把名单、所有 edition Issue、页面对齐，下一期粗筛前排除看过的片。

**Architecture：** 新模块 `watched.py`（纯函数：名单读写与匹配、Issue 任务项的格式与解析、同步算法、改写合并）和 `github.py`（整个项目唯一碰 GitHub 网络的地方）。`main.py` 新增三个子命令 `sync-watched`、`apply-watched-rewrites`、`migrate-issues`；出刊运行在内存里算「有效名单」，只读不写。新工作流 `watched-sync.yml` 串行同步、先提交名单再改写 Issue、每次都部署页面；`edition.yml` 不再部署页面，提交新一期后触发同步。

**Tech Stack：** Python 3.11、requests、pytest、PyYAML（只在测试里用）、GitHub Actions、GitHub REST API、gh CLI。

**Spec：** `docs/superpowers/specs/2026-10-17-watched-list-design.md`（下文「spec 第 N 节」都指它）。执行者两份都要读。

**谁来做：** 任务 1（闸门）和任务 14（上线）由控制者和用户一起做，不派子代理，每个对外动作（推 main、开/改/删 Issue、触发工作流）之前都要用户当场确认。任务 2–13 可以派子代理，子代理一律同步执行、不要后台等通知。

## Global Constraints

- 解释器只用 worktree 自己的 `.venv/bin/python`（任务 2 建）。**不要用** `/Users/minggao/Projects/film-radar/.venv`：它以可编辑方式装的是主仓库的 `src`。
- 所有命令在 `/Users/minggao/Projects/film-radar-watched` 下执行（`git -C` 或绝对路径），分支 `feat/watched`。
- 测试：`.venv/bin/python -m pytest -q`。测试不访问网络、不调 Claude、不碰 GitHub；GitHub 一律用 `helpers.FakeGitHub` 替身。`tests/conftest.py` 自动清掉 `GITHUB_TOKEN`、`GH_TOKEN`、`GITHUB_REPOSITORY`，漏了替身的测试会以「没有令牌」失败，而不是去改真 Issue。
- 命名：新概念一律叫 **`watched`**（用户看过）。已有的 `seen_before`（上一期也推荐过，决定「新」徽标）及其逻辑不改。
- 名单文件格式（spec 第 3 节，逐字照抄）：`{"version": 1, "films": {"<主编号>": {"title": ..., "since": ..., "ids": [...]}}}`；键是数字字符串，加载后键和 `ids` 都是整数；写出用 `json.dumps(..., ensure_ascii=False, indent=1, sort_keys=True) + "\n"`。文件不存在＝空名单；**格式不对抛 `WatchedError`，绝不当成空名单。**
- Issue 格式（spec 第 4 节，逐字照抄）：第一行 `<!-- film-radar:edition <YYYY-MM-DD> -->`；任务项 `- [ ] **片名** · 状态：一句话 <!-- film:<编号> bot:<0|1> -->`；解析正则 `^- \[( |x|X)\] .*<!-- film:(\d+) bot:([01]) -->\s*$`；不用 `<details>`。
- **只有同步程序写 `data/watched.json`；出刊运行只读，永远不改 Issue。只有 `watched-sync.yml` 部署 Pages。**
- `_STYLE_BASE` 保持原始字符串（`r"""`）；页面始终 `color-scheme: only light`，不加 `prefers-color-scheme: dark`。
- 提交信息用中文，结尾一行 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。只在 `feat/watched` 上提交；推 main 只在任务 1、14 里、经用户确认后做。
- Cineplex 密钥、`ANTHROPIC_API_KEY`、GitHub 令牌都不写进任何文件或日志。本机要令牌时只用行内环境变量 `GH_TOKEN=$(gh auth token) ...`。
- 缺陷注入（验红）只用 `sh scripts/redcheck.sh <测试文件>`。注入前把要改的源文件复制到 `/private/tmp/claude-501/-Users-minggao/054a1f4c-79d3-45c1-b3ce-9c04c03ae112/scratchpad/`，验完复制回来，再 `git -C /Users/minggao/Projects/film-radar-watched diff --exit-code -- <文件>` 确认还原。**不要用 `git checkout` 还原**。

## Review Focus

spec 没写、但最可能坑到用户的五种输入。每条的测试已经加进负责的任务里：

1. **GitHub 网页编辑过的正文是 `\r\n` 换行。** 解析照常认出每一行，改写时 `\r\n` 原样保留（任务 3 `test_parse_accepts_uppercase_x_and_crlf`，任务 5 `test_a_rewrite_only_touches_the_checkbox_and_the_bot_digit`）。
2. **用户在第一行的 edition 标记上面加了一行字。** 这个 Issue 不能被当成「不是程序管理的」而静默忽略（那样里面的勾永远不生效，违背 spec 第 1 节成功标准 4），要按「无法解析」报告（任务 3 `test_text_inserted_above_the_marker_is_reported_not_ignored`）。只有既没有标记、也没有任何 `<!-- film:` 行的 Issue 才忽略。
3. **接口返回的正文是 `null`（用户把正文清空了）。** 当成空字符串，不崩（任务 6 `test_an_empty_body_comes_back_as_an_empty_string`；任务 3 `parse_issue` 对 `""` 返回 `None`）。
4. **老的期数据没有 `watched_showing` 字段。** 编号目录、Issue 正文、页面折叠区都按空列表处理（任务 3、4、8 各有测试）。
5. **出刊运行时某个 edition Issue 无法解析。** 跳过那个 Issue 里的勾、在日志里说明，出刊照常完成，不能因此失败而白花一期的钱，也不能在调用 Claude 之后才失败（任务 9 `test_cli_an_unparsable_issue_does_not_stop_the_edition`）。

---

## 文件结构

| 文件 | 职责 | 任务 |
|---|---|---|
| `src/film_radar/watched.py`（新） | 名单读写与匹配；Issue 任务项格式与解析；同步算法；改写合并。纯函数 | 2、3、4、5 |
| `src/film_radar/github.py`（新） | GitHub Issues REST 接口：列出 edition Issue、读正文、改正文 | 6 |
| `src/film_radar/settings.py`、`config/settings.toml` | 新增 `repo = "AKASHA-R/film-radar"` | 6 |
| `src/film_radar/render.py` | 新 Issue 正文；页面生成时画出已看过、去掉按钮、Issue 链接、「隐藏」开关脚本、「看过、仍在映」折叠区 | 3、7、8 |
| `src/film_radar/assemble.py` | edition 数据新增 `watched_showing` | 9 |
| `src/film_radar/main.py` | 出刊接入有效名单；`build-site` 读名单；三个新子命令 | 7、9、10、11 |
| `.github/workflows/watched-sync.yml`（新） | 同步与唯一的页面部署 | 12 |
| `.github/workflows/edition.yml` | 去掉 Pages 部署，提交后触发同步，新的失败措辞 | 12 |
| `scripts/open_issue_once.sh`（新） | 开带 `failure` 标签的 Issue，同标题还开着就不重复开 | 12 |
| `.github/workflows/watched-probe.yml`（新，只在 main 上，任务 14 删掉） | 闸门探针 | 1 |
| `tests/test_watched.py`、`tests/test_github.py`、`tests/test_sync_cli.py`、`tests/test_migrate_cli.py`、`tests/test_workflows.py`、`tests/test_open_issue_once.py`（新） | 对应模块的测试 | 2–12 |
| `tests/helpers.py`、`tests/conftest.py`、`tests/test_render.py`、`tests/test_main.py`、`tests/test_settings.py`、`tests/test_assemble.py` | 替身、构造函数、改动的测试 | 4、6、7、8、9 |
| 主设计、`CLAUDE.md`、`README.md` | 文档同步 | 13 |

---

### Task 1：闸门 G1–G6（控制者和用户一起做）

spec 第 12 节的前提只能实测。任何一条不成立，按「不成立时」处理后才能继续后面的任务。

**Files：**
- Create（只在 main 上）：`.github/workflows/watched-probe.yml`
- Modify（`feat/watched`）：`docs/superpowers/specs/2026-10-17-watched-list-design.md` 第 12 节末尾追加实测结果

**Interfaces：**
- Produces：spec 第 12 节「实测结果」小节。任务 3（Issue 尾注）、任务 12（G4 退路）按它决定。

- [ ] **Step 1：向用户请求确认。** 原话说明：要往 main 推一个探针工作流 `watched-probe.yml`（只读仓库内容，只改带 `probe` 标签的测试 Issue），会开一个测试 Issue（会收到一封通知邮件），中间需要用户在网页和手机上各勾几次、在 DevTools 里切一次离线。用户明确同意后再继续。

- [ ] **Step 2：在临时 worktree 里写探针。**

```bash
git -C /Users/minggao/Projects/film-radar-watched fetch origin
git -C /Users/minggao/Projects/film-radar-watched worktree add /Users/minggao/Projects/film-radar-probe -b watched-probe origin/main
```

写 `/Users/minggao/Projects/film-radar-probe/.github/workflows/watched-probe.yml`：

```yaml
name: watched-probe

# 「已看过」功能的前提探针（spec 2026-10-17 第 12 节 G1–G6）。验证完随功能分支合并时删掉。
on:
  issues:
    types: [edited]
  workflow_dispatch:
    inputs:
      step:
        description: "open：开测试 Issue；rewrite：以机器人身份勾上 film 那一行；dispatch：用 GITHUB_TOKEN 触发一次 noop；noop：什么都不做"
        type: choice
        options: [noop, open, rewrite, dispatch]
        default: noop
      issue:
        description: "测试 Issue 编号（rewrite 用）"
        default: ""
      film:
        description: "要勾上的假编号（rewrite 用），如 9000002"
        default: ""

permissions:
  contents: read
  issues: write
  actions: write

jobs:
  probe:
    runs-on: ubuntu-latest
    steps:
      - name: Record the event
        env:
          ISSUE_AUTHOR: ${{ github.event.issue.user.login }}
        run: echo "event=${{ github.event_name }} actor=${{ github.actor }} issue=${{ github.event.issue.number }} author=$ISSUE_AUTHOR step=${{ inputs.step }}"

      - name: Open a probe issue
        if: inputs.step == 'open'
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh label create probe --repo "${{ github.repository }}" --color ededed --description "前提探针，验证完删除" 2>/dev/null || true
          {
            echo "<!-- film-radar:probe -->"
            echo "前提探针（spec 2026-10-17 第 12 节），验证完删除。请按会话里的步骤操作。"
            echo
            for n in 1 2 3 4 5 6; do
              echo "- [ ] **Probe $n** · 在映第 1 周：第 $n 行 <!-- film:900000$n bot:0 -->"
            done
            echo
            echo "cc @${{ github.repository_owner }}"
          } > probe_body.md
          gh issue create --repo "${{ github.repository }}" --title "film-radar 已看过前提探针（验证完删除）" \
            --body-file probe_body.md --label probe

      - name: Rewrite one line as the bot
        if: inputs.step == 'rewrite'
        env:
          GH_TOKEN: ${{ github.token }}
          ISSUE: ${{ inputs.issue }}
          FILM: ${{ inputs.film }}
        run: |
          gh api "repos/${{ github.repository }}/issues/$ISSUE" --jq .body > body.md
          sed -i "s/^- \[ \] \(.*<!-- film:$FILM bot:\)0 -->/- [x] \11 -->/" body.md
          gh api -X PATCH "repos/${{ github.repository }}/issues/$ISSUE" -F "body=@body.md" --silent
          gh api "repos/${{ github.repository }}/issues/$ISSUE" --jq .body

      - name: Dispatch a noop run
        if: inputs.step == 'dispatch'
        env:
          GH_TOKEN: ${{ github.token }}
        run: gh workflow run watched-probe.yml --repo "${{ github.repository }}" --ref main -f step=noop
```

- [ ] **Step 3：提交并推到 main，删掉临时 worktree。**

```bash
git -C /Users/minggao/Projects/film-radar-probe add .github/workflows/watched-probe.yml
git -C /Users/minggao/Projects/film-radar-probe commit -m "ci: 已看过功能的前提探针（验证完删除）

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git -C /Users/minggao/Projects/film-radar-probe push origin watched-probe:main
git -C /Users/minggao/Projects/film-radar-watched worktree remove /Users/minggao/Projects/film-radar-probe
git -C /Users/minggao/Projects/film-radar-watched branch -D watched-probe
```

推送被拒（main 在这期间有了新提交）就 `git -C /Users/minggao/Projects/film-radar-probe pull --rebase origin main` 后再推。

- [ ] **Step 4：开测试 Issue，记下编号、作者和原始正文。**

```bash
gh workflow run watched-probe.yml --repo AKASHA-R/film-radar --ref main -f step=open
gh run list --repo AKASHA-R/film-radar --workflow watched-probe.yml --limit 1 --json databaseId,status,conclusion
gh issue list --repo AKASHA-R/film-radar --label probe --json number,title
gh api repos/AKASHA-R/film-radar/issues/N --jq .user.login
gh api repos/AKASHA-R/film-radar/issues/N --jq .body > /private/tmp/claude-501/-Users-minggao/054a1f4c-79d3-45c1-b3ce-9c04c03ae112/scratchpad/probe-0.md
```

（`N` 换成实际编号；运行要等 `status` 为 `completed`。）预期作者是 `github-actions[bot]`——任务 6 的客户端只认这个作者。

- [ ] **Step 5：G1、G5（网页）。** 请用户：在电脑浏览器打开 Issue #N，勾「Probe 1」；同时确认行尾的 HTML 注释看不见、勾选框能点。然后：

```bash
gh api repos/AKASHA-R/film-radar/issues/N --jq .body > /private/tmp/claude-501/-Users-minggao/054a1f4c-79d3-45c1-b3ce-9c04c03ae112/scratchpad/probe-1.md
diff /private/tmp/claude-501/-Users-minggao/054a1f4c-79d3-45c1-b3ce-9c04c03ae112/scratchpad/probe-0.md /private/tmp/claude-501/-Users-minggao/054a1f4c-79d3-45c1-b3ce-9c04c03ae112/scratchpad/probe-1.md
grep -c $'\r' /private/tmp/claude-501/-Users-minggao/054a1f4c-79d3-45c1-b3ce-9c04c03ae112/scratchpad/probe-1.md
gh run list --repo AKASHA-R/film-radar --workflow watched-probe.yml --event issues --limit 3 --json databaseId,createdAt
gh run view RUN_ID --repo AKASHA-R/film-radar --log | grep "event="
```

通过条件：diff 只有「Probe 1」那一行从 `[ ]` 变成 `[x]`，行尾注释原样；有一次 `issues` 事件的运行，日志里 `actor` 是仓库所有者。顺便记下正文有没有变成 `\r\n`（`grep -c` 大于 0 就是有）。

- [ ] **Step 6：G1b、G3（没刷新的网页）。** 请用户：打开 Issue #N，DevTools → Network → Offline。然后：

```bash
gh workflow run watched-probe.yml --repo AKASHA-R/film-radar --ref main -f step=rewrite -f issue=N -f film=9000002
gh run list --repo AKASHA-R/film-radar --workflow watched-probe.yml --limit 2 --json databaseId,status,event,createdAt
```

运行完成后，请用户：恢复在线，**不要刷新**，立刻勾「Probe 3」，并说出页面上有没有报错或提示。然后取回正文存为 `probe-2.md` 并判断：

| 「Probe 2」行 | 「Probe 3」行 | 结论 |
|---|---|---|
| `[x] … bot:1` | `[x]` | 按位置只改那一项 |
| `[ ] … bot:0`（被旧正文盖回） | `[x]` | 整份覆盖 |
| 任意 | `[ ]` | 拒绝（记下用户看到的提示） |

G3：rewrite 那次运行之后，`--event issues` 的运行列表里不应出现新的运行（机器人用 `GITHUB_TOKEN` 改正文不触发工作流）。

- [ ] **Step 7：G2、G5（手机）。** 请用户：在 GitHub 手机 App 里打开 Issue #N，勾「Probe 4」，并确认注释看不见。取回正文核对（同 Step 5）。然后请用户：在 App 里停在这个 Issue 上，打开飞行模式；控制者执行 `gh workflow run watched-probe.yml --repo AKASHA-R/film-radar --ref main -f step=rewrite -f issue=N -f film=9000005`，完成后请用户关掉飞行模式、**不要下拉刷新**、立刻勾「Probe 6」。取回正文，按 Step 6 的表判断。

- [ ] **Step 8：G4。**

```bash
gh workflow run watched-probe.yml --repo AKASHA-R/film-radar --ref main -f step=dispatch
gh run list --repo AKASHA-R/film-radar --workflow watched-probe.yml --event workflow_dispatch --limit 3 --json databaseId,createdAt,displayTitle
gh api repos/AKASHA-R/film-radar/actions/runs/RUN_ID --jq .triggering_actor.login
```

通过条件：dispatch 那次运行之后出现一次新的 `workflow_dispatch` 运行，触发者是 `github-actions[bot]`。

- [ ] **Step 9：G6。** 用 WebFetch 读 `https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/about-task-lists` 和 `https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/creating-an-issue`，找「谁能勾选别人开的 Issue 里的任务项 / 谁能编辑别人的 Issue 正文」的原文；问用户有没有第二个 GitHub 账号可以实测（有就请用户用它打开 Issue #N 看能不能勾）。记下原文出处。

- [ ] **Step 10：按结论处理。**

| 闸门 | 不成立时 |
|---|---|
| G1、G5、G6 | **停下来**告诉用户，设计要重新讨论（spec 第 12 节的退路都是改设计），后面的任务一个都不做 |
| G1b、G2 结论是「拒绝且有提示」 | 任务 3 Step 0 给 Issue 尾注加一句（那里写了原文） |
| G2 手机不能勾，或手机拒绝但不提示 | 任务 13 的 README 里写明（那里写了原文） |
| G3 会自触发 | **什么都不加。** 不照 spec 的退路加 `github.actor` 条件：被自触发的那次同步发现没有操作、没有改写，不会再改 Issue，自然收敛；加任务级条件反而会让它在并发组里顶掉一次真正的同步再跳过，丢掉那次部署（spec 第 7 节）。在结果里写明这个理由 |
| G4 | 任务 12 按「G4 不成立时」那一步改用 `workflow_run` |

- [ ] **Step 11：把实测结果写进 spec 并提交。** 在 spec 第 12 节表格之后追加：

```markdown
### 实测结果（2026-10-__）

| # | 结果 | 证据 | 结论 |
|---|---|---|---|
| G1 | （成立 / 不成立：一句话） | Issue #N，运行 RUN_ID | |
| G1b | 按位置修改 / 整份覆盖 / 拒绝（提示原文） | probe-2.md 的两行 | |
| G2 | | | |
| G3 | | | |
| G4 | | | |
| G5 | | | |
| G6 | | 文档原文与出处 | |

正文换行：网页勾选后（是 / 不是）`\r\n`。Issue 作者：`github-actions[bot]`。
```

把下划线和括号里的内容换成实测值，然后：

```bash
git -C /Users/minggao/Projects/film-radar-watched add docs/superpowers/specs/2026-10-17-watched-list-design.md
git -C /Users/minggao/Projects/film-radar-watched commit -m "docs: watched spec 记下闸门 G1–G6 实测结果

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 12：删除测试 Issue（先问用户）。** 删除不可恢复，只针对这个测试 Issue。用户同意后：`gh issue delete N --repo AKASHA-R/film-radar --yes`。`watched-probe.yml` 留在 main 上，任务 14 合并时删掉。

---

### Task 2：开发环境、名单读写与匹配

**Files：**
- Create：`src/film_radar/watched.py`
- Test：`tests/test_watched.py`

**Interfaces：**
- Produces（`film_radar.watched`）：
  - `class WatchedError(Exception)`
  - `load_watched(text: str | None) -> dict[int, dict]`；`load_watched_file(path: Path) -> dict[int, dict]`；`dump_watched(films: dict[int, dict]) -> str`
  - 条目形状 `{"title": str, "since": str, "ids": list[int]}`（`ids` 升序、去重）
  - `watched_ids(films) -> frozenset[int]`；`version_ids(film: dict) -> frozenset[int]`；`is_watched(film: dict, watched: frozenset[int]) -> bool`
  - `split_watched(candidates, watched) -> tuple[list[dict], list[dict]]`，第二项每条形状 `{"film_id", "title", "status", "release_date", "weeks_in_release", "detail_url", "version_ids"}`，按 `(title, film_id)` 排序

- [ ] **Step 1：建 worktree 自己的虚拟环境，跑基线。**

```bash
/opt/homebrew/bin/python3.11 -m venv /Users/minggao/Projects/film-radar-watched/.venv
/Users/minggao/Projects/film-radar-watched/.venv/bin/pip install -e '/Users/minggao/Projects/film-radar-watched[dev]'
cd /Users/minggao/Projects/film-radar-watched && .venv/bin/python -c "import film_radar; print(film_radar.__file__)"
cd /Users/minggao/Projects/film-radar-watched && .venv/bin/python -m pytest -q
```

预期：路径在 `film-radar-watched/src` 下；`347 passed`（数字不同就记下实际数字，报告给控制者）。

- [ ] **Step 2：写失败的测试。** 新建 `tests/test_watched.py`：

```python
import json

import pytest

from film_radar.watched import (
    WatchedError, dump_watched, is_watched, load_watched, load_watched_file, split_watched, version_ids, watched_ids,
)
from helpers import make_candidate

ENTRY = {"title": "潘神的迷宫", "since": "2026-10-17T14:03:00-04:00", "ids": [62050]}


def listing(films):
    return json.dumps({"version": 1, "films": films}, ensure_ascii=False)


# ---- 名单文件（spec 第 3 节）----

def test_a_missing_file_is_an_empty_list(tmp_path):
    assert load_watched(None) == {}
    assert load_watched_file(tmp_path / "watched.json") == {}


def test_keys_and_ids_become_integers_and_ids_are_sorted():
    films = load_watched(listing({"62050": {**ENTRY, "ids": [62252, 62050, 62050]}}))
    assert films == {62050: {**ENTRY, "ids": [62050, 62252]}}


@pytest.mark.parametrize("bad", [
    "", "{not json", "[]",
    json.dumps({"films": {}}), json.dumps({"version": 2, "films": {}}), json.dumps({"version": 1, "films": []}),
    listing({"abc": ENTRY}), listing({"６２": ENTRY}),
    listing({"62050": {"title": "x", "since": "y"}}), listing({"62050": {**ENTRY, "extra": 1}}),
    listing({"62050": {**ENTRY, "ids": []}}), listing({"62050": {**ENTRY, "ids": ["62050"]}}),
    listing({"62050": {**ENTRY, "ids": [1]}}), listing({"62050": {**ENTRY, "ids": [62050, True]}}),
    listing({"62050": {**ENTRY, "title": None}}),
])
def test_a_malformed_file_raises_instead_of_meaning_empty(bad):
    """当成空名单的话，同步会把所有 Issue 里的勾全部清掉。"""
    with pytest.raises(WatchedError):
        load_watched(bad)


def test_dump_is_stable_and_round_trips():
    films = {62050: dict(ENTRY), 100: {"title": "Z", "since": "s", "ids": [100]}}
    text = dump_watched(films)
    assert text == dump_watched(dict(reversed(list(films.items()))))
    assert load_watched(text) == films
    assert text.endswith("\n") and '\n "films": {' in text and "潘神的迷宫" in text


# ---- 匹配 ----

def test_watched_ids_is_the_union_of_every_entry():
    films = {1: {"title": "a", "since": "s", "ids": [1, 5]}, 2: {"title": "b", "since": "s", "ids": [2]}}
    assert watched_ids(films) == {1, 2, 5}


def test_a_film_is_watched_when_any_version_is_listed():
    versions = [{"film_id": 62050, "name": "A", "language": "English", "subtitle": ""},
                {"film_id": 62252, "name": "A (Spanish)", "language": "Spanish", "subtitle": ""}]
    candidate = make_candidate(62050, "A", versions=versions)
    assert version_ids(candidate) == {62050, 62252}
    assert is_watched(candidate, frozenset({62252}))
    assert not is_watched(candidate, frozenset({1}))


def test_version_ids_reads_watched_showing_entries_too():
    assert version_ids({"film_id": 7, "version_ids": [7, 8]}) == {7, 8}


def test_split_keeps_the_order_of_the_rest_and_sorts_watched_by_title():
    zeta, alpha, mid = make_candidate(1, "Zeta"), make_candidate(2, "Alpha"), make_candidate(3, "Mid")
    rest, showing = split_watched([zeta, alpha, mid], frozenset({1, 2}))
    assert rest == [mid]
    assert [e["title"] for e in showing] == ["Alpha", "Zeta"]
    assert showing[0] == {
        "film_id": 2, "title": "Alpha", "status": "now_playing", "release_date": "2026-10-02",
        "weeks_in_release": 1, "detail_url": "https://www.cineplex.com/movie/film-2", "version_ids": [2],
    }
```

- [ ] **Step 3：跑测试确认失败。**

Run：`.venv/bin/python -m pytest tests/test_watched.py -q`
Expected：FAIL，`ModuleNotFoundError: No module named 'film_radar.watched'`

- [ ] **Step 4：实现。** 新建 `src/film_radar/watched.py`：

```python
"""「已看过」名单（data/watched.json）与 edition Issue 勾选框之间的同步。纯函数，不碰网络。

名单是唯一的事实来源；Issue 里的勾选框是用户的操作入口。设计见
docs/superpowers/specs/2026-10-17-watched-list-design.md。

命名：这里的 watched 是「用户看过」。assemble.py 里的 seen_before 是「上一期也推荐过」，两回事。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

WATCHED_VERSION = 1
_ID = re.compile(r"[0-9]+")


class WatchedError(Exception):
    """名单文件格式不对。绝不能当成空名单：那样同步会把所有 Issue 里的勾全部清掉。"""


def load_watched(text: str | None) -> dict[int, dict]:
    """None（文件不存在）等于空名单。返回 {主编号: {"title", "since", "ids"}}，键和 ids 都是整数。"""
    if text is None:
        return {}
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise WatchedError(f"data/watched.json 不是合法的 JSON：{e}") from e
    if not isinstance(raw, dict) or raw.get("version") != WATCHED_VERSION or not isinstance(raw.get("films"), dict):
        raise WatchedError(f'data/watched.json 顶层必须是 {{"version": {WATCHED_VERSION}, "films": {{...}}}}')
    films = {}
    for key, entry in raw["films"].items():
        if not _ID.fullmatch(key):
            raise WatchedError(f"data/watched.json 的键必须是数字编号：{key!r}")
        if not isinstance(entry, dict) or set(entry) != {"title", "since", "ids"}:
            raise WatchedError(f"data/watched.json 的条目 {key} 必须正好有 title、since、ids 三个字段")
        ids = entry["ids"]
        if not (isinstance(entry["title"], str) and isinstance(entry["since"], str) and isinstance(ids, list)
                and ids and all(type(i) is int for i in ids) and int(key) in ids):
            raise WatchedError(f"data/watched.json 的条目 {key} 内容不对（ids 必须是非空整数列表，且包含 {key}）")
        films[int(key)] = {"title": entry["title"], "since": entry["since"], "ids": sorted(set(ids))}
    return films


def load_watched_file(path: Path) -> dict[int, dict]:
    return load_watched(path.read_text(encoding="utf-8") if path.exists() else None)


def dump_watched(films: dict[int, dict]) -> str:
    """写出格式固定（键排序、缩进 1），避免无意义的差异。"""
    data = {"version": WATCHED_VERSION, "films": {
        str(film_id): {"title": entry["title"], "since": entry["since"], "ids": sorted(entry["ids"])}
        for film_id, entry in films.items()
    }}
    return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def watched_ids(films: dict[int, dict]) -> frozenset[int]:
    return frozenset(i for entry in films.values() for i in entry["ids"])


def version_ids(film: dict) -> frozenset[int]:
    """一部片的所有编号：主编号加各版本编号。候选、一期里的片（versions）和「看过、仍在映」的条目（version_ids）都能用。"""
    if "version_ids" in film:
        return frozenset([film["film_id"], *film["version_ids"]])
    return frozenset([film["film_id"], *(v["film_id"] for v in film.get("versions", []))])


def is_watched(film: dict, watched: frozenset[int]) -> bool:
    """任一版本编号在名单里就算看过：版本集合在真实数据里会变（spec 第 3 节）。"""
    return not version_ids(film).isdisjoint(watched)


def split_watched(candidates: list[dict], watched: frozenset[int]) -> tuple[list[dict], list[dict]]:
    """把候选分成「继续评估」和「看过、仍在映」。后者只留页面和 Issue 要用的字段，按片名排序。"""
    rest, showing = [], []
    for candidate in candidates:
        (showing if is_watched(candidate, watched) else rest).append(candidate)
    entries = [{
        "film_id": c["film_id"], "title": c["title"], "status": c["status"], "release_date": c["release_date"],
        "weeks_in_release": c["weeks_in_release"], "detail_url": c["detail_url"],
        "version_ids": sorted(version_ids(c)),
    } for c in showing]
    return rest, sorted(entries, key=lambda e: (e["title"], e["film_id"]))
```

- [ ] **Step 5：跑测试确认通过。**

Run：`.venv/bin/python -m pytest tests/test_watched.py -q && .venv/bin/python -m pytest -q`
Expected：全部 PASS

- [ ] **Step 6：验红。** 把 `load_watched` 里 `except json.JSONDecodeError` 分支改成 `return {}`，`sh scripts/redcheck.sh tests/test_watched.py` 应当 FAIL（`test_a_malformed_file_raises_instead_of_meaning_empty`）；按 Global Constraints 的办法还原并确认 `git diff --exit-code`。

- [ ] **Step 7：提交。**

```bash
git -C /Users/minggao/Projects/film-radar-watched add src/film_radar/watched.py tests/test_watched.py
git -C /Users/minggao/Projects/film-radar-watched commit -m "feat: 已看过名单的读写与按版本匹配

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3：Issue 任务项格式、解析与新的 Issue 正文

**Files：**
- Modify：`src/film_radar/watched.py`（追加）、`src/film_radar/render.py`（`issue_body` 重写，新增 `_issue_text`、`_issue_line`、`ISSUE_HOWTO`）
- Test：`tests/test_watched.py`（追加）、`tests/test_render.py`（替换两个 `issue_body` 测试，新增几个）

**Interfaces：**
- Consumes：任务 2 的 `is_watched`
- Produces（`film_radar.watched`）：
  - `@dataclass(frozen=True) Issue(number: int, body: str)`
  - `@dataclass(frozen=True) Line(film_id: int, checked: bool, bot: bool)`
  - `@dataclass(frozen=True) ParsedIssue(number: int, edition_id: str, lines: tuple[Line, ...])`
  - `class IssueFormatError(Exception)`，属性 `number: int`、`reasons: list[str]`
  - `EDITION_MARKER`、`TASK_LINE`（正则）、`FILM_MARK = "<!-- film:"`
  - `edition_marker(edition_id: str) -> str`；`task_line(text: str, film_id: int, checked: bool) -> str`；`has_edition_marker(body: str) -> bool`；`parse_issue(issue: Issue) -> ParsedIssue | None`
- Produces（`film_radar.render`）：`issue_body(edition, number, page_url, watched: frozenset[int] = frozenset()) -> str`

- [ ] **Step 0：看任务 1 的结论。** 读 spec 第 12 节「实测结果」。如果 G1b 或 G2 的结论是「拒绝且有提示」，本任务的 `ISSUE_HOWTO` 用第二句加长版：`"勾选＝我已经看过，取消勾选＝撤销。几分钟后页面和其他期 Issue 会同步；页面没变化就强制刷新一下。连续勾几部时，勾完一部看到页面刷新再勾下一部。"`，并在 `test_issue_body_lists_must_and_ok_as_checkboxes` 里加一行断言它在正文里。否则用下面的原文。

- [ ] **Step 1：写失败的测试（解析）。** 追加到 `tests/test_watched.py`：

```python
# ---- Issue 任务项（spec 第 4 节）----

from film_radar.watched import (  # noqa: E402
    Issue, IssueFormatError, Line, ParsedIssue, edition_marker, has_edition_marker, parse_issue, task_line,
)

FJORD = "- [ ] **Fjord** · 在映第 2 周：一句话 <!-- film:62301 bot:0 -->"
BODY = "\n".join([
    "<!-- film-radar:edition 2026-10-22 -->",
    "第 4 期重点推荐：",
    "",
    FJORD,
    "",
    "看过、仍在映（取消勾选可撤销）：",
    "",
    "- [x] **Pan** · 重映（2006 年上映） <!-- film:62050 bot:1 -->",
    "",
    "cc @AKASHA-R",
    "",
])


def test_marker_and_task_line_formats():
    assert edition_marker("2026-10-22") == "<!-- film-radar:edition 2026-10-22 -->"
    assert task_line("**A** · 在映第 1 周", 5, True) == "- [x] **A** · 在映第 1 周 <!-- film:5 bot:1 -->"
    assert task_line("**A** · 在映第 1 周", 5, False) == "- [ ] **A** · 在映第 1 周 <!-- film:5 bot:0 -->"
    assert has_edition_marker(BODY) and not has_edition_marker("备注\n" + BODY) and not has_edition_marker("")


def test_parse_reads_every_task_line():
    assert parse_issue(Issue(7, BODY)) == ParsedIssue(7, "2026-10-22", (Line(62301, False, False), Line(62050, True, True)))


def test_parse_accepts_uppercase_x_and_crlf():
    """GitHub 网页编辑过的正文可能是 \\r\\n 换行（Review Focus 1）。"""
    body = BODY.replace("- [ ] **Fjord**", "- [X] **Fjord**").replace("\n", "\r\n")
    parsed = parse_issue(Issue(7, body))
    assert parsed.edition_id == "2026-10-22"
    assert parsed.lines == (Line(62301, True, False), Line(62050, True, True))


def test_an_issue_without_marker_or_film_lines_is_ignored():
    assert parse_issue(Issue(3, "第 2 期重点推荐：\n\n- **A**（在映第 1 周）：旧格式\n")) is None
    assert parse_issue(Issue(9, "")) is None


def test_text_inserted_above_the_marker_is_reported_not_ignored():
    """静默忽略的话，这个 Issue 里的勾永远不生效（Review Focus 2）。"""
    with pytest.raises(IssueFormatError, match="第一行"):
        parse_issue(Issue(7, "我的备注\n" + BODY))


@pytest.mark.parametrize("broken", [
    "- [ ] **Fjord** · x <!-- film:62301 bot:2 -->",
    "- [ ] **Fjord** · x <!-- film:abc bot:0 -->",
    "* [ ] **Fjord** · x <!-- film:62301 bot:0 -->",
    "  - [ ] **Fjord** · x <!-- film:62301 bot:0 -->",
    "- [ ] **Fjord** · x <!-- film:62301 bot:0 --> 我加的字",
])
def test_a_broken_line_makes_the_whole_issue_unparsable(broken):
    with pytest.raises(IssueFormatError) as caught:
        parse_issue(Issue(7, BODY.replace(FJORD, broken)))
    assert caught.value.number == 7 and "第 4 行" in caught.value.reasons[0]


def test_a_film_listed_twice_makes_the_whole_issue_unparsable():
    with pytest.raises(IssueFormatError, match="两次"):
        parse_issue(Issue(7, BODY.replace("film:62050", "film:62301")))
```

- [ ] **Step 2：写失败的测试（正文）。** 在 `tests/test_render.py` 里：把 import 那行改成

```python
from film_radar.render import (
    CATEGORY_LABELS, ISSUE_HOWTO, ISSUE_TITLE_LIMIT, issue_body, issue_title, render_edition, render_site, status_text,
)
from film_radar.watched import Issue, parse_issue
```

删掉 `test_issue_body` 和 `test_issue_body_without_must_or_failures`，换成：

```python
SEEN_ENTRY = {"film_id": 9, "title": "Seen", "status": "now_playing", "release_date": "2006-10-11",
              "weeks_in_release": None, "detail_url": "https://www.cineplex.com/movie/seen", "version_ids": [9]}


def test_issue_body_lists_must_and_ok_as_checkboxes(settings):
    edition = build_edition(settings, [
        recommended(1, "Pick", {"status": "coming_soon", "release_date": "2026-10-09", "weeks_in_release": None},
                    tier="must", one_liner="一部民俗恐怖片。"),
        recommended(2, "Fine", tier="ok", one_liner="还行。"),
        skipped(3, "Nope"),
        broken(4, "Broken"),
    ])
    body = issue_body(edition, 1, PAGE_URL)
    lines = body.split("\n")
    assert lines[0] == "<!-- film-radar:edition 2026-10-08 -->"
    assert "- [ ] **Pick** · 10月9日上映：一部民俗恐怖片。 <!-- film:1 bot:0 -->" in lines
    assert "- [ ] **Fine** · 在映第 1 周：还行。 <!-- film:2 bot:0 -->" in lines
    assert lines.index("第 1 期重点推荐：") < lines.index("可以看：")
    assert "跳过 1 部，未能评估 1 部。" in lines
    assert ISSUE_HOWTO in lines and f"完整页面：{PAGE_URL}" in lines
    assert "Nope" not in body and "Broken" not in body and "<details" not in body


def test_issue_body_without_must_or_failures(settings):
    body = issue_body(build_edition(settings, [skipped(1, "A")]), 1, PAGE_URL)
    assert "本期没有重点推荐。" in body and "可以看：" not in body
    assert "未能评估" not in body and "跳过 1 部。" in body


def test_issue_body_round_trips_through_the_parser(settings):
    edition = build_edition(settings, [recommended(1, "A", tier="must"), recommended(2, "B", tier="ok")])
    edition["watched_showing"] = [dict(SEEN_ENTRY)]
    parsed = parse_issue(Issue(5, issue_body(edition, 3, PAGE_URL, frozenset({9}))))
    assert parsed.edition_id == "2026-10-08"
    assert [(l.film_id, l.checked, l.bot) for l in parsed.lines] == [(1, False, False), (2, False, False), (9, True, True)]


def test_watched_section_lists_films_checked(settings):
    edition = build_edition(settings, [recommended(1, "A", tier="must")])
    edition["watched_showing"] = [dict(SEEN_ENTRY)]
    lines = issue_body(edition, 1, PAGE_URL, frozenset({9})).split("\n")
    assert "看过、仍在映（取消勾选可撤销）：" in lines
    assert "- [x] **Seen** · 重映（2006 年上映） <!-- film:9 bot:1 -->" in lines


def test_watched_section_absent_when_empty_or_missing(settings):
    """老数据没有 watched_showing 字段（Review Focus 4）。"""
    edition = build_edition(settings, [recommended(1, "A", tier="must")])
    edition.pop("watched_showing", None)
    assert "看过、仍在映" not in issue_body(edition, 1, PAGE_URL)
    edition["watched_showing"] = []
    assert "看过、仍在映" not in issue_body(edition, 1, PAGE_URL)


def test_a_recommended_film_already_on_the_list_is_checked(settings):
    """迁移旧 Issue 时按当时的名单生成勾选状态（spec 第 10 节）。"""
    edition = build_edition(settings, [recommended(1, "A", tier="must")])
    assert "- [x] **A** · 在映第 1 周：一句话定位。 <!-- film:1 bot:1 -->" in issue_body(edition, 1, PAGE_URL, frozenset({1}))


def test_issue_lines_are_cleaned_so_the_issue_always_parses(settings):
    hostile = "Line\r\nbreak\tand <!-- film:1 bot:1 --> @octocat end"
    edition = build_edition(settings, [recommended(7, hostile, tier="must", one_liner=hostile),
                                       recommended(8, "B **bold** · dot", tier="ok")])
    body = issue_body(edition, 1, PAGE_URL)
    assert [l.film_id for l in parse_issue(Issue(1, body)).lines] == [7, 8]
    assert "<!-- film:1 " not in body and "＜!-- film:1 bot:1 --＞" in body
    assert "@octocat" not in body and "\t" not in body and " " not in body
```

- [ ] **Step 3：跑测试确认失败。**

Run：`.venv/bin/python -m pytest tests/test_watched.py tests/test_render.py -q`
Expected：FAIL（`ImportError: cannot import name 'Issue'`、`cannot import name 'ISSUE_HOWTO'`）

- [ ] **Step 4：实现解析。** `src/film_radar/watched.py` 顶部 import 改成

```python
import json
import re
from dataclasses import dataclass
from pathlib import Path
```

文件末尾追加：

```python
# ---- Issue 任务项（spec 第 4 节）----

EDITION_MARKER = re.compile(r"<!-- film-radar:edition (\d{4}-\d{2}-\d{2}) -->")
FILM_MARK = "<!-- film:"
TASK_LINE = re.compile(r"^- \[( |x|X)\] .*<!-- film:(\d+) bot:([01]) -->\s*$")


@dataclass(frozen=True)
class Issue:
    number: int
    body: str


@dataclass(frozen=True)
class Line:
    film_id: int
    checked: bool
    bot: bool          # 程序最后一次写入时这一行勾没勾；用户的操作＝当前勾选 ≠ bot


@dataclass(frozen=True)
class ParsedIssue:
    number: int
    edition_id: str
    lines: tuple[Line, ...]


class IssueFormatError(Exception):
    def __init__(self, number: int, reasons: list[str]):
        super().__init__(f"Issue #{number} 无法解析：" + "；".join(reasons))
        self.number = number
        self.reasons = list(reasons)


def edition_marker(edition_id: str) -> str:
    return f"<!-- film-radar:edition {edition_id} -->"


def task_line(text: str, film_id: int, checked: bool) -> str:
    """一部片一行任务项。text 必须已经清理过（render._issue_text）。"""
    return f"- [{'x' if checked else ' '}] {text} <!-- film:{film_id} bot:{int(checked)} -->"


def _first_line(body: str) -> str:
    return body.split("\n", 1)[0].lstrip("﻿").strip()


def has_edition_marker(body: str) -> bool:
    return EDITION_MARKER.fullmatch(_first_line(body)) is not None


def parse_issue(issue: Issue) -> ParsedIssue | None:
    """不是程序管理的 Issue（没有标记、也没有任何任务项标记）返回 None。

    是程序管理的、但有坏行或重复编号，抛 IssueFormatError：整个 Issue 跳过、一个勾都不采用，
    手改坏的 Issue 里分不清哪些勾是用户的意图。标记不在第一行（用户在上面加了字）也算坏，
    否则这个 Issue 会被静默忽略。按 "\\n" 分行，行尾的 "\\r" 由正则的 \\s* 吸收。"""
    rows = issue.body.split("\n")
    marker = EDITION_MARKER.fullmatch(_first_line(issue.body))
    if marker is None:
        if any(FILM_MARK in row or EDITION_MARKER.search(row) for row in rows):
            raise IssueFormatError(issue.number, ["第一行的 edition 标记不见了（是不是在它上面加了文字？）"])
        return None
    lines, reasons, seen = [], [], set()
    for n, row in enumerate(rows, 1):
        if FILM_MARK not in row:
            continue
        hit = TASK_LINE.match(row)
        if hit is None:
            reasons.append(f"第 {n} 行格式不对：{row.strip()[:80]}")
            continue
        film_id = int(hit.group(2))
        if film_id in seen:
            reasons.append(f"第 {n} 行：编号 {film_id} 出现了两次")
            continue
        seen.add(film_id)
        lines.append(Line(film_id, hit.group(1) != " ", hit.group(3) == "1"))
    if reasons:
        raise IssueFormatError(issue.number, reasons)
    return ParsedIssue(issue.number, marker.group(1), tuple(lines))
```

- [ ] **Step 5：实现正文。** `src/film_radar/render.py`：import 区加 `import re`，并在 `from pathlib import Path` 下面加 `from .watched import edition_marker, is_watched, task_line`。在 `ISSUE_TITLE_LIMIT = 200` 下面加：

```python
ISSUE_HOWTO = "勾选＝我已经看过，取消勾选＝撤销。几分钟后页面和其他期 Issue 会同步；页面没变化就强制刷新一下。"
_LINE_BREAKS = re.compile(r"[\r\n\t\v\f\x1c-\x1e\x85  ]")
```

把 `issue_body` 整个换成：

```python
def _issue_text(text: str) -> str:
    """写进 Issue 任务项的数据文字（片名、一句话推荐）先清理（spec 第 4 节）：换行和制表符换成空格，
    否则一行任务项会被拆成两行，整个 Issue 生来就无法解析；尖括号换成全角，免得拼出假的 <!-- film: --> 标记
    （逐字替换，不会像删掉 <!-- 那样拼出新标记）；@ 照旧插零宽空格。"""
    return _no_mention(_LINE_BREAKS.sub(" ", text).replace("<", "＜").replace(">", "＞"))


def _issue_line(film: dict, watched: frozenset[int], one_liner: str = "") -> str:
    # 片名和状态之间所有行都用「 · 」：重映的状态文字自带括号，外面再套括号就成了双层
    text = f"**{film['title']}** · {status_text(film)}"
    if one_liner.strip():
        text += f"：{one_liner}"
    return task_line(_issue_text(text), film["film_id"], is_watched(film, watched))


def issue_body(edition: dict, number: int, page_url: str, watched: frozenset[int] = frozenset()) -> str:
    """edition Issue 正文：每部推荐片一行勾选框，勾选＝看过（spec 2026-10-17 第 4 节）。"""
    films = edition["films"]
    musts = _by_strength([f for f in films if f["outcome"] == "must"])
    oks = _by_strength([f for f in films if f["outcome"] == "ok"])
    showing = edition.get("watched_showing", [])        # 老数据没有这个字段
    lines = [edition_marker(edition["edition_id"])]
    if musts:
        lines += [f"第 {number} 期重点推荐：", ""] + [_issue_line(f, watched, f["card"]["one_liner"]) for f in musts]
    else:
        lines.append("本期没有重点推荐。")
    if oks:
        lines += ["", "可以看：", ""] + [_issue_line(f, watched, f["card"]["one_liner"]) for f in oks]
    if showing:
        lines += ["", "看过、仍在映（取消勾选可撤销）：", ""] + [_issue_line(e, watched) for e in showing]
    counts = edition["counts"]
    summary = f"跳过 {counts['skip']} 部"
    if counts["review_failed"]:
        summary += f"，未能评估 {counts['review_failed']} 部"
    lines += ["", summary + "。", "", ISSUE_HOWTO, f"完整页面：{page_url}"]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 6：跑测试确认通过。**

Run：`.venv/bin/python -m pytest -q`
Expected：全部 PASS（`test_issue_text_never_mentions_github_users` 也要过）

- [ ] **Step 7：验红。** 两处各注入一次、各自还原：①`_issue_text` 去掉 `_LINE_BREAKS.sub(" ", text)` → `tests/test_render.py` 应当 FAIL；②`parse_issue` 里 `marker is None` 分支直接 `return None` → `tests/test_watched.py` 应当 FAIL。

- [ ] **Step 8：提交。**

```bash
git -C /Users/minggao/Projects/film-radar-watched add src/film_radar/watched.py src/film_radar/render.py tests/test_watched.py tests/test_render.py
git -C /Users/minggao/Projects/film-radar-watched commit -m "feat: edition Issue 改成勾选框格式，并能解析回来

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4：同步纯函数

**Files：**
- Modify：`src/film_radar/watched.py`（追加）、`tests/helpers.py`（追加 `task_issue`、`toggle`）
- Test：`tests/test_watched.py`（追加）

**Interfaces：**
- Consumes：任务 2 的 `version_ids`、`watched_ids`；任务 3 的 `Issue`、`parse_issue`、`IssueFormatError`、`task_line`、`edition_marker`
- Produces（`film_radar.watched`）：
  - `@dataclass(frozen=True) Action(issue: int, film_id: int, watched: bool)`
  - `@dataclass(frozen=True) Rewrite(issue: int, film_id: int, observed: bool, target: bool)`
  - `@dataclass(frozen=True) Problem(issue: int, reasons: tuple[str, ...])`
  - `@dataclass(frozen=True) Catalog(by_edition, by_primary, titles)`，方法 `versions(edition_id: str, film_id: int) -> frozenset[int]`
  - `@dataclass SyncResult(films, changed: bool, actions: list[Action], conflicts: list[int], rewrites: list[Rewrite], problems: list[Problem])`
  - `build_catalog(editions: list[dict]) -> Catalog`
  - `sync(films: dict[int, dict], issues: list[Issue], catalog: Catalog, now: str) -> SyncResult`
- Produces（`tests/helpers.py`）：`task_issue(edition_id: str, *rows: tuple[int, bool, bool]) -> str`、`toggle(body: str, film_id: int) -> str`

- [ ] **Step 1：加测试构造函数。** 追加到 `tests/helpers.py` 末尾：

```python
# ---- 「已看过」同步用到 ----

def task_issue(edition_id: str, *rows) -> str:
    """一个最小的 edition Issue 正文。rows 是 (film_id, 当前勾选, bot)。"""
    from film_radar.watched import edition_marker, task_line

    lines = [edition_marker(edition_id), "", "第 N 期重点推荐：", ""]
    for film_id, checked, bot in rows:
        line = task_line(f"**Film {film_id}** · 在映第 1 周", film_id, bot)
        if checked != bot:
            line = f"- [{'x' if checked else ' '}]" + line[5:]
        lines.append(line)
    return "\n".join(lines) + "\n\ncc @AKASHA-R\n"


def toggle(body: str, film_id: int) -> str:
    """模拟用户在网页上点一下某一行的勾选框。"""
    rows = body.split("\n")
    for i, row in enumerate(rows):
        if f"<!-- film:{film_id} " in row:
            rows[i] = ("- [x]" if row.startswith("- [ ]") else "- [ ]") + row[5:]
    return "\n".join(rows)
```

- [ ] **Step 2：写失败的测试。** 追加到 `tests/test_watched.py`：

```python
# ---- 同步（spec 第 5 节）----

from film_radar.watched import Action, Rewrite, build_catalog, sync  # noqa: E402
from helpers import task_issue  # noqa: E402

NOW = "2026-10-18T09:00:00-04:00"


def edition(edition_id, *film_ids, versions=None, showing=()):
    versions = versions or {}
    data = {"edition_id": edition_id, "films": [
        {"film_id": f, "title": f"Film {f}", "versions": [{"film_id": v} for v in versions.get(f, [f])]}
        for f in film_ids
    ]}
    if showing:
        data["watched_showing"] = [{"film_id": f, "title": f"Film {f}", "version_ids": [f]} for f in showing]
    return data


CATALOG = build_catalog([edition("2026-10-03", 1, 2), edition("2026-10-08", 1, 3)])


def entry(film_id, since=NOW, ids=None):
    return {"title": f"Film {film_id}", "since": since, "ids": ids or [film_id]}


def run(films, issues, catalog=CATALOG):
    return sync(films, [Issue(number, body) for number, body in issues.items()], catalog, NOW)


def test_a_tick_adds_the_film_and_plans_every_issue_that_shows_it():
    result = run({}, {2: task_issue("2026-10-03", (1, True, False), (2, False, False)),
                      5: task_issue("2026-10-08", (1, False, False), (3, False, False))})
    assert result.films == {1: entry(1)} and result.changed
    assert result.actions == [Action(2, 1, True)]
    assert result.rewrites == [Rewrite(2, 1, True, True), Rewrite(5, 1, False, True)]
    assert result.conflicts == [] and result.problems == []


def test_an_untick_removes_the_film_everywhere():
    result = run({1: entry(1)}, {2: task_issue("2026-10-03", (1, False, True)),
                                 5: task_issue("2026-10-08", (1, True, True))})
    assert result.films == {} and result.changed
    assert result.actions == [Action(2, 1, False)]
    assert result.rewrites == [Rewrite(2, 1, False, False), Rewrite(5, 1, True, False)]


def test_the_list_wins_over_an_issue_left_behind_by_a_failed_rewrite():
    """名单是事实来源：Issue 和名单不一致、却没有用户操作（勾选＝bot），按名单改 Issue，不反过来改名单。"""
    result = run({1: entry(1)}, {5: task_issue("2026-10-08", (1, False, False))})
    assert result.films == {1: entry(1)} and not result.changed and result.actions == []
    assert result.rewrites == [Rewrite(5, 1, False, True)]


def test_conflicting_actions_are_settled_by_the_newer_issue():
    newer_unticks = run({}, {5: task_issue("2026-10-08", (1, False, True)), 2: task_issue("2026-10-03", (1, True, False))})
    assert newer_unticks.films == {} and newer_unticks.conflicts == [1]
    newer_ticks = run({1: entry(1)}, {2: task_issue("2026-10-03", (1, False, True)), 5: task_issue("2026-10-08", (1, True, False))})
    assert list(newer_ticks.films) == [1] and newer_ticks.conflicts == [1]


def test_an_unparsable_issue_is_skipped_without_blocking_the_others():
    unparsable = task_issue("2026-10-03", (1, True, False)).replace("bot:0", "bot:9")
    result = run({}, {2: unparsable, 5: task_issue("2026-10-08", (3, True, False))})
    assert result.films == {3: entry(3)}
    assert [p.issue for p in result.problems] == [2] and "格式不对" in result.problems[0].reasons[0]
    assert {r.issue for r in result.rewrites} == {5}


def test_issues_without_the_edition_marker_are_ignored():
    result = run({}, {3: "第 2 期重点推荐：\n\n- **Film 1**（在映第 1 周）：旧格式\n",
                      9: "film-radar 运行失败\n\ncc @AKASHA-R\n"})
    assert result.films == {} and result.actions == [] and result.rewrites == [] and result.problems == []


def test_a_second_run_on_the_settled_issues_does_nothing():
    first = run({}, {2: task_issue("2026-10-03", (1, True, False), (2, False, False)),
                     5: task_issue("2026-10-08", (1, False, False))})
    second = run(first.films, {2: task_issue("2026-10-03", (1, True, True), (2, False, False)),
                               5: task_issue("2026-10-08", (1, True, True))})
    assert second.films == first.films
    assert not second.changed and second.actions == [] and second.rewrites == []


def test_ticking_a_listed_film_again_keeps_its_entry():
    old = entry(1, since="2026-10-01T00:00:00-04:00")
    result = run({1: old}, {5: task_issue("2026-10-08", (1, True, False))})
    assert result.films == {1: old} and not result.changed


def test_unticking_a_film_that_is_not_listed_changes_nothing():
    result = run({}, {5: task_issue("2026-10-08", (1, False, True))})
    assert result.films == {} and not result.changed
    assert result.rewrites == [Rewrite(5, 1, False, False)]          # 只把 bot 对齐


def test_a_tick_records_every_version_seen_for_that_film():
    catalog = build_catalog([edition("2026-10-03", 1), edition("2026-10-08", 1, versions={1: [1, 4]})])
    result = run({}, {2: task_issue("2026-10-03", (1, True, False))}, catalog)
    assert result.films == {1: entry(1, ids=[1, 4])}


def test_films_are_matched_by_any_version_when_the_primary_id_changes():
    catalog = build_catalog([edition("2026-10-08", 1, versions={1: [1, 4]}), edition("2026-10-22", 4)])
    listed = {1: entry(1, ids=[1, 4])}
    result = run(listed, {7: task_issue("2026-10-22", (4, False, False))}, catalog)
    assert result.rewrites == [Rewrite(7, 4, False, True)] and not result.changed
    assert run(listed, {7: task_issue("2026-10-22", (4, False, True))}, catalog).films == {}


def test_a_film_missing_from_the_editions_is_still_recorded():
    result = run({}, {5: task_issue("2026-10-08", (9000001, True, False))})
    assert result.films == {9000001: {"title": "9000001", "since": NOW, "ids": [9000001]}}


def test_catalog_reads_watched_showing_and_tolerates_old_editions():
    catalog = build_catalog([edition("2026-10-03", 1), edition("2026-10-22", 2, showing=(5,))])
    assert catalog.versions("2026-10-22", 5) == {5}
    assert catalog.versions("2026-10-03", 1) == {1}
    assert catalog.versions("2026-10-03", 77) == {77}          # 没见过的片只认它自己的编号
    assert catalog.titles[5] == "Film 5"
```

- [ ] **Step 3：跑测试确认失败。**

Run：`.venv/bin/python -m pytest tests/test_watched.py -q`
Expected：FAIL（`ImportError: cannot import name 'Action'`）

- [ ] **Step 4：实现。** 追加到 `src/film_radar/watched.py` 末尾：

```python
# ---- 同步（spec 第 5 节）----

@dataclass(frozen=True)
class Action:
    issue: int
    film_id: int
    watched: bool          # True＝勾上（标为看过），False＝取消（撤销）


@dataclass(frozen=True)
class Rewrite:
    issue: int
    film_id: int
    observed: bool         # 计算时读到的勾选：改写时用它判断用户之后有没有又改过（spec 第 6 节第 4 步）
    target: bool


@dataclass(frozen=True)
class Problem:
    issue: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Catalog:
    """data/editions 里的编号：某一期里某部片的版本编号；每个主编号跨期合并后的版本编号；片名。"""
    by_edition: dict
    by_primary: dict
    titles: dict

    def versions(self, edition_id: str, film_id: int) -> frozenset[int]:
        return self.by_edition.get((edition_id, film_id), frozenset({film_id}))


@dataclass
class SyncResult:
    films: dict[int, dict]
    changed: bool
    actions: list[Action]
    conflicts: list[int]
    rewrites: list[Rewrite]
    problems: list[Problem]


def build_catalog(editions: list[dict]) -> Catalog:
    by_edition, by_primary, titles = {}, {}, {}
    for edition in sorted(editions, key=lambda e: e["edition_id"]):
        for film in [*edition["films"], *edition.get("watched_showing", [])]:      # 老数据没有 watched_showing
            ids = version_ids(film)
            by_edition[(edition["edition_id"], film["film_id"])] = ids
            by_primary[film["film_id"]] = by_primary.get(film["film_id"], frozenset()) | ids
            titles[film["film_id"]] = film["title"]
    return Catalog(by_edition, by_primary, titles)


def sync(films: dict[int, dict], issues: list[Issue], catalog: Catalog, now: str) -> SyncResult:
    """films 是旧名单，issues 是所有 edition Issue（含已关闭的），now 是多伦多时区的 ISO 时间。"""
    parsed, problems = [], []
    for issue in sorted(issues, key=lambda i: i.number):
        try:
            result = parse_issue(issue)
        except IssueFormatError as e:
            problems.append(Problem(e.number, tuple(e.reasons)))
            continue
        if result is not None:
            parsed.append(result)

    # 用户的操作＝当前勾选和 bot 不一致的行。按 Issue 编号从小到大应用，冲突时编号大的（较新的一期）自然胜出。
    # 不用 updated_at：评论、关闭、改标签都会刷新它，反映不了勾选的先后
    actions = [Action(p.number, line.film_id, line.checked) for p in parsed for line in p.lines if line.checked != line.bot]
    kinds: dict[int, set[bool]] = {}
    for action in actions:
        kinds.setdefault(action.film_id, set()).add(action.watched)
    conflicts = sorted(film_id for film_id, seen in kinds.items() if len(seen) > 1)

    edition_of = {p.number: p.edition_id for p in parsed}
    new = {film_id: {**entry, "ids": list(entry["ids"])} for film_id, entry in films.items()}
    for action in actions:
        ids = catalog.versions(edition_of[action.issue], action.film_id)
        covering = [key for key, entry in new.items() if not ids.isdisjoint(entry["ids"])]
        if action.watched and not covering:          # 已经在名单里的片再勾一次，不改动已有条目
            new[action.film_id] = {
                "title": catalog.titles.get(action.film_id, str(action.film_id)),
                "since": now,
                "ids": sorted(ids | catalog.by_primary.get(action.film_id, frozenset())),
            }
        elif not action.watched:
            for key in covering:
                del new[key]

    listed = watched_ids(new)
    rewrites = []
    for p in parsed:
        for line in p.lines:
            target = not catalog.versions(p.edition_id, line.film_id).isdisjoint(listed)
            if line.checked != target or line.bot != target:
                rewrites.append(Rewrite(p.number, line.film_id, line.checked, target))
    return SyncResult(new, new != films, actions, conflicts, rewrites, problems)
```

- [ ] **Step 5：跑测试确认通过。**

Run：`.venv/bin/python -m pytest -q`
Expected：全部 PASS

- [ ] **Step 6：验红。** 把 `for issue in sorted(issues, key=lambda i: i.number)` 改成 `sorted(..., reverse=True)`，`sh scripts/redcheck.sh tests/test_watched.py` 应当 FAIL（冲突那条）；还原。再把 `if action.watched and not covering:` 改成 `if action.watched:`，应当 FAIL（`test_ticking_a_listed_film_again_keeps_its_entry`）；还原。

- [ ] **Step 7：提交。**

```bash
git -C /Users/minggao/Projects/film-radar-watched add src/film_radar/watched.py tests/helpers.py tests/test_watched.py
git -C /Users/minggao/Projects/film-radar-watched commit -m "feat: 已看过同步算法（从 Issue 勾选得出新名单和改写计划）

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5：改写合并

**Files：**
- Modify：`src/film_radar/watched.py`（追加 `apply_rewrites`）
- Test：`tests/test_watched.py`（追加）

**Interfaces：**
- Consumes：任务 3 的 `TASK_LINE`；任务 4 的 `Rewrite`、`sync`
- Produces：`apply_rewrites(body: str, rewrites: list[Rewrite]) -> str`。调用方负责先确认 `body` 能解析（任务 10）。

- [ ] **Step 1：写失败的测试。** 追加到 `tests/test_watched.py`：

```python
# ---- 改写合并（spec 第 6 节第 4 步）----

from film_radar.watched import apply_rewrites  # noqa: E402
from helpers import toggle  # noqa: E402


def lines_of(body):
    return parse_issue(Issue(0, body)).lines


def test_a_rewrite_sets_checkbox_and_bot_to_the_target():
    out = apply_rewrites(task_issue("2026-10-08", (1, False, False), (3, False, False)), [Rewrite(5, 1, False, True)])
    assert lines_of(out) == (Line(1, True, True), Line(3, False, False))


def test_a_rewrite_only_touches_the_checkbox_and_the_bot_digit():
    body = task_issue("2026-10-08", (1, False, False)).replace("**Film 1**", "**Film 1** 和朋友一起看").replace("\n", "\r\n")
    out = apply_rewrites(body, [Rewrite(5, 1, False, True)])
    assert out == body.replace("- [ ] **Film 1**", "- [x] **Film 1**").replace("film:1 bot:0", "film:1 bot:1")


def test_a_box_the_user_changed_after_the_computation_keeps_the_users_choice():
    body = task_issue("2026-10-08", (1, False, False))          # 计算时读到「勾上」，改写前用户又取消了
    out = apply_rewrites(body, [Rewrite(5, 1, True, True)])
    assert lines_of(out) == (Line(1, False, True),)             # 勾选保留用户的，bot 写成目标：下一轮认得出这是撤销


def round_trip(films, bodies, user=None):
    """跑一轮同步再改写。user(bodies) 在计算之后、改写之前修改正文，模拟用户手快。"""
    result = sync(films, [Issue(n, b) for n, b in bodies.items()], CATALOG, NOW)
    if user:
        user(bodies)
    for number in sorted({r.issue for r in result.rewrites}):
        bodies[number] = apply_rewrites(bodies[number], [r for r in result.rewrites if r.issue == number])
    return result.films, bodies


def settled(films, bodies):
    """再跑一轮应当什么都不做。"""
    again = sync(films, [Issue(n, b) for n, b in bodies.items()], CATALOG, NOW)
    return again.actions == [] and again.rewrites == [] and not again.changed


def test_unticking_right_after_ticking_is_not_swallowed():
    bodies = {5: task_issue("2026-10-08", (1, True, False))}
    films, bodies = round_trip({}, bodies, user=lambda b: b.update({5: toggle(b[5], 1)}))
    assert list(films) == [1]                                   # 第一轮记下了勾
    films, bodies = round_trip(films, bodies)
    assert films == {} and lines_of(bodies[5]) == (Line(1, False, False),) and settled(films, bodies)


def test_reticking_right_after_unticking_is_not_swallowed():
    bodies = {5: task_issue("2026-10-08", (1, False, True))}
    films, bodies = round_trip({1: entry(1)}, bodies, user=lambda b: b.update({5: toggle(b[5], 1)}))
    assert films == {}
    films, bodies = round_trip(films, bodies)
    assert list(films) == [1] and lines_of(bodies[5]) == (Line(1, True, True),) and settled(films, bodies)


def test_another_line_changed_in_the_same_issue_is_not_overwritten():
    bodies = {5: task_issue("2026-10-08", (1, True, False), (3, False, False))}
    films, bodies = round_trip({}, bodies, user=lambda b: b.update({5: toggle(b[5], 3)}))
    assert list(films) == [1]
    films, bodies = round_trip(films, bodies)
    assert sorted(films) == [1, 3] and settled(films, bodies)


def test_a_rewrite_that_never_happened_is_repaired_by_the_next_run():
    bodies = {2: task_issue("2026-10-03", (1, True, False)), 5: task_issue("2026-10-08", (1, False, False))}
    first = sync({}, [Issue(n, b) for n, b in bodies.items()], CATALOG, NOW)       # 名单已提交，改写全部失败
    films, bodies = round_trip(first.films, bodies)
    assert films == first.films
    assert lines_of(bodies[2]) == (Line(1, True, True),) and lines_of(bodies[5]) == (Line(1, True, True),)
    assert settled(films, bodies)
```

- [ ] **Step 2：跑测试确认失败。**

Run：`.venv/bin/python -m pytest tests/test_watched.py -q`
Expected：FAIL（`ImportError: cannot import name 'apply_rewrites'`）

- [ ] **Step 3：实现。** 追加到 `src/film_radar/watched.py` 末尾：

```python
def apply_rewrites(body: str, rewrites: list[Rewrite]) -> str:
    """在改写前新读到的正文上逐行合并（spec 第 6 节第 4 步），只动勾选框和 bot 两处，其他文字原样保留。

    bot 一律写成目标；勾选框只在「新读到的勾选」等于「计算时读到的勾选」时才改，否则保留用户刚改的勾选：
    那一行变成「当前 ≠ bot」，下一次同步能认出这个操作。"""
    plan = {r.film_id: r for r in rewrites}
    rows = body.split("\n")
    for i, row in enumerate(rows):
        hit = TASK_LINE.match(row)
        if hit is None or int(hit.group(2)) not in plan:
            continue
        rewrite = plan[int(hit.group(2))]
        current = hit.group(1) != " "
        checked = rewrite.target if current == rewrite.observed else current
        start, end = hit.span(3)
        rows[i] = f"- [{'x' if checked else ' '}]" + row[5:start] + str(int(rewrite.target)) + row[end:]
    return "\n".join(rows)
```

- [ ] **Step 4：跑测试确认通过。**

Run：`.venv/bin/python -m pytest -q`
Expected：全部 PASS

- [ ] **Step 5：验红。** 把 `checked = rewrite.target if current == rewrite.observed else current` 改成 `checked = rewrite.target`，`sh scripts/redcheck.sh tests/test_watched.py` 应当 FAIL（三条「not swallowed / not overwritten」）；还原。

- [ ] **Step 6：提交。**

```bash
git -C /Users/minggao/Projects/film-radar-watched add src/film_radar/watched.py tests/test_watched.py
git -C /Users/minggao/Projects/film-radar-watched commit -m "feat: 改写 Issue 时在新读到的正文上合并，不吞掉用户刚做的操作

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6：GitHub 接口客户端、`repo` 配置、测试替身

**Files：**
- Create：`src/film_radar/github.py`、`tests/test_github.py`
- Modify：`src/film_radar/settings.py`、`config/settings.toml`、`tests/test_settings.py`、`tests/conftest.py`、`tests/helpers.py`

**Interfaces：**
- Consumes：任务 3 的 `Issue`
- Produces：
  - `Settings.repo: str`（形如 `owner/name`）
  - `film_radar.github`：`API`、`BOT_LOGIN = "github-actions[bot]"`、`class GitHubError(Exception)`、`class GitHubClient(session, token, repo)`，方法 `edition_issues() -> list[Issue]`、`issue_body(number: int) -> str`、`update_body(number: int, body: str) -> None`，属性 `repo`；`client_from_env(settings, session=None) -> GitHubClient`
  - `helpers.FakeGitHub(bodies: dict[int, str] | None = None, fail_updates: int = 0, before_update=None)`：同名三个方法；属性 `bodies`、`updates: list[tuple[int, str]]`、`calls: list`

- [ ] **Step 1：写失败的测试。** `tests/conftest.py` 改成：

```python
import pytest

from film_radar.settings import load_settings
from helpers import ROOT


@pytest.fixture
def settings():
    return load_settings(ROOT / "config" / "settings.toml")


@pytest.fixture(autouse=True)
def no_github_credentials(monkeypatch):
    """测试绝不能拿到真令牌：漏了替身的测试会以「没有令牌」失败，而不是去改真 Issue。"""
    for name in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_REPOSITORY"):
        monkeypatch.delenv(name, raising=False)
```

`tests/test_settings.py`：在 `test_loads_repo_settings` 末尾加 `assert settings.repo == "AKASHA-R/film-radar"`，文件末尾加：

```python
@pytest.mark.parametrize("bad", ["film-radar", "https://github.com/AKASHA-R/film-radar", "AKASHA-R/film-radar/x", "AKASHA R/film-radar"])
def test_rejects_a_repo_that_is_not_owner_slash_name(tmp_path, bad):
    path = variant(tmp_path, 'repo = "AKASHA-R/film-radar"', f'repo = "{bad}"')
    with pytest.raises(SettingsError, match="repo"):
        load_settings(path)
```

新建 `tests/test_github.py`：

```python
import pytest
import requests

from film_radar.github import API, GitHubClient, GitHubError, client_from_env
from film_radar.watched import Issue
from helpers import FakeGitHub

REPO = "AKASHA-R/film-radar"
FIRST = f"{API}/repos/{REPO}/issues?labels=edition&state=all&per_page=100"
SECOND = f"{API}/repositories/1/issues?labels=edition&state=all&per_page=100&page=2"
BOT = {"login": "github-actions[bot]"}


class Response:
    def __init__(self, status=200, data=None, link=""):
        self.status_code = status
        self._data = data
        self.headers = {"Link": link} if link else {}

    def json(self):
        return self._data


class FakeHTTP:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, url, headers=None, timeout=None, json=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "timeout": timeout, "json": json})
        route = self.routes[(method, url)]
        if isinstance(route, Exception):
            raise route
        return route


def item(number, body="正文", user=BOT, **extra):
    return {"number": number, "body": body, "user": user, "state": "open", **extra}


def client(routes):
    http = FakeHTTP(routes)
    return GitHubClient(http, "token-not-real", REPO), http


def test_reads_every_page_including_closed_issues_and_drops_pull_requests():
    gh, http = client({
        ("GET", FIRST): Response(data=[item(5), item(4, pull_request={"url": "x"})],
                                 link=f'<{SECOND}>; rel="next", <{SECOND}>; rel="last"'),
        ("GET", SECOND): Response(data=[item(2, state="closed")]),
    })
    assert gh.edition_issues() == [Issue(5, "正文"), Issue(2, "正文")]
    assert [c["url"] for c in http.calls] == [FIRST, SECOND]
    assert http.calls[0]["headers"]["Authorization"] == "Bearer token-not-real"
    assert http.calls[0]["timeout"] == 30


def test_issues_not_opened_by_the_bot_are_ignored():
    """有分诊权限的人也能给自己开的 Issue 打 edition 标签；那不是程序管理的 Issue。"""
    gh, _ = client({("GET", FIRST): Response(data=[item(7, user={"login": "someone"}), item(8, user=None), item(5)])})
    assert [i.number for i in gh.edition_issues()] == [5]


def test_an_empty_body_comes_back_as_an_empty_string():
    """用户把正文清空时接口返回 null（Review Focus 3）。"""
    gh, _ = client({("GET", FIRST): Response(data=[item(5, body=None)]),
                    ("GET", f"{API}/repos/{REPO}/issues/5"): Response(data=item(5, body=None))})
    assert gh.edition_issues() == [Issue(5, "")]
    assert gh.issue_body(5) == ""


def test_update_sends_only_the_body():
    url = f"{API}/repos/{REPO}/issues/5"
    gh, http = client({("PATCH", url): Response(data=item(5))})
    gh.update_body(5, "新正文")
    assert http.calls == [{"method": "PATCH", "url": url, "headers": http.calls[0]["headers"], "timeout": 30,
                           "json": {"body": "新正文"}}]


@pytest.mark.parametrize("route, message", [
    (Response(status=502), "HTTP 502"),
    (requests.ConnectionError("boom"), "ConnectionError"),
])
def test_http_and_network_errors_become_github_errors(route, message):
    gh, _ = client({("GET", FIRST): route})
    with pytest.raises(GitHubError, match=message):
        gh.edition_issues()


def test_client_from_env_needs_a_token(settings):
    with pytest.raises(GitHubError, match="GITHUB_TOKEN"):
        client_from_env(settings)


def test_client_from_env_prefers_the_actions_repository(settings, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "token-not-real")
    assert client_from_env(settings).repo == "AKASHA-R/film-radar"
    monkeypatch.setenv("GITHUB_TOKEN", "token-not-real")
    monkeypatch.setenv("GITHUB_REPOSITORY", "someone/fork")
    assert client_from_env(settings).repo == "someone/fork"


def test_the_fake_has_the_same_interface_as_the_real_client():
    public = {name for name in vars(GitHubClient) if not name.startswith("_")}
    assert public == {"edition_issues", "issue_body", "update_body"}
    assert public <= set(dir(FakeGitHub))
```

- [ ] **Step 2：跑测试确认失败。**

Run：`.venv/bin/python -m pytest tests/test_github.py tests/test_settings.py -q`
Expected：FAIL（`ModuleNotFoundError: No module named 'film_radar.github'`；`Settings` 没有 `repo`）

- [ ] **Step 3：实现配置。** `config/settings.toml` 末尾 `page_url = ...` 下面加：

```toml
# GitHub 仓库（owner/name）。页面上「去 Issue 打勾」的链接和本机跑迁移时的接口用它；Actions 里接口以 GITHUB_REPOSITORY 为准。
repo = "AKASHA-R/film-radar"
```

`src/film_radar/settings.py`：`import tomllib` 下面加 `import re`；`CADENCE_DAYS = 14` 下面加 `_REPO = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+")`；`Settings` 末尾加字段 `repo: str`；`load_settings` 的 `return settings` 之前加：

```python
    if not _REPO.fullmatch(settings.repo):
        raise SettingsError(f"repo 要写成 owner/name，例如 AKASHA-R/film-radar：{settings.repo!r}")
```

- [ ] **Step 4：实现客户端。** 新建 `src/film_radar/github.py`：

```python
"""GitHub Issues 接口。整个项目只有这里碰 GitHub 的网络；测试用 helpers.FakeGitHub 替身。"""
from __future__ import annotations

import os
import re

import requests

from .settings import Settings
from .watched import Issue

API = "https://api.github.com"
BOT_LOGIN = "github-actions[bot]"
TIMEOUT = 30
_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


class GitHubError(Exception):
    pass


class GitHubClient:
    def __init__(self, session, token: str, repo: str):
        self.session = session
        self.repo = repo
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _request(self, method: str, url: str, **kwargs):
        try:
            response = self.session.request(method, url, headers=self._headers, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as e:
            raise GitHubError(f"{method} {url}: {type(e).__name__}") from e
        if not 200 <= response.status_code < 300:
            raise GitHubError(f"{method} {url}: HTTP {response.status_code}")
        return response

    def edition_issues(self) -> list[Issue]:
        """所有带 edition 标签的 Issue，包括已关闭的（用户可能勾完顺手关掉），跟着 Link 头按页读完，去掉 PR。
        只认机器人开的：有分诊权限的人也能给自己开的 Issue 打 edition 标签，那不是程序管理的 Issue。"""
        url = f"{API}/repos/{self.repo}/issues?labels=edition&state=all&per_page=100"
        issues = []
        while url:
            response = self._request("GET", url)
            for item in response.json():
                if "pull_request" in item or (item.get("user") or {}).get("login") != BOT_LOGIN:
                    continue
                issues.append(Issue(item["number"], item.get("body") or ""))
            found = _NEXT.search(response.headers.get("Link", ""))
            url = found.group(1) if found else None
        return issues

    def issue_body(self, number: int) -> str:
        return self._request("GET", f"{API}/repos/{self.repo}/issues/{number}").json().get("body") or ""

    def update_body(self, number: int, body: str) -> None:
        self._request("PATCH", f"{API}/repos/{self.repo}/issues/{number}", json={"body": body})


def client_from_env(settings: Settings, session=None) -> GitHubClient:
    """Actions 里用 GITHUB_TOKEN 和 GITHUB_REPOSITORY；本机用 GH_TOKEN=$(gh auth token) 和配置里的 repo。"""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise GitHubError("没有 GITHUB_TOKEN（本机运行请在命令前加 GH_TOKEN=$(gh auth token)）")
    repo = os.environ.get("GITHUB_REPOSITORY") or settings.repo
    return GitHubClient(session if session is not None else requests.Session(), token, repo)
```

- [ ] **Step 5：加替身。** 追加到 `tests/helpers.py` 末尾：

```python
class FakeGitHub:
    """github.GitHubClient 的替身：Issue 正文存在内存里（{编号: 正文}）。方法与真客户端一致（test_github.py 守着）。

    fail_updates：接下来这么多次 update_body 抛 GitHubError。before_update(number, body)：真正写入前回调，
    用来断言「改写前已经写好备份」这类顺序。"""

    def __init__(self, bodies=None, fail_updates=0, before_update=None):
        self.bodies = dict(bodies or {})
        self.fail_updates = fail_updates
        self.before_update = before_update
        self.updates: list[tuple[int, str]] = []
        self.calls: list = []

    def edition_issues(self):
        from film_radar.watched import Issue

        self.calls.append("edition_issues")
        return [Issue(number, body) for number, body in sorted(self.bodies.items())]

    def issue_body(self, number):
        self.calls.append(("issue_body", number))
        return self.bodies[number]

    def update_body(self, number, body):
        from film_radar.github import GitHubError

        self.calls.append(("update_body", number))
        if self.fail_updates:
            self.fail_updates -= 1
            raise GitHubError(f"PATCH issues/{number}: HTTP 502")
        if self.before_update:
            self.before_update(number, body)
        self.updates.append((number, body))
        self.bodies[number] = body
```

- [ ] **Step 6：跑测试确认通过。**

Run：`.venv/bin/python -m pytest -q`
Expected：全部 PASS

- [ ] **Step 7：提交。**

```bash
git -C /Users/minggao/Projects/film-radar-watched add src/film_radar/github.py src/film_radar/settings.py config/settings.toml tests/test_github.py tests/test_settings.py tests/conftest.py tests/helpers.py
git -C /Users/minggao/Projects/film-radar-watched commit -m "feat: GitHub Issues 客户端、repo 配置与测试替身

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7：页面——生成时画出已看过、去掉按钮、链到 Issue、只剩「隐藏」开关

**Files：**
- Modify：`src/film_radar/render.py`、`src/film_radar/main.py`（`_build_site`、`_run` 里的 `render_site`、`STAGES`）
- Test：`tests/test_render.py`、`tests/test_main.py`

**Interfaces：**
- Consumes：任务 2 的 `is_watched`、`watched_ids`、`load_watched_file`、`WatchedError`；任务 6 的 `Settings.repo`
- Produces（`film_radar.render`）：
  - `issues_url(repo: str) -> str` ＝ `f"https://github.com/{repo}/issues?q=is%3Aissue+label%3Aedition"`
  - `HIDE_SEEN_SCRIPT`（取代 `SEEN_SCRIPT`）
  - `render_edition(edition, number, archive, *, is_latest, prefix, watched=frozenset(), repo=None) -> str`
  - `render_site(editions, out_dir, *, watched=frozenset(), repo=None) -> None`
- Produces（`film_radar.main`）：`STAGES[WatchedError] == "读取已看过名单"`；`build-site` 读 `data/watched.json`

- [ ] **Step 1：改测试辅助函数。** `tests/test_render.py` 顶部 `PAGE_URL` 下面加两个常量，并把 `page` 改成：

```python
REPO = "AKASHA-R/film-radar"
ISSUES = "https://github.com/AKASHA-R/film-radar/issues?q=is%3Aissue+label%3Aedition"


def page(edition, number=1, latest=True, watched=frozenset(), repo=REPO):
    archive = [(edition["edition_id"], number)]
    return render_edition(edition, number, archive, is_latest=latest, prefix="" if latest else "../",
                          watched=watched, repo=repo)
```

浏览器测试区的 import 改成 `from film_radar.render import HIDE_SEEN_SCRIPT, STYLE as _STYLE`。

- [ ] **Step 2：删掉按钮时代的测试。** 从 `tests/test_render.py` 删除这些测试函数（整个函数）：`test_every_recommended_card_has_one_hidden_seen_button`、`test_nav_has_a_hidden_hide_seen_chip`、`test_seen_script_is_on_every_page_but_the_stale_script_only_on_the_latest`、`test_seen_script_is_static_and_carries_no_page_data`、`test_seen_script_is_valid_javascript`、`test_page_has_a_polite_live_region_for_seen_announcements`、`test_browser_a_seen_film_is_restored_from_storage_on_load`、`test_browser_clicking_toggles_and_persists`、`test_browser_corrupted_storage_does_not_break_the_page`、`test_browser_hide_seen_chip_hides_and_remembers`、`test_browser_storage_failure_still_lets_you_mark_for_this_visit`、`test_browser_marking_works_when_only_writing_fails`、`test_browser_hide_chip_works_when_storage_is_unavailable`、`test_browser_a_leftover_hide_preference_does_not_swallow_the_first_mark`、`test_browser_marking_in_hide_mode_keeps_keyboard_focus`、`test_browser_changes_are_announced_politely`、`test_browser_state_is_carried_by_aria_pressed_not_by_a_changing_name`、`test_browser_storage_clear_and_bfcache_restore_resync_the_page`、`test_browser_pseudo_element_text_renders_what_the_css_says`；同时删掉 `SEED` 这个 lambda 和旧的 `PROBE` 字符串。`QUOTA`、`DENIED`、`_run_in_chrome`、`browser` 保留。

保留不动（spec 第 9 节表里「保留」的约定）：`test_glance_rows_carry_the_film_id_for_seen_state`、`test_touch_targets_scroll_margin_and_nav_scrollbar`、`test_seen_state_is_not_expressed_with_a_category_hue`、`test_css_escapes_survive_python_string_handling`、`test_every_candidate_appears_exactly_once`、`test_sections_are_in_order`。

- [ ] **Step 3：写新的测试。** 在 `# ---- 我已经看过：标记 ----` 那个位置（标题改成 `# ---- 已看过：生成时画出来（spec 2026-10-17 第 9 节）----`）放：

```python
def test_watched_films_are_drawn_as_seen_on_every_page(mixed):
    for html in (page(mixed, watched=frozenset({1})), page(mixed, latest=False, watched=frozenset({1}))):
        card = card_html(html, 1)
        assert card.startswith('<article class="film feature is-seen" id="film-1"')
        assert '<span class="sr-only">（已看过）</span>' in card
        assert "is-seen" not in card_html(html, 2)
        glance = re.search(r'<section id="glance".*?</section>', html, re.S).group(0)
        assert '<li class="is-seen" data-cat="horror" data-fid="1">' in glance
        assert '<li data-cat="japanese" data-fid="2">' in glance


def test_a_watched_version_marks_the_whole_film(settings):
    versions = [{"film_id": 1, "name": "A", "language": "English", "subtitle": ""},
                {"film_id": 62252, "name": "A (Spanish)", "language": "Spanish", "subtitle": ""}]
    edition = build_edition(settings, [recommended(1, "A", {"versions": versions})])
    assert "is-seen" in card_html(page(edition, watched=frozenset({62252})), 1)


def test_cards_link_to_the_edition_issues_instead_of_a_button(mixed):
    html = page(mixed, watched=frozenset({1}))
    assert "data-seen" not in html and html.count("<button") == 1          # 只剩导航里的「隐藏已看过」开关
    assert f'<a class="seen" href="{ISSUES}" rel="noopener">看过了？去 Issue 打勾</a>' in card_html(html, 2)
    assert f'<a class="seen" href="{ISSUES}" rel="noopener">去 Issue 撤销</a>' in card_html(html, 1)
    assert html.count('class="seen"') == 2                                   # 跳过、未能评估的片没有


def test_no_issue_link_without_a_repo(mixed):
    assert 'class="seen"' not in page(mixed, repo=None)


def test_hide_chip_counts_the_seen_cards_and_always_starts_hidden(mixed):
    def nav(html):
        return re.search(r'<nav class="jump".*?</nav>', html, re.S).group(0)
    two = nav(page(mixed, watched=frozenset({1, 2})))
    assert ('<button type="button" class="chip" data-hide-seen aria-label="隐藏已看过（2 部）" aria-pressed="false" hidden>'
            '<span class="lbl">隐藏已看过</span><span class="n">2</span></button>') in two
    assert 'aria-label="隐藏已看过（0 部）"' in nav(page(mixed))
    assert 'aria-label="隐藏已看过（0 部）"' in nav(page(mixed, watched=frozenset({3, 5})))   # 跳过、未能评估的片不算


def test_hide_script_is_on_every_page_and_the_old_storage_key_is_gone(mixed):
    latest, archived = page(mixed), page(mixed, latest=False)
    for html in (latest, archived):
        assert "film-radar:hide-seen:v1" in html and "film-radar:seen:v1" not in html
    assert 'getElementById("stale")' in latest and 'getElementById("stale")' not in archived
    assert 'id="stale"' not in archived


def test_hide_script_is_static_and_carries_no_page_data(settings):
    def script_of(edition):
        return re.search(r"<script>(\(function\(\)\{var HIDE=.*?)</script>", page(edition), re.S).group(1)
    one = build_edition(settings, [recommended(1, "First Title")])
    two = build_edition(settings, [recommended(2, "Another <b>Title</b>")])
    assert script_of(one) == script_of(two) == HIDE_SEEN_SCRIPT
    assert "First Title" not in HIDE_SEEN_SCRIPT


@_pytest.mark.skipif(not _shutil.which("node"), reason="需要 node 做语法检查")
def test_hide_script_is_valid_javascript(tmp_path):
    path = tmp_path / "hide.js"
    path.write_text(HIDE_SEEN_SCRIPT, encoding="utf-8")
    result = _subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_page_has_no_live_region_any_more(mixed):
    html = page(mixed)
    assert "data-live" not in html and "aria-live" not in html


def test_render_site_draws_the_watched_list_on_every_page(settings, tmp_path):
    older = build_edition(settings, [recommended(1, "Older Pick")], run_date=date(2026, 9, 24),
                          generated_at="2026-09-24T07:05:00-04:00")
    newer = build_edition(settings, [recommended(1, "Older Pick"), recommended(2, "Newer Pick")])
    render_site([older, newer], tmp_path, watched=frozenset({1}), repo=REPO)
    for path in (tmp_path / "index.html", tmp_path / "editions" / "2026-09-24.html"):
        html = path.read_text(encoding="utf-8")
        assert '<article class="film feature is-seen" id="film-1"' in html and ISSUES in html
```

（`test_a_watched_version_marks_the_whole_film` 依赖 `test_render.py` 已有的 `card_html`。上面的测试用到 `_pytest`、`_shutil`、`_subprocess`，它们在文件后半段才 import：把这一组测试放在 `# ---- 瑞士风配色……` 的 import 块之后。）

浏览器测试区（`browser = _pytest.mark.skipif(...)` 之后）放：

```python
PROBE = """
var q=function(s){return document.querySelector(s)};
var state=function(id){var c=document.getElementById("film-"+id);var g=q('[data-fid="'+id+'"]');
 return {card:c.classList.contains("is-seen"),row:g.classList.contains("is-seen"),shown:getComputedStyle(c).display!=="none"}};
"""
SEEN = frozenset({1})          # mixed 里 1 是重点推荐、2 是可以看


@browser
def test_browser_chip_appears_with_the_count_of_seen_films(mixed):
    result = _run_in_chrome(page(mixed, watched=SEEN), after=PROBE +
        'var chip=q("[data-hide-seen]");document.title="RESULT:"+JSON.stringify({one:state(1),two:state(2),'
        'chipHidden:chip.hidden,label:chip.getAttribute("aria-label"),pressed:chip.getAttribute("aria-pressed")});')
    assert result["one"] == {"card": True, "row": True, "shown": True}
    assert result["two"] == {"card": False, "row": False, "shown": True}
    assert result["chipHidden"] is False and result["label"] == "隐藏已看过（1 部）" and result["pressed"] == "false"


@browser
def test_browser_hide_seen_chip_hides_and_remembers(mixed):
    result = _run_in_chrome(page(mixed, watched=SEEN), after=PROBE +
        'var chip=q("[data-hide-seen]");chip.click();var a=state(1),row=getComputedStyle(q(\'[data-fid="1"]\')).display,other=state(2);'
        'var pressed=chip.getAttribute("aria-pressed"),label=chip.querySelector(".lbl").textContent,remembered=localStorage.getItem("film-radar:hide-seen:v1");'
        'chip.click();document.title="RESULT:"+JSON.stringify({a:a,row:row,other:other,pressed:pressed,label:label,remembered:remembered,again:state(1)});')
    assert result["a"]["shown"] is False and result["row"] == "none" and result["other"]["shown"] is True
    assert result["pressed"] == "true" and result["label"] == "显示已看过" and result["remembered"] == "1"
    assert result["again"]["shown"] is True


@browser
def test_browser_a_remembered_preference_hides_on_load(mixed):
    result = _run_in_chrome(page(mixed, watched=SEEN), before='localStorage.setItem("film-radar:hide-seen:v1","1");', after=PROBE +
        'document.title="RESULT:"+JSON.stringify({one:state(1),pressed:q("[data-hide-seen]").getAttribute("aria-pressed")});')
    assert result == {"one": {"card": True, "row": True, "shown": False}, "pressed": "true"}


@browser
def test_browser_a_leftover_preference_does_nothing_on_a_page_without_seen_films(mixed):
    result = _run_in_chrome(page(mixed), before='localStorage.setItem("film-radar:hide-seen:v1","1");', after=PROBE +
        'document.title="RESULT:"+JSON.stringify({chipHidden:q("[data-hide-seen]").hidden,'
        'root:document.documentElement.classList.contains("hide-seen"),two:state(2)});')
    assert result == {"chipHidden": True, "root": False, "two": {"card": False, "row": False, "shown": True}}


@browser
def test_browser_the_old_button_storage_is_neither_read_nor_deleted(mixed):
    result = _run_in_chrome(page(mixed), before='localStorage.setItem("film-radar:seen:v1",JSON.stringify({"2":1}));', after=PROBE +
        'document.title="RESULT:"+JSON.stringify({two:state(2),stored:localStorage.getItem("film-radar:seen:v1")});')
    assert result == {"two": {"card": False, "row": False, "shown": True}, "stored": '{"2":1}'}


@browser
def test_browser_hide_chip_works_when_only_writing_fails(mixed):
    result = _run_in_chrome(page(mixed, watched=SEEN), before=QUOTA, after=PROBE +
        'var chip=q("[data-hide-seen]");chip.click();var a=state(1).shown;chip.click();var b=state(1).shown;'
        'document.title="RESULT:"+JSON.stringify({a:a,b:b});')
    assert result == {"a": False, "b": True}


@browser
def test_browser_hide_chip_works_when_storage_is_unavailable(mixed):
    result = _run_in_chrome(page(mixed, watched=SEEN), before=DENIED, after=PROBE +
        'var chip=q("[data-hide-seen]");chip.click();'
        'document.title="RESULT:"+JSON.stringify({pressed:chip.getAttribute("aria-pressed"),root:document.documentElement.classList.contains("hide-seen"),'
        'card:getComputedStyle(document.getElementById("film-1")).display});')
    assert result == {"pressed": "true", "root": True, "card": "none"}


@browser
def test_browser_chip_state_is_carried_by_aria_pressed_not_by_a_changing_name(mixed):
    result = _run_in_chrome(page(mixed, watched=SEEN), after=
        'var c=document.querySelector("[data-hide-seen]");c.click();'
        'document.title="RESULT:"+JSON.stringify({label:c.getAttribute("aria-label"),pressed:c.getAttribute("aria-pressed")});')
    assert result == {"label": "隐藏已看过（1 部）", "pressed": "true"}


@browser
def test_browser_storage_clear_and_bfcache_restore_resync_the_preference(mixed):
    result = _run_in_chrome(page(mixed, watched=SEEN), before='localStorage.setItem("film-radar:hide-seen:v1","1");', after=PROBE +
        'var root=document.documentElement;var a=root.classList.contains("hide-seen");'
        'localStorage.clear();window.dispatchEvent(new StorageEvent("storage",{key:null}));var b=root.classList.contains("hide-seen");'
        'localStorage.setItem("film-radar:hide-seen:v1","1");window.dispatchEvent(new PageTransitionEvent("pageshow",{persisted:true}));'
        'document.title="RESULT:"+JSON.stringify({a:a,b:b,c:root.classList.contains("hide-seen")});')
    assert result == {"a": True, "b": False, "c": True}


@browser
def test_browser_pseudo_element_text_renders_what_the_css_says(mixed):
    result = _run_in_chrome(page(mixed, watched=SEEN), after=
        'var card=document.getElementById("film-1");var det=document.querySelector("#film-2 details");det.open=true;'
        'document.title="RESULT:"+JSON.stringify({stamp:getComputedStyle(card.querySelector(".eyebrow"),"::after").content,'
        'minus:getComputedStyle(det.querySelector("summary"),"::after").content,numContent:getComputedStyle(document.querySelector("h2"),"::before").content,'
        'inc:getComputedStyle(document.querySelector("h2")).counterIncrement,reset:getComputedStyle(document.querySelector("main")).counterReset,'
        'link:getComputedStyle(document.querySelector("#film-2 a.seen")).minHeight});')
    assert result["stamp"] == '"✓ 已看过"' and result["minus"] == '"−"' and result["numContent"] == "counter(sec, decimal-leading-zero)"
    assert result["inc"] == "sec 1" and result["reset"] == "sec 0"          # 章节序号：main 归零、每个 h2 加一
    assert result["link"] == "44px"                                         # 「去 Issue 打勾」的触控目标
```

`tests/test_main.py`：import 区加 `from film_radar.watched import dump_watched`，在 `test_cli_build_site_rebuilds_from_data` 后面加：

```python
def test_cli_build_site_marks_listed_films_and_links_to_the_issues(root, settings):
    write_edition(root, build_edition(settings, [recommended(1, "A"), recommended(2, "B")], run_date=date(2026, 10, 3)))
    (root / "data" / "watched.json").write_text(dump_watched({1: {"title": "A", "since": "s", "ids": [1]}}), encoding="utf-8")
    assert main(["--root", str(root), "build-site"]) == 0
    index = (root / "site" / "index.html").read_text(encoding="utf-8")
    assert '<article class="film feature is-seen" id="film-1"' in index
    assert '<article class="film feature" id="film-2"' in index
    assert "https://github.com/AKASHA-R/film-radar/issues?q=is%3Aissue+label%3Aedition" in index


def test_cli_build_site_fails_on_a_malformed_watched_list(root, settings):
    write_edition(root, build_edition(settings, [recommended(1, "A")], run_date=date(2026, 10, 3)))
    (root / "data" / "watched.json").write_text("{not json", encoding="utf-8")
    assert main(["--root", str(root), "build-site"]) == 1
    assert "失败环节：读取已看过名单" in (root / "out" / "failure.txt").read_text(encoding="utf-8")
```

- [ ] **Step 4：跑测试确认失败。**

Run：`.venv/bin/python -m pytest tests/test_render.py tests/test_main.py -q`
Expected：FAIL（`ImportError: cannot import name 'HIDE_SEEN_SCRIPT'`）

- [ ] **Step 5：实现 render。** `src/film_radar/render.py`：

1. import 改成 `from .watched import edition_marker, is_watched, task_line`（任务 3 已有，确认在）。
2. `_STYLE_BASE` 里 `.seen{...}` 那一行在 `color:var(--ink);` 后面加 `text-decoration:none;`；**删掉** `.seen[aria-pressed="true"]{background:var(--green);border-color:var(--green);color:var(--on-green)}` 那一行。
3. 整个 `SEEN_SCRIPT = r"""..."""` 换成：

```python
HIDE_SEEN_SCRIPT = r"""(function(){var HIDE="film-radar:hide-seen:v1",root=document.documentElement,chip=document.querySelector("[data-hide-seen]");
if(!chip)return;
/* 已看过的样式在生成页面时就画好了（名单在仓库里）；这段脚本只管「隐藏已看过」这个本机显示偏好。
   偏好以内存为准，存储只负责记住：存储读不了、写不了（配额满、无痕模式）时，这次访问里照常能切换 */
var n=document.querySelectorAll(".film.is-seen").length,hide=false;
function read(){try{return localStorage.getItem(HIDE)==="1"}catch(e){return null}}
function sync(){var h=read();if(h!==null)hide=h}
function persist(){try{localStorage.setItem(HIDE,hide?"1":"0")}catch(e){}}
function render(){var h=hide&&n>0;chip.hidden=n===0;chip.setAttribute("aria-pressed",h?"true":"false");
chip.querySelector(".lbl").textContent=h?"显示已看过":"隐藏已看过";root.classList.toggle("hide-seen",h)}
chip.addEventListener("click",function(){hide=!hide;persist();render()});
window.addEventListener("storage",function(e){if(e.key===null||e.key===HIDE){sync();render()}});
window.addEventListener("pageshow",function(e){if(e.persisted){sync();render()}});
sync();render()})();"""
```

4. 在 `safe_url` 后面加：

```python
def issues_url(repo: str) -> str:
    """所有 edition Issue 的列表：页面上「去 Issue 打勾」指向这里。"""
    return f"https://github.com/{repo}/issues?q=is%3Aissue+label%3Aedition"
```

5. `_film_card` 的签名改成 `def _film_card(film: dict, compact: bool, watched: frozenset[int] = frozenset(), link: str | None = None) -> str:`，把从 `fid = int(film["film_id"])` 到 `return` 结束这一段换成：

```python
    fid = int(film["film_id"])
    seen = is_watched(film, watched)
    # 「已看过」记在仓库的名单里，标记入口是 edition Issue 的勾选框（spec 2026-10-17）；页面只负责画出来、指过去
    label = "去 Issue 撤销" if seen else "看过了？去 Issue 打勾"
    to_issue = f'<a class="seen" href="{esc(link)}" rel="noopener">{label}</a>' if link else ""
    cta = f'<div class="cta">{buy}{to_issue}</div>'
    kind = "compact" if compact else "feature"
    state = " is-seen" if seen else ""
    hint = '<span class="sr-only">（已看过）</span>' if seen else ""
    return (
        f'<article class="film {kind}{state}" id="film-{fid}" data-film="{fid}" data-cat="{esc(card["category"])}">'
        f'<div class="top">{poster_html}<div class="head">'
        f'<div class="eyebrow"><span class="badge cat">{esc(category)}</span>{_meter(card["strength"])}</div>'
        f'<h3>{esc(film["title"])}{title_zh}{hint}</h3>'
        f"{_badges(film)}{lead}{_facts(film, compact)}{cta}"
        f"</div></div>{body}</article>"
    )
```

6. `_glance_row`、`_glance_section`、`_must_section`、`_ok_section`、`_nav` 换成：

```python
def _glance_row(film: dict, tier: str, watched: frozenset[int]) -> str:
    card = film["card"]
    fid = int(film["film_id"])
    seen = is_watched(film, watched)
    title_zh = f"<small>{esc(card['title_zh'])}</small>" if card["title_zh"] else ""
    hint = '<span class="sr-only">（已看过）</span>' if seen else ""
    tier_tag = '<span class="g-tier">重点</span>' if tier == "must" else ""
    hot = "".join(f'<span class="g-hot {kind}">{esc(label)}</span>' for kind, label in _urgency(film))
    category = CATEGORY_LABELS.get(card["category"], card["category"])
    state = ' class="is-seen"' if seen else ""
    return (
        f'<li{state} data-cat="{esc(card["category"])}" data-fid="{fid}"><a href="#film-{fid}"><i class="g-dot"></i>'
        f'<span class="g-title">{esc(film["title"])}{title_zh}{hint}</span>'
        f'<span class="g-meta">{tier_tag}<span class="g-cat">{esc(category)}</span>'
        f'<span>{esc(status_text(film))}</span>{hot}{_meter(card["strength"])}</span></a></li>'
    )


def _glance_section(must: list[dict], ok: list[dict], watched: frozenset[int]) -> str:
    if not must and not ok:
        return ""
    rows = ("".join(_glance_row(f, "must", watched) for f in _by_strength(must))
            + "".join(_glance_row(f, "ok", watched) for f in _by_strength(ok)))
    return f'<section id="glance"><h2>本期速览</h2><ul class="glance">{rows}</ul></section>'


def _must_section(films: list[dict], watched: frozenset[int], link: str | None) -> str:
    if not films:
        return '<h2 id="must">重点推荐</h2><p class="empty">本期没有重点推荐。</p>'
    cards = "".join(_film_card(f, False, watched, link) for f in _by_strength(films))
    return f'<h2 id="must">重点推荐{_count(len(films))}</h2>' + cards


def _ok_section(films: list[dict], watched: frozenset[int], link: str | None) -> str:
    if not films:
        return ""
    cards = "".join(_film_card(f, True, watched, link) for f in _by_strength(films))
    return f'<h2 id="ok">可以看{_count(len(films))}</h2><div class="grid">{cards}</div>'
```

`_nav` 的签名改成 `def _nav(has_glance: bool, must: int, ok: int, skip: int, seen: int) -> str:`，开关那两行换成：

```python
    # 开关生成时一律带 hidden：脚本跑起来、本页有已看过的片才显示，脚本不可用时不会留下点不动的按钮
    links.append(f'<button type="button" class="chip" data-hide-seen aria-label="隐藏已看过（{seen} 部）" aria-pressed="false" hidden>'
                 f'<span class="lbl">隐藏已看过</span><span class="n">{seen}</span></button>')
```

7. `render_edition` 和 `render_site` 换成：

```python
def render_edition(edition: dict, number: int, archive: list[tuple[str, int]], *,
                   is_latest: bool, prefix: str, watched: frozenset[int] = frozenset(),
                   repo: str | None = None) -> str:
    films = edition["films"]

    def of(outcome: str) -> list[dict]:
        return [f for f in films if f["outcome"] == outcome]

    musts, oks = of("must"), of("ok")
    link = issues_url(repo) if repo else None
    seen = sum(1 for f in musts + oks if is_watched(f, watched))
    title = f"多伦多院线 · 第 {number} 期"
    glance = _glance_section(musts, oks, watched)
    body = (
        glance
        + _must_section(musts, watched, link)
        + _ok_section(oks, watched, link)
        + _failed_section(of("review_failed"))
        + _skip_section(of("skip"))
        + _events_section(edition["filtered_events"])
        + _footer(edition, archive, is_latest, prefix)
    )
    return (
        '<!DOCTYPE html><html lang="zh-Hans"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="only light">'
        '<meta name="robots" content="noindex">'
        f"<title>{esc(title)}</title><style>{STYLE}</style></head>"
        f"<body>{_hero(edition, title, is_latest)}"
        f"{_nav(bool(glance), len(musts), len(oks), len(of('skip')), seen)}"
        f"<main>{body}</main>"
        f"<script>{HIDE_SEEN_SCRIPT}</script></body></html>"
    )


def render_site(editions: list[dict], out_dir: Path, *, watched: frozenset[int] = frozenset(),
                repo: str | None = None) -> None:
    """watched 用在所有页面上（包括往期）：名单是现在的名单，不是当期的。"""
    if not editions:
        raise ValueError("没有任何一期数据，无法生成站点")
    ordered = sorted(editions, key=lambda e: e["edition_id"])
    numbered = [(edition, i + 1) for i, edition in enumerate(ordered)]
    archive = [(edition["edition_id"], number) for edition, number in reversed(numbered)]
    pages = out_dir / "editions"
    pages.mkdir(parents=True, exist_ok=True)
    for edition, number in numbered:
        page = render_edition(edition, number, archive, is_latest=False, prefix="../", watched=watched, repo=repo)
        (pages / f'{edition["edition_id"]}.html').write_text(page, encoding="utf-8")
    latest, number = numbered[-1]
    index = render_edition(latest, number, archive, is_latest=True, prefix="", watched=watched, repo=repo)
    (out_dir / "index.html").write_text(index, encoding="utf-8")
```

- [ ] **Step 6：实现 main。** `src/film_radar/main.py`：import 区加 `from .watched import WatchedError, load_watched_file, watched_ids`；`STAGES` 里 `AssembleError: "汇总",` 后面加 `WatchedError: "读取已看过名单",`；`_run` 里 `render_site(editions, root / "site")` 改成 `render_site(editions, root / "site", repo=settings.repo)`（任务 9 再加 `watched`）；`_build_site` 换成：

```python
def _build_site(root: Path) -> int:
    """工作流部署页面走这里：已看过以仓库里的名单为准。"""
    settings = load_settings(root / "config" / "settings.toml")
    watched = watched_ids(load_watched_file(root / "data" / "watched.json"))
    render_site(load_editions(root / "data" / "editions"), root / "site", watched=watched, repo=settings.repo)
    return 0
```

- [ ] **Step 7：跑测试确认通过（含浏览器测试）。**

Run：`.venv/bin/python -m pytest -q`
Expected：全部 PASS；本机有 Chrome，`-rs` 看一眼浏览器测试没有被跳过：`.venv/bin/python -m pytest tests/test_render.py -q -rs | tail -3`

- [ ] **Step 8：验红。** ①把 `HIDE_SEEN_SCRIPT` 里 `var h=hide&&n>0` 改成 `var h=hide`，`sh scripts/redcheck.sh tests/test_render.py` 应当 FAIL（`test_browser_a_leftover_preference_does_nothing_on_a_page_without_seen_films`）；还原。②把 `_STYLE_BASE` 的 `r"""` 改成 `"""`，应当 FAIL（`test_css_escapes_survive_python_string_handling`）；还原。

- [ ] **Step 9：提交。**

```bash
git -C /Users/minggao/Projects/film-radar-watched add src/film_radar/render.py src/film_radar/main.py tests/test_render.py tests/test_main.py
git -C /Users/minggao/Projects/film-radar-watched commit -m "feat: 页面按名单画出已看过，按钮换成去 Issue 打勾的链接

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8：页面——「看过、仍在映」折叠区

**Files：**
- Modify：`src/film_radar/render.py`
- Test：`tests/test_render.py`

**Interfaces：**
- Consumes：edition 的 `watched_showing`（形状见任务 2 `split_watched`；老数据没有这个键）；任务 2 的 `is_watched`
- Produces：`_watched_section(entries: list[dict], watched: frozenset[int]) -> str`，在页面上位于「跳过的片」之后、「已过滤的非电影活动」之前

- [ ] **Step 1：写失败的测试。** 追加到 `tests/test_render.py`（放在 `test_skip_list_shows_reasons` 附近）：

```python
SHOWING = [{"film_id": 9, "title": "Pan's Labyrinth", "status": "now_playing", "release_date": "2006-10-11",
            "weeks_in_release": None, "detail_url": "https://www.cineplex.com/movie/pans-labyrinth", "version_ids": [9]}]


def with_showing(edition, entries=SHOWING):
    edition["watched_showing"] = [dict(e) for e in entries]
    return edition


def watched_fold(html):
    return re.search(r'<details class="fold"><summary>看过、仍在映.*?</details>', html, re.S).group(0)


def test_watched_fold_sits_between_skipped_and_filtered_events(mixed):
    html = page(with_showing(mixed), watched=frozenset({9}))
    order = [html.index(m) for m in ("跳过的片（2）", "看过、仍在映（1）", "已过滤的非电影活动（1）")]
    assert order == sorted(order)
    nav = re.search(r'<nav class="jump".*?</nav>', html, re.S).group(0)
    hero = re.search(r"<header.*?</header>", html, re.S).group(0)
    assert "看过、仍在映" not in nav and "看过、仍在映" not in hero


def test_watched_fold_lists_title_status_and_link(mixed):
    fold = watched_fold(page(with_showing(mixed), watched=frozenset({9})))
    assert "<b>Pan&#x27;s Labyrinth</b> · 重映（2006 年上映）" in fold
    assert '<a href="https://www.cineplex.com/movie/pans-labyrinth" rel="noopener">Cineplex</a>' in fold
    assert "已撤销" not in fold


def test_a_film_unticked_since_the_edition_is_marked_revoked(mixed):
    fold = watched_fold(page(with_showing(mixed), watched=frozenset()))
    assert '<span class="revoked">已撤销，下期会重新评估</span>' in fold


def test_watched_fold_absent_when_empty_or_missing(mixed):
    """老数据没有 watched_showing 字段（Review Focus 4）。"""
    mixed.pop("watched_showing", None)
    assert "看过、仍在映" not in page(mixed)
    assert "看过、仍在映" not in page(with_showing(mixed, []))


def test_watched_fold_escapes_text_and_drops_unsafe_links(mixed):
    hostile = [{**SHOWING[0], "title": "<x-mark>", "detail_url": "javascript:alert(1)"}]
    html = page(with_showing(mixed, hostile))
    assert "<x-mark>" not in html and "&lt;x-mark&gt;" in html and "javascript:" not in html
```

- [ ] **Step 2：跑测试确认失败。**

Run：`.venv/bin/python -m pytest tests/test_render.py -q -k watched_fold or revoked`
Expected：FAIL（页面里没有「看过、仍在映」）

- [ ] **Step 3：实现。** `src/film_radar/render.py`：`_STYLE_BASE` 里 `ul.plain li{...}` 那一行下面加一行 `.revoked{margin-left:10px;color:var(--warn);font-weight:700}`。在 `_skip_section` 后面加：

```python
def _watched_section(entries: list[dict], watched: frozenset[int]) -> str:
    """当期因为看过而没参加评估、但仍在映或即将上映的片（spec 2026-10-17 第 9 节）。
    生成页面时名单里已经没有它（用户后来撤销了），就注明下期会重新评估。"""
    if not entries:
        return ""
    rows = []
    for entry in entries:
        url = safe_url(entry["detail_url"])
        link = f' · <a href="{esc(url)}" rel="noopener">Cineplex</a>' if url else ""
        revoked = "" if is_watched(entry, watched) else '<span class="revoked">已撤销，下期会重新评估</span>'
        rows.append(f'<li><b>{esc(entry["title"])}</b> · {esc(status_text(entry))}{link}{revoked}</li>')
    return (f'<details class="fold"><summary>看过、仍在映（{len(entries)}）</summary>'
            f'<ul class="plain">{"".join(rows)}</ul></details>')
```

`render_edition` 的 `body` 里，`+ _skip_section(of("skip"))` 后面加一行 `+ _watched_section(edition.get("watched_showing", []), watched)`。

- [ ] **Step 4：跑测试确认通过。**

Run：`.venv/bin/python -m pytest -q`
Expected：全部 PASS（`test_style_has_no_tiny_text`、`test_brand_backgrounds_always_come_with_their_text_colour` 也要过）

- [ ] **Step 5：提交。**

```bash
git -C /Users/minggao/Projects/film-radar-watched add src/film_radar/render.py tests/test_render.py
git -C /Users/minggao/Projects/film-radar-watched commit -m "feat: 页面新增「看过、仍在映」折叠区

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9：出刊流水线接入有效名单

**Files：**
- Modify：`src/film_radar/assemble.py`、`src/film_radar/main.py`
- Test：`tests/test_assemble.py`、`tests/test_main.py`

**Interfaces：**
- Consumes：任务 2 的 `split_watched`、`load_watched`、`watched_ids`；任务 4 的 `build_catalog`、`sync`；任务 6 的 `client_from_env`、`GitHubError`、`helpers.FakeGitHub`；任务 7 的 `render_site(..., watched=, repo=)`；任务 3 的 `issue_body(..., watched)`
- Produces：
  - `assemble(..., watched_showing: list[dict] | None = None)`，edition 新增键 `"watched_showing"`（总是存在，默认 `[]`）
  - `run_pipeline(..., watched: frozenset[int] = frozenset())`
  - `main.github_client`（模块级，默认 `client_from_env`，测试里替换）
  - `main.remote_watched_text(root: Path) -> str | None`（模块级，测试里替换）
  - `main.effective_watched(root, settings, editions, now: datetime) -> frozenset[int]`
  - `STAGES[GitHubError] == "GitHub 接口"`

- [ ] **Step 1：写失败的测试（assemble）。** 追加到 `tests/test_assemble.py`：

```python
def test_watched_showing_is_carried_but_not_counted(settings):
    showing = [{"film_id": 9, "title": "Seen", "status": "now_playing", "release_date": "2006-10-11",
                "weeks_in_release": None, "detail_url": "https://www.cineplex.com/movie/seen", "version_ids": [9]}]
    edition = assemble(**kwargs(settings, watched_showing=showing))
    assert edition["watched_showing"] == showing
    assert edition["counts"] == {"must": 1, "ok": 0, "skip": 1, "review_failed": 0}


def test_watched_showing_defaults_to_empty(settings):
    assert assemble(**kwargs(settings))["watched_showing"] == []
```

- [ ] **Step 2：写失败的测试（流水线）。** `tests/test_main.py`：

1. import 区：`from film_radar.main import (...)` 里加 `remote_watched_text`（保持按字母序），加 `import subprocess`，加 `from film_radar.render import render_edition`、`from film_radar.watched import WatchedError, dump_watched`（任务 7 已加 `dump_watched` 就合并），`from helpers import ...` 里加 `FakeGitHub, task_issue`。
2. `FakeCineplex.__init__` 加 `self.detail_calls = []`，`movie_details` 第一行加 `self.detail_calls.append(film_url)`。
3. `pipeline()` 改成：

```python
def pipeline(settings, client=None, caller=None, previous=None, triage_caller=None, watched=frozenset()):
    return run_pipeline(
        client=client or FakeCineplex(), caller=caller or ScriptedCaller(keep={61994, 38459}),
        triage_caller=triage_caller,
        settings=settings, taste=TASTE, run_date=RUN, previous=previous,
        generated_at="2026-10-03T07:05:00-04:00", watched=watched,
    )
```

4. `use_fakes()` 改成：

```python
def use_fakes(monkeypatch, client=None, caller=None, github=None, watched_text=None):
    pair = (client or FakeCineplex(), caller or ScriptedCaller(keep={61994, 38459}))
    monkeypatch.setattr(main_module, "build_clients", lambda settings: (pair[0], pair[1], pair[1]))   # 两个阶段共用一个假 caller
    fake_github = github if github is not None else FakeGitHub()
    monkeypatch.setattr(main_module, "github_client", lambda settings: fake_github)
    monkeypatch.setattr(main_module, "remote_watched_text", lambda root: watched_text)
    return pair
```

5. 在「数据核对」那组测试后面加：

```python
# ---- 已看过（spec 2026-10-17 第 8 节）----

NINJA_URL = next(m["filmUrl"] for m in MOVIES if m["id"] == 61994)


def test_watched_films_skip_details_triage_and_review(settings):
    client, caller = FakeCineplex(), ScriptedCaller(keep={61994, 38459})
    edition = pipeline(settings, client=client, caller=caller, watched=frozenset({61995}))   # 只看过日语版，整部片都算看过
    sent = json.loads(caller.calls[0]["user"].split("<candidates>")[1].split("</candidates>")[0])
    assert 61994 not in {c["film_id"] for c in sent}
    assert NINJA_URL not in client.detail_calls
    assert sum(1 for c in caller.calls if c.get("tools")) == 1           # 只有 Digger 做了联网精评
    assert 61994 not in {f["film_id"] for f in edition["films"]}
    assert edition["watched_showing"] == [{
        "film_id": 61994, "title": "Ninja Scroll 4K", "status": "coming_soon", "release_date": "2026-10-04",
        "weeks_in_release": None, "detail_url": "https://www.cineplex.com/movie/ninja-scroll-4k",
        "version_ids": [61994, 61995],
    }]
    assert sum(edition["counts"].values()) == len(EXPECTED_CANDIDATES) - 1


def test_sanity_counts_candidates_before_watched_films_are_removed(settings):
    caller = ScriptedCaller()
    edition = pipeline(settings, caller=caller, watched=frozenset(EXPECTED_CANDIDATES))
    assert edition["films"] == [] and len(edition["watched_showing"]) == len(EXPECTED_CANDIDATES)
    assert edition["counts"] == {"must": 0, "ok": 0, "skip": 0, "review_failed": 0}
    assert caller.calls == []                                            # 一部都不用评，不调 Claude
    render_edition(edition, 1, [(edition["edition_id"], 1)], is_latest=True, prefix="")   # 0 部片也能生成页面
```

6. 在「命令行」那组测试末尾加：

```python
def test_cli_skip_week_reads_nothing_from_github(root, monkeypatch):
    def explode(*args):
        raise AssertionError("跳过周不应该读 GitHub、也不应该建客户端")

    for name in ("build_clients", "github_client", "remote_watched_text"):
        monkeypatch.setattr(main_module, name, explode)
    assert main(["--root", str(root), "run", "--date", "2026-10-15"]) == 0


def test_cli_reads_the_list_before_the_issues(root, monkeypatch):
    """反过来的话，两次读取之间刚好完成一次同步（先提交名单、后改写 Issue），会同时漏掉两边的这个勾。"""
    order = []

    class Recording(FakeGitHub):
        def edition_issues(self):
            order.append("issues")
            return super().edition_issues()

    use_fakes(monkeypatch, github=Recording())
    monkeypatch.setattr(main_module, "remote_watched_text", lambda root: order.append("list"))
    assert main(["--root", str(root), "run", "--manual", "--date", "2026-10-03"]) == 0
    assert order == ["list", "issues"]


def test_cli_a_pending_tick_counts_but_nothing_is_written_back(root, monkeypatch, settings):
    write_edition(root, build_edition(settings, [recommended(61994, "Ninja Scroll 4K")], run_date=date(2026, 9, 19)))
    github = FakeGitHub({4: task_issue("2026-09-19", (61994, True, False))})
    use_fakes(monkeypatch, github=github)
    assert main(["--root", str(root), "run", "--manual", "--date", "2026-10-03"]) == 0
    edition = json.loads((root / "data" / "editions" / "2026-10-03.json").read_text(encoding="utf-8"))
    assert [e["film_id"] for e in edition["watched_showing"]] == [61994]
    assert "- [x] **Ninja Scroll 4K** · 10月4日上映 <!-- film:61994 bot:1 -->" in (root / "out" / "issue_body.md").read_text(encoding="utf-8")
    assert not (root / "data" / "watched.json").exists()                 # 出刊只读：名单由同步提交
    assert github.updates == []                                          # 也不改 Issue
    index = (root / "site" / "index.html").read_text(encoding="utf-8")
    assert "看过、仍在映（1）" in index


def test_cli_an_edition_where_everything_was_watched_still_publishes(root, monkeypatch):
    films = {i: {"title": str(i), "since": "s", "ids": [i]} for i in EXPECTED_CANDIDATES}
    _, caller = use_fakes(monkeypatch, watched_text=dump_watched(films))
    assert main(["--root", str(root), "run", "--manual", "--date", "2026-10-03"]) == 0
    body = (root / "out" / "issue_body.md").read_text(encoding="utf-8")
    assert "本期没有重点推荐。" in body and body.count("- [x]") == len(EXPECTED_CANDIDATES)
    assert (root / "site" / "index.html").exists() and caller.calls == []


def test_cli_without_a_token_fails_before_any_claude_call(root, monkeypatch):
    def explode(settings):
        raise AssertionError("不应该建 Claude 客户端")

    monkeypatch.setattr(main_module, "build_clients", explode)
    monkeypatch.setattr(main_module, "remote_watched_text", lambda root: None)
    assert main(["--root", str(root), "run", "--manual", "--date", "2026-10-03"]) == 1
    failure = (root / "out" / "failure.txt").read_text(encoding="utf-8")
    assert "失败环节：GitHub 接口" in failure and "GITHUB_TOKEN" in failure
    assert not (root / "data").exists()


def test_cli_a_malformed_watched_list_fails_before_any_claude_call(root, monkeypatch):
    use_fakes(monkeypatch, watched_text="{not json")
    monkeypatch.setattr(main_module, "build_clients", lambda settings: (_ for _ in ()).throw(AssertionError("不应该建客户端")))
    assert main(["--root", str(root), "run", "--manual", "--date", "2026-10-03"]) == 1
    assert "失败环节：读取已看过名单" in (root / "out" / "failure.txt").read_text(encoding="utf-8")


def test_cli_an_unparsable_issue_does_not_stop_the_edition(root, monkeypatch, capsys):
    """Review Focus 5：坏 Issue 里的勾不采用，出刊照常完成。"""
    unparsable = task_issue("2026-09-19", (61994, True, False)).replace("bot:0", "bot:7")
    use_fakes(monkeypatch, github=FakeGitHub({4: unparsable}))
    assert main(["--root", str(root), "run", "--manual", "--date", "2026-10-03"]) == 0
    assert "Issue #4 无法解析" in capsys.readouterr().out
    edition = json.loads((root / "data" / "editions" / "2026-10-03.json").read_text(encoding="utf-8"))
    assert 61994 in {f["film_id"] for f in edition["films"]}


# ---- 从 origin/main 取最新名单（用本机临时 git 仓库，不联网）----

def _git(*args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "init.defaultBranch=main", *args],
                   check=True, capture_output=True)


@pytest.fixture
def origin(tmp_path):
    bare, writer = tmp_path / "origin.git", tmp_path / "writer"
    _git("init", "--bare", str(bare))
    _git("clone", str(bare), str(writer))
    (writer / "README").write_text("x", encoding="utf-8")
    _git("-C", str(writer), "add", "-A")
    _git("-C", str(writer), "commit", "-m", "init")
    _git("-C", str(writer), "push", "origin", "HEAD:main")
    return bare, writer


def test_remote_watched_text_reads_origin_main_not_the_checkout(origin, tmp_path):
    bare, writer = origin
    (writer / "data").mkdir()
    (writer / "data" / "watched.json").write_text("old\n", encoding="utf-8")
    _git("-C", str(writer), "add", "-A")
    _git("-C", str(writer), "commit", "-m", "old")
    _git("-C", str(writer), "push", "origin", "HEAD:main")
    reader = tmp_path / "reader"
    _git("clone", str(bare), str(reader))
    (writer / "data" / "watched.json").write_text("new\n", encoding="utf-8")
    _git("-C", str(writer), "commit", "-am", "new")
    _git("-C", str(writer), "push", "origin", "HEAD:main")
    assert (reader / "data" / "watched.json").read_text(encoding="utf-8") == "old\n"
    assert remote_watched_text(reader) == "new\n"


def test_remote_watched_text_is_none_when_main_has_no_list(origin, tmp_path):
    bare, _ = origin
    reader = tmp_path / "reader"
    _git("clone", str(bare), str(reader))
    assert remote_watched_text(reader) is None


def test_remote_watched_text_fails_loudly_without_a_remote(tmp_path):
    with pytest.raises(WatchedError, match="git fetch"):
        remote_watched_text(tmp_path)
```

7. `test_cli_success_writes_everything` 末尾加一行 `assert "label%3Aedition" in (root / "site" / "index.html").read_text(encoding="utf-8")`。

- [ ] **Step 3：跑测试确认失败。**

Run：`.venv/bin/python -m pytest tests/test_assemble.py tests/test_main.py -q`
Expected：FAIL（`ImportError: cannot import name 'remote_watched_text'`；`assemble()` 不认 `watched_showing`）

- [ ] **Step 4：实现 assemble。** `src/film_radar/assemble.py`：`assemble` 签名末尾加 `watched_showing: list[dict] | None = None`；返回的 dict 里 `"orphan_ids": list(orphan_ids),` 后面加：

```python
        # 因为看过而没参加评估、但仍在映的片（spec 2026-10-17 第 8 节）。不进 films、不进 counts、不参加总数核对
        "watched_showing": list(watched_showing or []),
```

- [ ] **Step 5：实现 main。** `src/film_radar/main.py`：

1. import 区加 `import subprocess`；`from .github import GitHubError, client_from_env`；把任务 7 加的 watched import 换成 `from .watched import WatchedError, build_catalog, load_watched, load_watched_file, split_watched, sync, watched_ids`。
2. `STAGES` 里 `WatchedError: "读取已看过名单",` 后面加 `GitHubError: "GitHub 接口",`。
3. `run_pipeline` 签名末尾加 `watched: frozenset[int] = frozenset()`，函数体改成在 `check_sanity(...)` 之后、`attach_details(...)` 之前插入一行，并把 `assemble(...)` 调用加上 `watched_showing`：

```python
    check_sanity(movies, theatres, showtimes, candidates)        # 用排除前的候选，「候选为 0」的含义不变
    candidates, watched_showing = split_watched(candidates, watched)
    attach_details(client, candidates)                             # 看过的片不抓详情页、不粗筛、不精评
```

```python
    return assemble(
        candidates=candidates, verdicts=verdicts, reviews=reviews, previous=previous,
        filtered_events=filtered_events, orphan_ids=orphan_ids, usage=usage,
        run_date=run_date, generated_at=generated_at, settings=settings, watched_showing=watched_showing,
    )
```

4. `build_clients` 之后加：

```python
github_client = client_from_env        # 测试里换成替身，不联网


def remote_watched_text(root: Path) -> str | None:
    """origin/main 上最新的 data/watched.json；那里没有这个文件时返回 None。
    出刊要跑十几分钟，检出时的那份可能已经旧了，所以先 fetch 再读（spec 第 8 节）。"""
    def git(*args: str):
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8")

    fetched = git("fetch", "--quiet", "origin", "main")
    if fetched.returncode != 0:
        raise WatchedError(f"取最新名单失败（git fetch）：{fetched.stderr.strip()}")
    listed = git("ls-tree", "--name-only", "FETCH_HEAD", "--", "data/watched.json")
    if listed.returncode != 0:
        raise WatchedError(f"取最新名单失败（git ls-tree）：{listed.stderr.strip()}")
    if not listed.stdout.strip():
        return None
    shown = git("show", "FETCH_HEAD:data/watched.json")
    if shown.returncode != 0:
        raise WatchedError(f"取最新名单失败（git show）：{shown.stderr.strip()}")
    return shown.stdout


def effective_watched(root: Path, settings: Settings, editions: list[dict], now: datetime) -> frozenset[int]:
    """名单＋Issue 里还没同步的勾，只在内存里算，不提交名单、不改 Issue（spec 第 6 节末段、第 8 节）。
    先读名单、后读 Issue。"""
    films = load_watched(remote_watched_text(root))
    issues = github_client(settings).edition_issues()
    result = sync(films, issues, build_catalog(editions), now.isoformat(timespec="seconds"))
    for problem in result.problems:
        print(f"Issue #{problem.issue} 无法解析，这一期不采用它里面的勾：{'；'.join(problem.reasons)}")
    return watched_ids(result.films)
```

5. `_run` 里从 `taste = ...` 到 `edition = run_pipeline(...)` 这一段换成：

```python
    taste = (root / "config" / "taste_profile.md").read_text(encoding="utf-8")
    editions_dir = root / "data" / "editions"
    editions = load_editions(editions_dir)
    # 在任何 Claude 调用之前：读名单或 Issue 失败不花钱
    watched = effective_watched(root, settings, editions, now)
    previous = previous_edition(editions, run_date)
    client, caller, triage_caller = build_clients(settings)
    edition = run_pipeline(
        client=client, caller=caller, triage_caller=triage_caller, settings=settings, taste=taste, run_date=run_date,
        previous=previous, generated_at=now.isoformat(timespec="seconds"), watched=watched,
    )
```

并把后面两处改成：`render_site(editions, root / "site", watched=watched, repo=settings.repo)`、`issue_body(edition, number, settings.page_url, watched)`。（`_run` 里写完新一期后重新 `editions = load_editions(editions_dir)` 那一行保留。）

- [ ] **Step 6：跑测试确认通过。**

Run：`.venv/bin/python -m pytest -q`
Expected：全部 PASS（原来的 `test_cli_skip_week_does_nothing`、`test_cli_failure_leaves_no_edition_and_no_site` 等不改也要过）

- [ ] **Step 7：验红。** ①把 `effective_watched` 里两行读取的顺序对调（先 `issues = ...` 后 `films = ...`），`sh scripts/redcheck.sh tests/test_main.py` 应当 FAIL（`test_cli_reads_the_list_before_the_issues`）；还原。②把 `check_sanity` 那一行挪到 `split_watched` 之后，应当 FAIL（`test_sanity_counts_candidates_before_watched_films_are_removed`）；还原。

- [ ] **Step 8：提交。**

```bash
git -C /Users/minggao/Projects/film-radar-watched add src/film_radar/assemble.py src/film_radar/main.py tests/test_assemble.py tests/test_main.py
git -C /Users/minggao/Projects/film-radar-watched commit -m "feat: 出刊前排除看过的片，名单与未同步的勾只读不写

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10：同步子命令 `sync-watched` 与 `apply-watched-rewrites`

**Files：**
- Modify：`src/film_radar/main.py`
- Create：`tests/test_sync_cli.py`

**Interfaces：**
- Consumes：任务 3 的 `Issue`、`parse_issue`、`IssueFormatError`；任务 4 的 `sync`、`build_catalog`、`Rewrite`、`Problem`；任务 5 的 `apply_rewrites`；任务 2 的 `dump_watched`；任务 9 的 `github_client`
- Produces（工作流用）：
  - `python -m film_radar.main sync-watched`：写 `data/watched.json`（有变化时）、`out/watched_plan.json`（`{"rewrites": [{"issue", "film_id", "observed", "target"}]}`）、`out/problems/issue-<N>.md`（第一行是失败 Issue 标题，其余是正文）、`GITHUB_OUTPUT` 里 `changed=true|false`、运行摘要
  - `python -m film_radar.main apply-watched-rewrites`：读 `out/watched_plan.json`，逐个 Issue 重新读取、合并、PATCH，每个 Issue 最多试 3 次；仍失败的以「GitHub 接口」环节退出 1，`out/failure.txt` 写明哪几个 Issue 和提醒
  - `REWRITE_ATTEMPTS = 3`

- [ ] **Step 1：写失败的测试。** 新建 `tests/test_sync_cli.py`：

```python
import json
import shutil

import pytest

from film_radar import main as main_module
from film_radar.main import main
from film_radar.watched import Issue, Line, load_watched_file, parse_issue
from helpers import ROOT, FakeGitHub, task_issue, toggle

TITLES = {1: "One", 2: "Two", 3: "Three"}


@pytest.fixture
def root(tmp_path, monkeypatch):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    editions = tmp_path / "data" / "editions"
    editions.mkdir(parents=True)
    for edition_id, ids in (("2026-10-03", [1, 2]), ("2026-10-08", [1, 3])):
        films = [{"film_id": i, "title": TITLES[i], "versions": [{"film_id": i}]} for i in ids]
        (editions / f"{edition_id}.json").write_text(json.dumps({"edition_id": edition_id, "films": films}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "gh_output"))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "gh_summary"))
    monkeypatch.setattr(main_module.time, "sleep", lambda seconds: None)
    return tmp_path


def use_github(monkeypatch, github):
    monkeypatch.setattr(main_module, "github_client", lambda settings: github)
    return github


def sync_watched(root):
    return main(["--root", str(root), "sync-watched"])


def apply_rewrites(root):
    return main(["--root", str(root), "apply-watched-rewrites"])


def lines(github, number):
    return parse_issue(Issue(number, github.bodies[number])).lines


def read(path):
    return path.read_text(encoding="utf-8")


def test_a_tick_is_recorded_and_spread_to_every_issue(root, monkeypatch):
    github = use_github(monkeypatch, FakeGitHub({2: task_issue("2026-10-03", (1, True, False)),
                                                 5: task_issue("2026-10-08", (1, False, False), (3, False, False))}))
    assert sync_watched(root) == 0
    films = load_watched_file(root / "data" / "watched.json")
    assert list(films) == [1] and films[1]["title"] == "One" and films[1]["since"][-6] in "+-"
    assert "changed=true" in read(root / "gh_output")
    assert "#2 勾上 1" in read(root / "gh_summary")
    assert apply_rewrites(root) == 0
    assert lines(github, 2) == (Line(1, True, True),)
    assert lines(github, 5) == (Line(1, True, True), Line(3, False, False))

    before = read(root / "data" / "watched.json")
    github.updates.clear()
    assert sync_watched(root) == 0 and apply_rewrites(root) == 0       # 第二轮：没有操作、没有改写
    assert github.updates == [] and read(root / "data" / "watched.json") == before
    assert json.loads(read(root / "out" / "watched_plan.json")) == {"rewrites": []}
    assert "changed=false" in read(root / "gh_output").splitlines()[-1]


def test_nothing_to_do_creates_no_list(root, monkeypatch):
    use_github(monkeypatch, FakeGitHub({5: task_issue("2026-10-08", (1, False, False))}))
    assert sync_watched(root) == 0
    assert not (root / "data" / "watched.json").exists()


def test_an_unparsable_issue_is_reported_and_the_rest_still_sync(root, monkeypatch):
    unparsable = task_issue("2026-10-03", (1, True, False)).replace("bot:0", "bot:9")
    use_github(monkeypatch, FakeGitHub({4: unparsable, 5: task_issue("2026-10-08", (3, True, False))}))
    assert sync_watched(root) == 0
    assert list(load_watched_file(root / "data" / "watched.json")) == [3]
    problem = read(root / "out" / "problems" / "issue-4.md").split("\n")
    assert problem[0] == "已看过同步：Issue #4 无法解析"
    assert any("格式不对" in row for row in problem)
    assert "Issue #4 无法解析" in read(root / "gh_summary")


def test_a_malformed_list_fails_and_changes_nothing(root, monkeypatch):
    (root / "data" / "watched.json").write_text("{not json", encoding="utf-8")
    use_github(monkeypatch, FakeGitHub({5: task_issue("2026-10-08", (3, True, False))}))
    assert sync_watched(root) == 1
    assert "失败环节：读取已看过名单" in read(root / "out" / "failure.txt")
    assert read(root / "data" / "watched.json") == "{not json"
    assert not (root / "out" / "watched_plan.json").exists()


def test_failed_rewrites_fail_the_run_and_the_next_sync_repairs_them(root, monkeypatch):
    github = use_github(monkeypatch, FakeGitHub({2: task_issue("2026-10-03", (1, True, False)),
                                                 5: task_issue("2026-10-08", (1, False, False))}, fail_updates=3))
    assert sync_watched(root) == 0
    assert apply_rewrites(root) == 1
    failure = read(root / "out" / "failure.txt")
    assert "失败环节：GitHub 接口" in failure and "#2" in failure and "不要在这几个 Issue 里撤销" in failure
    assert github.calls.count(("update_body", 2)) == 3                 # 每个 Issue 最多试三次
    assert lines(github, 5) == (Line(1, True, True),)                  # 别的 Issue 照常改写

    assert sync_watched(root) == 0 and apply_rewrites(root) == 0
    assert lines(github, 2) == (Line(1, True, True),)


def test_a_change_made_between_sync_and_rewrite_is_kept(root, monkeypatch):
    github = use_github(monkeypatch, FakeGitHub({5: task_issue("2026-10-08", (1, True, False))}))
    assert sync_watched(root) == 0
    github.bodies[5] = toggle(github.bodies[5], 1)                     # 计算之后、改写之前用户又取消了
    assert apply_rewrites(root) == 0
    assert lines(github, 5) == (Line(1, False, True),)
    assert sync_watched(root) == 0
    assert load_watched_file(root / "data" / "watched.json") == {}


def test_an_issue_broken_between_sync_and_rewrite_is_skipped_and_reported(root, monkeypatch):
    github = use_github(monkeypatch, FakeGitHub({2: task_issue("2026-10-03", (1, True, False)),
                                                 5: task_issue("2026-10-08", (1, False, False))}))
    assert sync_watched(root) == 0
    github.bodies[5] = github.bodies[5].replace("bot:0", "bot:8")
    assert apply_rewrites(root) == 0
    assert ("update_body", 5) not in github.calls
    assert read(root / "out" / "problems" / "issue-5.md").startswith("已看过同步：Issue #5 无法解析\n")
```

- [ ] **Step 2：跑测试确认失败。**

Run：`.venv/bin/python -m pytest tests/test_sync_cli.py -q`
Expected：FAIL（`argument command: invalid choice: 'sync-watched'`，或 `module 'film_radar.main' has no attribute 'time'`）

- [ ] **Step 3：实现。** `src/film_radar/main.py`：

1. import 区加 `import time`、`from dataclasses import asdict`；watched 的 import 补上 `Issue, IssueFormatError, Problem, Rewrite, apply_rewrites, dump_watched, parse_issue`。
2. 在 `_build_site` 后面加：

```python
REWRITE_ATTEMPTS = 3


def _write_problems(out: Path, problems: list[Problem]) -> None:
    """无法解析的 Issue 各写一个文件：第一行是失败 Issue 的标题，其余是正文。工作流逐个开 Issue（同标题还开着就不重复开）。"""
    folder = out / "problems"
    folder.mkdir(parents=True, exist_ok=True)
    for problem in problems:
        lines = [f"已看过同步：Issue #{problem.issue} 无法解析",
                 f"Issue #{problem.issue} 里有几行不符合格式，这个 Issue 里的勾这次都没有采用，其他 Issue 照常同步：", ""]
        lines += [f"- {reason}" for reason in problem.reasons]
        lines += ["", "在这个 Issue 的编辑历史里把这几行改回原样，然后在任意一个 edition Issue 里勾一下（或手动运行 watched-sync），就会重新同步。"]
        (folder / f"issue-{problem.issue}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_sync_summary(result, issue_count: int) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["## 已看过同步", "", f"- 读到 {issue_count} 个 edition Issue，名单现在 {len(result.films)} 部"]
    lines += [f"- #{a.issue} {'勾上' if a.watched else '取消'} {a.film_id}" for a in result.actions]
    if result.conflicts:
        lines.append("- 同一部片在不同 Issue 里操作相反，以编号大的 Issue 为准：" + "、".join(str(i) for i in result.conflicts))
    lines += [f"- Issue #{p.issue} 无法解析，跳过" for p in result.problems]
    lines += [f"- 计划改写 {len(result.rewrites)} 行", ""]
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _sync_watched(root: Path) -> int:
    """spec 第 6 节第 2 步：读 Issue、计算、写名单和改写计划。提交和改写是工作流里后面的两步。"""
    settings = load_settings(root / "config" / "settings.toml")
    path = root / "data" / "watched.json"
    films = load_watched_file(path)
    issues = github_client(settings).edition_issues()
    now = datetime.now(ZoneInfo(settings.timezone)).isoformat(timespec="seconds")
    result = sync(films, issues, build_catalog(load_editions(root / "data" / "editions")), now)
    if result.changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump_watched(result.films), encoding="utf-8")
    out = root / "out"
    out.mkdir(parents=True, exist_ok=True)
    plan = {"rewrites": [asdict(r) for r in result.rewrites]}
    (out / "watched_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    _write_problems(out, result.problems)
    _set_output("changed", "true" if result.changed else "false")
    _write_sync_summary(result, len(issues))
    print(f"读到 {len(issues)} 个 edition Issue：操作 {len(result.actions)} 个，计划改写 {len(result.rewrites)} 行，"
          f"无法解析 {len(result.problems)} 个。")
    return 0


def _apply_watched_rewrites(root: Path) -> int:
    """spec 第 6 节第 4 步：名单已经提交之后才跑。每个 Issue 重新读取正文、在新正文上合并再写回。"""
    settings = load_settings(root / "config" / "settings.toml")
    out = root / "out"
    plan = json.loads((out / "watched_plan.json").read_text(encoding="utf-8"))
    rewrites = [Rewrite(**r) for r in plan["rewrites"]]
    client = github_client(settings)
    problems, failed = [], []
    for number in sorted({r.issue for r in rewrites}):
        mine = [r for r in rewrites if r.issue == number]
        for attempt in range(REWRITE_ATTEMPTS):
            try:
                body = client.issue_body(number)
                try:
                    parsed = parse_issue(Issue(number, body))
                except IssueFormatError as e:
                    problems.append(Problem(number, tuple(e.reasons)))
                    break
                if parsed is None:
                    problems.append(Problem(number, ("改写前重新读取时，第一行的 edition 标记不见了",)))
                    break
                new = apply_rewrites(body, mine)
                if new != body:
                    client.update_body(number, new)
                break
            except GitHubError as e:
                error = e
                if attempt + 1 < REWRITE_ATTEMPTS:
                    time.sleep(5)
        else:
            failed.append(f"#{number}（{error}）")
    _write_problems(out, problems)
    if failed:
        raise GitHubError(
            "名单已提交，但这几个 Issue 没改写完：" + "、".join(failed) + "。"
            "下一次同步成功之前，不要在这几个 Issue 里撤销刚才的勾（会被认成「没有操作」，"
            "见 spec 2026-10-17 第 15 节）。手动运行 watched-sync 就会补上。"
        )
    print(f"改写完成：{len({r.issue for r in rewrites})} 个 Issue，跳过无法解析的 {len(problems)} 个。")
    return 0
```

3. `main()` 里 `commands.add_parser("build-site")` 后面加 `commands.add_parser("sync-watched")` 和 `commands.add_parser("apply-watched-rewrites")`；`try:` 块改成：

```python
    try:
        if args.command == "run":
            return _run(root, args.manual, args.date)
        if args.command == "sync-watched":
            return _sync_watched(root)
        if args.command == "apply-watched-rewrites":
            return _apply_watched_rewrites(root)
        return _build_site(root)
```

- [ ] **Step 4：跑测试确认通过。**

Run：`.venv/bin/python -m pytest -q`
Expected：全部 PASS

- [ ] **Step 5：提交。**

```bash
git -C /Users/minggao/Projects/film-radar-watched add src/film_radar/main.py tests/test_sync_cli.py
git -C /Users/minggao/Projects/film-radar-watched commit -m "feat: sync-watched 与 apply-watched-rewrites 子命令

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11：迁移子命令 `migrate-issues`

**Files：**
- Modify：`src/film_radar/main.py`
- Create：`tests/test_migrate_cli.py`

**Interfaces：**
- Consumes：任务 3 的 `issue_body`、`has_edition_marker`；任务 2 的 `load_watched_file`、`watched_ids`；任务 9 的 `github_client`
- Produces：`python -m film_radar.main migrate-issues --map N=YYYY-MM-DD [--map ...] [--apply]`；`class MigrateError(Exception)`，`STAGES[MigrateError] == "迁移旧 Issue"`

- [ ] **Step 1：写失败的测试。** 新建 `tests/test_migrate_cli.py`：

```python
import json
import shutil
from datetime import date

import pytest

from film_radar import main as main_module
from film_radar.main import main
from film_radar.watched import Issue, dump_watched, parse_issue
from helpers import ROOT, FakeGitHub, build_edition, recommended, skipped

OLD = ("第 2 期重点推荐：\n\n- **B**（在映第 1 周）：一句话定位。\n\n可以看 0 部，跳过 1 部。\n\n"
       "完整页面：https://akasha-r.github.io/film-radar/\n\ncc @AKASHA-R\n")


@pytest.fixture
def root(tmp_path, settings):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    editions = tmp_path / "data" / "editions"
    editions.mkdir(parents=True)
    for edition in (build_edition(settings, [recommended(1, "A")], run_date=date(2026, 10, 3)),
                    build_edition(settings, [recommended(2, "B"), skipped(3, "C")], run_date=date(2026, 10, 8))):
        (editions / f"{edition['edition_id']}.json").write_text(json.dumps(edition, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def use_github(monkeypatch, github):
    monkeypatch.setattr(main_module, "github_client", lambda settings: github)
    return github


def migrate(root, *args):
    return main(["--root", str(root), "migrate-issues", *args])


def test_dry_run_prints_the_new_body_and_changes_nothing(root, monkeypatch, capsys):
    github = use_github(monkeypatch, FakeGitHub({5: OLD}))
    assert migrate(root, "--map", "5=2026-10-08") == 0
    out = capsys.readouterr().out
    assert "<!-- film-radar:edition 2026-10-08 -->" in out and "加 --apply 才改写" in out
    assert github.updates == [] and github.bodies[5] == OLD
    assert not (root / "out" / "migrate-backup").exists()


def test_apply_backs_up_first_then_rewrites_in_the_checkbox_format(root, monkeypatch):
    def backup_exists(number, body):
        assert (root / "out" / "migrate-backup" / f"{number}.md").read_text(encoding="utf-8") == OLD

    github = use_github(monkeypatch, FakeGitHub({5: OLD}, before_update=backup_exists))
    assert migrate(root, "--map", "5=2026-10-08", "--apply") == 0
    new = github.bodies[5]
    parsed = parse_issue(Issue(5, new))
    assert parsed.edition_id == "2026-10-08" and [l.film_id for l in parsed.lines] == [2]
    assert not parsed.lines[0].checked                                 # 名单为空：都不勾
    assert "第 2 期重点推荐：" in new                                   # 期号按数据顺序算
    assert new.endswith("\ncc @AKASHA-R\n")


def test_apply_uses_the_current_watched_list(root, monkeypatch):
    (root / "data" / "watched.json").write_text(dump_watched({2: {"title": "B", "since": "s", "ids": [2]}}), encoding="utf-8")
    github = use_github(monkeypatch, FakeGitHub({5: OLD}))
    assert migrate(root, "--map", "5=2026-10-08", "--apply") == 0
    assert parse_issue(Issue(5, github.bodies[5])).lines[0].checked


def test_an_issue_already_in_the_new_format_is_never_overwritten(root, monkeypatch, capsys):
    """中途失败重跑时，不能把用户在已迁移 Issue 里打的勾清掉。没有强制覆盖的选项。"""
    migrated = "<!-- film-radar:edition 2026-10-08 -->\n- [x] **B** · 在映第 1 周 <!-- film:2 bot:0 -->\n"
    github = use_github(monkeypatch, FakeGitHub({5: migrated}))
    assert migrate(root, "--map", "5=2026-10-08", "--apply") == 0
    assert github.updates == [] and "跳过" in capsys.readouterr().out


def test_an_unknown_edition_fails_before_touching_github(root, monkeypatch):
    github = use_github(monkeypatch, FakeGitHub({5: OLD}))
    assert migrate(root, "--map", "5=2026-10-09", "--apply") == 1
    failure = (root / "out" / "failure.txt").read_text(encoding="utf-8")
    assert "失败环节：迁移旧 Issue" in failure and "2026-10-09" in failure
    assert github.calls == []


def test_a_badly_written_map_is_rejected(root, capsys):
    with pytest.raises(SystemExit):
        migrate(root, "--map", "5:2026-10-08")
    assert "Issue编号=期号" in capsys.readouterr().err
```

- [ ] **Step 2：跑测试确认失败。**

Run：`.venv/bin/python -m pytest tests/test_migrate_cli.py -q`
Expected：FAIL（`invalid choice: 'migrate-issues'`）

- [ ] **Step 3：实现。** `src/film_radar/main.py`：

1. import 区加 `import re`；watched 的 import 补上 `has_edition_marker`。
2. `class ReviewError` 后面加：

```python
class MigrateError(Exception):
    pass
```

`STAGES` 里 `GitHubError: "GitHub 接口",` 后面加 `MigrateError: "迁移旧 Issue",`。
3. 在 `_apply_watched_rewrites` 后面加：

```python
def _map_arg(text: str) -> tuple[int, str]:
    number, sep, edition_id = text.partition("=")
    if not (sep and number.isdigit() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", edition_id)):
        raise argparse.ArgumentTypeError(f"--map 要写成 Issue编号=期号，例如 2=2026-10-03：{text!r}")
    return int(number), edition_id


def _migrate_issues(root: Path, maps: list[tuple[int, str]], apply: bool) -> int:
    """一次性把旧 Issue 改成勾选格式（spec 第 10 节）。默认只打印；--apply 才改写，改写前先备份旧正文。
    已经带 edition 标记的一律跳过，没有强制覆盖的选项：重跑不会清掉用户在已迁移 Issue 里打的勾。"""
    settings = load_settings(root / "config" / "settings.toml")
    editions = load_editions(root / "data" / "editions")
    by_id = {e["edition_id"]: e for e in editions}
    numbers = {e["edition_id"]: i + 1 for i, e in enumerate(editions)}
    missing = [edition_id for _, edition_id in maps if edition_id not in by_id]
    if missing:
        raise MigrateError("data/editions 里没有这几期：" + "、".join(missing))
    watched = watched_ids(load_watched_file(root / "data" / "watched.json"))
    client = github_client(settings)
    owner = settings.repo.split("/")[0]
    backup = root / "out" / "migrate-backup"
    for number, edition_id in maps:
        old = client.issue_body(number)
        if has_edition_marker(old):
            print(f"#{number} 已经是勾选格式，跳过（不提供强制覆盖：会清掉你在里面打的勾）。")
            continue
        new = issue_body(by_id[edition_id], numbers[edition_id], settings.page_url, watched) + f"\ncc @{owner}\n"
        if not apply:
            print(f"----- #{number} → 第 {numbers[edition_id]} 期 {edition_id}（预览，加 --apply 才改写）-----\n{new}")
            continue
        backup.mkdir(parents=True, exist_ok=True)
        (backup / f"{number}.md").write_text(old, encoding="utf-8")
        client.update_body(number, new)
        print(f"#{number} 已改写，旧正文备份在 {backup / f'{number}.md'}")
    return 0
```

4. `main()` 里加：

```python
    migrate = commands.add_parser("migrate-issues")
    migrate.add_argument("--map", dest="maps", action="append", type=_map_arg, required=True)
    migrate.add_argument("--apply", action="store_true")
```

`try:` 块里 `apply-watched-rewrites` 分支后面加：

```python
        if args.command == "migrate-issues":
            return _migrate_issues(root, args.maps, args.apply)
```

- [ ] **Step 4：跑测试确认通过。**

Run：`.venv/bin/python -m pytest -q`
Expected：全部 PASS

- [ ] **Step 5：提交。**

```bash
git -C /Users/minggao/Projects/film-radar-watched add src/film_radar/main.py tests/test_migrate_cli.py
git -C /Users/minggao/Projects/film-radar-watched commit -m "feat: migrate-issues 子命令（旧 Issue 改成勾选格式）

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12：工作流

**Files：**
- Create：`.github/workflows/watched-sync.yml`、`scripts/open_issue_once.sh`、`tests/test_workflows.py`、`tests/test_open_issue_once.py`
- Modify：`.github/workflows/edition.yml`、`pyproject.toml`

**Interfaces：**
- Consumes：任务 10 的 `sync-watched`、`apply-watched-rewrites`、`out/problems/*.md`、`out/failure.txt`；任务 7 的 `build-site`
- Produces：`scripts/open_issue_once.sh <标题> <正文文件>`（需要 `GH_TOKEN`、`GITHUB_REPOSITORY`、`GITHUB_REPOSITORY_OWNER`）

- [ ] **Step 0：看任务 1 的结论。** 如果 spec 第 12 节记录 G4 不成立，本任务按最后的「G4 不成立时」一步改，其余照做。

- [ ] **Step 1：装 PyYAML。** `pyproject.toml` 里 `dev = ["pytest==9.1.1"]` 改成 `dev = ["pytest==9.1.1", "pyyaml==6.0.3"]`，然后 `/Users/minggao/Projects/film-radar-watched/.venv/bin/pip install -e '/Users/minggao/Projects/film-radar-watched[dev]'`。

- [ ] **Step 2：写失败的测试（工作流结构）。** 新建 `tests/test_workflows.py`：

```python
"""工作流结构测试。这些顺序和条件是防丢勾的护栏：写在文档里，被改坏了没人会发现（spec 2026-10-17 第 6、13 节）。"""
import yaml

from helpers import ROOT


def workflow(name):
    data = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))
    data["on"] = data.pop(True, data.get("on"))          # PyYAML 按 YAML 1.1 把键 on 读成 True
    return data


SYNC = workflow("watched-sync.yml")
EDITION = workflow("edition.yml")


def steps(wf, job):
    return wf["jobs"][job]["steps"]


def step(wf, job, step_id):
    return next(s for s in steps(wf, job) if s.get("id") == step_id)


def position(wf, job, step_id):
    return [s.get("id") for s in steps(wf, job)].index(step_id)


def failure_script(wf, job):
    return next(s for s in steps(wf, job) if s.get("if") == "failure()")["run"]


def test_sync_checks_out_the_latest_main():
    """排队的运行在创建时就固定了提交；不写 ref 会按几分钟前的旧名单把 Issue 改回去。"""
    checkout = steps(SYNC, "sync")[0]
    assert checkout["uses"].startswith("actions/checkout@") and checkout["with"]["ref"] == "main"


def test_sync_commits_the_list_before_it_rewrites_issues():
    assert position(SYNC, "sync", "sync") < position(SYNC, "sync", "commit") < position(SYNC, "sync", "apply")
    assert "sync-watched" in step(SYNC, "sync", "sync")["run"]
    assert "apply-watched-rewrites" in step(SYNC, "sync", "apply")["run"]
    assert step(SYNC, "sync", "apply")["if"] == "steps.commit.outcome == 'success'"


def test_sync_deploys_every_run_once_the_list_is_committed():
    assert SYNC["jobs"]["sync"]["environment"]["name"] == "github-pages"
    build = step(SYNC, "sync", "build")
    assert build["if"] == "always() && steps.commit.outcome == 'success'"
    assert build["run"].index("git pull") < build["run"].index("build-site")
    assert position(SYNC, "sync", "apply") < position(SYNC, "sync", "build") < position(SYNC, "sync", "deploy")
    assert step(SYNC, "sync", "pages")["if"] == "always() && steps.build.outcome == 'success'"
    assert step(SYNC, "sync", "upload")["if"] == "always() && steps.pages.outcome == 'success'"
    assert step(SYNC, "sync", "deploy")["if"] == "always() && steps.upload.outcome == 'success'"
    assert step(SYNC, "sync", "deploy")["uses"].startswith("actions/deploy-pages@")


def test_sync_runs_for_every_issue_edit_without_a_job_filter():
    assert SYNC["on"]["issues"]["types"] == ["edited"] and "workflow_dispatch" in SYNC["on"]
    assert "if" not in SYNC["jobs"]["sync"]


def test_the_two_workflows_do_not_share_a_concurrency_group():
    assert SYNC["concurrency"] == {"group": "watched-sync", "cancel-in-progress": False}
    assert EDITION["concurrency"] == {"group": "edition", "cancel-in-progress": False}


def test_sync_permissions():
    assert SYNC["permissions"] == {"contents": "write", "issues": "write", "pages": "write", "id-token": "write"}


def test_edition_no_longer_deploys_pages():
    job = EDITION["jobs"]["edition"]
    assert not [s for s in job["steps"] if "pages" in s.get("uses", "")]
    assert "environment" not in job
    assert EDITION["permissions"] == {"contents": "write", "issues": "write", "actions": "write"}


def test_edition_reads_github_and_triggers_the_sync():
    assert step(EDITION, "edition", "run")["env"]["GITHUB_TOKEN"] == "${{ github.token }}"
    dispatch = step(EDITION, "edition", "dispatch")
    assert dispatch["if"] == "always() && steps.commit.outcome == 'success'"
    assert "gh workflow run watched-sync.yml" in dispatch["run"] and "--ref main" in dispatch["run"]
    assert position(EDITION, "edition", "commit") < position(EDITION, "edition", "issue") < position(EDITION, "edition", "dispatch")


def test_edition_failure_wording_checks_the_sync_trigger_first():
    script = failure_script(EDITION, "edition")
    order = [script.index(text) for text in
             ("同步没有触发", "通知 Issue 也没开成", "只是通知 Issue 没开成", "提交数据这一步没完成", "cat out/failure.txt")]
    assert order == sorted(order)
    assert "部署失败" not in script and "scripts/open_issue_once.sh" in script


def test_sync_failure_wording():
    script = failure_script(SYNC, "sync")
    order = [script.index(text) for text in
             ('"$APPLY_OUTCOME" = "failure"', "名单和 Issue 已经更新", "推送三次都被拒", '"$SYNC_OUTCOME" = "failure"')]
    assert order == sorted(order)
    assert 'scripts/open_issue_once.sh "已看过同步失败"' in script


def test_unparsable_issues_are_reported_every_run():
    report = next(s for s in steps(SYNC, "sync") if s.get("name") == "Report unparsable issues")
    assert report["if"] == "always()" and "out/problems" in report["run"] and "open_issue_once.sh" in report["run"]
```

- [ ] **Step 3：写失败的测试（开 Issue 脚本）。** 新建 `tests/test_open_issue_once.py`：

```python
import os
import shlex
import subprocess

from helpers import ROOT

SCRIPT = ROOT / "scripts" / "open_issue_once.sh"


def run_script(tmp_path, title, open_titles=(), listing_fails=False):
    """用一个假的 gh 跑脚本：api 子命令吐出 open_titles（或失败），其余子命令记下参数、把 --body-file 拷出来。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "gh.log"
    listing = "  exit 1\n" if listing_fails else f"  printf '%s\\n' {' '.join(shlex.quote(t) for t in open_titles)}\n  exit 0\n"
    (bin_dir / "gh").write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> {shlex.quote(str(log))}\n'
        'if [ "$1" = "api" ]; then\n' + listing + "fi\n"
        "while [ $# -gt 0 ]; do\n"
        f'  if [ "$1" = "--body-file" ]; then cp "$2" {shlex.quote(str(tmp_path / "created.md"))}; fi\n'
        "  shift\n"
        "done\n",
        encoding="utf-8")
    (bin_dir / "gh").chmod(0o755)
    body = tmp_path / "body.md"
    body.write_text("出错了\n", encoding="utf-8")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
           "GITHUB_REPOSITORY": "AKASHA-R/film-radar", "GITHUB_REPOSITORY_OWNER": "AKASHA-R"}
    result = subprocess.run(["sh", str(SCRIPT), title, str(body)], env=env, capture_output=True, text=True)
    return result, (log.read_text(encoding="utf-8") if log.exists() else "")


def test_opens_a_failure_issue_with_a_cc_line(tmp_path):
    result, log = run_script(tmp_path, "已看过同步失败", open_titles=["film-radar 运行失败 2026-10-22"])
    assert result.returncode == 0, result.stderr
    assert "repos/AKASHA-R/film-radar/issues?labels=failure&state=open" in log        # REST 列表，不用搜索接口
    assert "issue create --repo AKASHA-R/film-radar --title 已看过同步失败" in log and "--label failure" in log
    assert (tmp_path / "created.md").read_text(encoding="utf-8") == "出错了\n\ncc @AKASHA-R\n"


def test_does_not_open_a_second_one_while_the_first_is_open(tmp_path):
    result, log = run_script(tmp_path, "已看过同步失败", open_titles=["已看过同步失败"])
    assert result.returncode == 0 and "issue create" not in log and "不重复开" in result.stdout


def test_only_an_exact_title_counts_as_a_duplicate(tmp_path):
    _, log = run_script(tmp_path, "已看过同步失败", open_titles=["已看过同步失败（旧）"])
    assert "issue create" in log


def test_still_opens_when_listing_fails(tmp_path):
    """列不出来时宁可重复，也不能漏报。"""
    _, log = run_script(tmp_path, "已看过同步失败", listing_fails=True)
    assert "issue create" in log
```

- [ ] **Step 4：跑测试确认失败。**

Run：`.venv/bin/python -m pytest tests/test_workflows.py tests/test_open_issue_once.py -q`
Expected：FAIL（`FileNotFoundError: ... watched-sync.yml`；脚本不存在）

- [ ] **Step 5：写脚本。** 新建 `scripts/open_issue_once.sh`：

```sh
#!/bin/sh
# 开一个带 failure 标签的 Issue；同标题的失败 Issue 还开着就不重复开。
# 用 REST 列表比对标题，不用搜索接口：搜索索引有延迟，连续两次失败仍会重复开（spec 2026-10-17 第 11 节）。
# 列不出来时照样开：宁可重复，也不能漏报。
# 用法：sh scripts/open_issue_once.sh 标题 正文文件。需要 GH_TOKEN、GITHUB_REPOSITORY、GITHUB_REPOSITORY_OWNER。
set -eu
title=$1
body=$2
if gh api --paginate "repos/$GITHUB_REPOSITORY/issues?labels=failure&state=open&per_page=100" --jq '.[].title' | grep -Fxq -- "$title"; then
  echo "同标题的失败 Issue 还开着，不重复开：$title"
  exit 0
fi
printf '\ncc @%s\n' "$GITHUB_REPOSITORY_OWNER" >> "$body"
gh issue create --repo "$GITHUB_REPOSITORY" --title "$title" --body-file "$body" --label failure
```

- [ ] **Step 6：写同步工作流。** 新建 `.github/workflows/watched-sync.yml`：

```yaml
name: watched-sync

# 「已看过」名单的同步，也是整个仓库唯一部署页面的地方（spec 2026-10-17 第 6、7 节）。
# 任何 Issue 被编辑都完整跑一轮，不加任务级的过滤条件：同组里新排队的运行会顶掉原来排队的那个，
# 只对 edition Issue 运行的话，编辑别的 Issue 产生的运行会顶掉一次真正的同步、自己却什么都不做，那次部署就丢了。
on:
  issues:
    types: [edited]
  workflow_dispatch:

permissions:
  contents: write
  issues: write
  pages: write
  id-token: write

# 同步之间串行。不和 edition 共用并发组：共用的话，出刊排队时用户正好打勾，出刊运行会被同步顶掉，而且不报错。
concurrency:
  group: watched-sync
  cancel-in-progress: false

jobs:
  sync:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deploy.outputs.page_url }}
    steps:
      # 必须写 ref: main。issues 和 workflow_dispatch 的运行在创建时就固定了要检出的提交，
      # 排队等到开始执行时，默认检出的是几分钟前的旧名单，会按旧名单把刚同步好的 Issue 改回去
      - uses: actions/checkout@v4
        with:
          ref: main

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - run: pip install -e .

      - name: Sync watched list
        id: sync
        env:
          GITHUB_TOKEN: ${{ github.token }}
        run: python -m film_radar.main sync-watched

      # 先提交名单，再改写 Issue：反过来的话，Issue 改写成功而提交失败时，用户的勾在 Issue 里已被「对齐」掉、
      # 名单里却没有，这个勾就悄无声息地丢了。顺序和条件由 tests/test_workflows.py 守着
      - name: Commit watched list
        id: commit
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data/watched.json 2>/dev/null || true
          if git diff --cached --quiet; then
            echo "名单没有变化。"
            exit 0
          fi
          git commit -m "data: 同步已看过名单"
          # 只有同步写这个文件、同步之间又是串行的，变基不会在它上面冲突（出刊只提交 data/editions）
          for attempt in 1 2 3; do
            git pull --rebase --quiet origin main && git push && exit 0
            sleep 5
          done
          echo "git push 三次都没成功，名单没提交。" >&2
          exit 1

      - name: Rewrite issues
        id: apply
        if: steps.commit.outcome == 'success'
        env:
          GITHUB_TOKEN: ${{ github.token }}
        run: python -m film_radar.main apply-watched-rewrites

      # 每次同步都部署，不管名单变没变：同组排队的运行被顶掉时，顶替者开始得更晚、从更新的 main 出发，
      # 所以后一次部署一定不比前一次旧。改写 Issue 失败也照样部署：页面按已提交的名单生成
      - name: Build site
        id: build
        if: always() && steps.commit.outcome == 'success'
        run: |
          git pull --ff-only --quiet origin main
          python -m film_radar.main build-site

      - uses: actions/configure-pages@v5
        id: pages
        if: always() && steps.build.outcome == 'success'

      - uses: actions/upload-pages-artifact@v3
        id: upload
        if: always() && steps.pages.outcome == 'success'
        with:
          path: site

      - name: Deploy pages
        id: deploy
        if: always() && steps.upload.outcome == 'success'
        uses: actions/deploy-pages@v4

      - name: Report unparsable issues
        if: always()
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          for f in out/problems/*.md; do
            [ -e "$f" ] || continue
            tail -n +2 "$f" > problem_body.md
            printf '\n运行日志：%s/%s/actions/runs/%s\n' "${{ github.server_url }}" "${{ github.repository }}" "${{ github.run_id }}" >> problem_body.md
            sh scripts/open_issue_once.sh "$(head -n 1 "$f")" problem_body.md
          done

      - name: Open failure issue
        if: failure()
        env:
          GH_TOKEN: ${{ github.token }}
          SYNC_OUTCOME: ${{ steps.sync.outcome }}
          COMMIT_OUTCOME: ${{ steps.commit.outcome }}
          APPLY_OUTCOME: ${{ steps.apply.outcome }}
          DEPLOY_OUTCOME: ${{ steps.deploy.outcome }}
        run: |
          {
            echo "运行日志：${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
            echo
            if [ "$APPLY_OUTCOME" = "failure" ]; then
              cat out/failure.txt
              echo
              if [ "$DEPLOY_OUTCOME" = "success" ]; then
                echo "页面已按新名单更新。"
              else
                echo "页面也没更新成功。"
              fi
            elif [ "$APPLY_OUTCOME" = "success" ] && [ "$DEPLOY_OUTCOME" != "success" ]; then
              echo "名单和 Issue 已经更新，只是页面还是旧的；手动运行 watched-sync 重新部署。"
            elif [ "$COMMIT_OUTCOME" = "failure" ]; then
              echo "推送三次都被拒，名单没提交，什么都没变。你的勾还在 Issue 里，下一次同步会补上；想马上补就手动运行 watched-sync。页面这次没有部署。"
            elif [ "$SYNC_OUTCOME" = "failure" ]; then
              cat out/failure.txt 2>/dev/null || echo "同步程序失败了，但没有留下失败说明，详见运行日志。"
              echo
              echo "名单没提交，什么都没变。你的勾还在 Issue 里，下一次同步会补上。页面这次没有部署：如果刚出了新一期，手动运行 watched-sync。"
            elif [ "$SYNC_OUTCOME" = "success" ]; then
              echo "名单、Issue 和页面都处理完了，失败在开「Issue 无法解析」提醒这一步，详见运行日志。"
            else
              echo "失败在同步之前的环境准备（检出代码或安装依赖），详见运行日志。什么都没变。"
            fi
          } > failure_body.md
          sh scripts/open_issue_once.sh "已看过同步失败" failure_body.md
```

- [ ] **Step 7：改出刊工作流。** 把 `.github/workflows/edition.yml` 整个换成：

```yaml
name: edition

on:
  schedule:
    # 每周四 11:00 UTC（多伦多夏令时 7:00，冬令时 6:00）。脚本里按周数奇偶决定这周跑不跑。
    - cron: "0 11 * * 4"
  workflow_dispatch:

# 页面不在这里部署：提交新一期之后触发 watched-sync，由它生成并部署页面，整个仓库只有一个部署者（spec 2026-10-17 第 6 节）
permissions:
  contents: write
  issues: write
  actions: write

concurrency:
  group: edition
  cancel-in-progress: false

jobs:
  edition:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - run: pip install -e .

      - name: Run pipeline
        id: run
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          # 只读：取最新的已看过名单和 Issue 里还没同步的勾，用来排除看过的片（GITHUB_REPOSITORY 是 Actions 默认就有的）
          GITHUB_TOKEN: ${{ github.token }}
        run: python -m film_radar.main run ${{ github.event_name == 'workflow_dispatch' && '--manual' || '' }}

      # 这一期花了几块钱，只存在这台临时机器上。先备份成产物：后面的推送、开 Issue 任何一步失败，
      # 数据都还在，可以手工提交，不用再付一次钱重跑
      - name: Back up the new edition
        if: steps.run.outputs.skipped == 'false'
        uses: actions/upload-artifact@v4
        with:
          name: edition-backup
          path: |
            data/editions
            out
          retention-days: 14

      - name: Commit edition data
        id: commit
        if: steps.run.outputs.skipped == 'false'
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data/editions
          git diff --cached --quiet || git commit -m "data: 第 ${{ steps.run.outputs.edition_id }} 期"
          # 跑一期要十来分钟，这期间有人往 main 推了东西的话，直接推送会被拒绝。先变基再推，最多三次
          for attempt in 1 2 3; do
            git pull --rebase --quiet origin main && git push && exit 0
            sleep 5
          done
          echo "git push 三次都没成功。这一期的数据在本次运行的 edition-backup 产物里。" >&2
          exit 1

      - name: Open edition issue
        id: issue
        if: steps.run.outputs.skipped == 'false'
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          printf '\ncc @%s\n' "${{ github.repository_owner }}" >> out/issue_body.md
          gh issue create --repo "${{ github.repository }}" \
            --title "$(cat out/issue_title.txt)" \
            --body-file out/issue_body.md \
            --label edition

      # 开 Issue 失败也要触发，否则页面就没人更新了。用 GITHUB_TOKEN 触发 workflow_dispatch 是允许的（闸门 G4）
      - name: Trigger watched-sync
        id: dispatch
        if: always() && steps.commit.outcome == 'success'
        env:
          GH_TOKEN: ${{ github.token }}
        run: gh workflow run watched-sync.yml --repo "${{ github.repository }}" --ref main

      - name: Open failure issue
        if: failure()
        env:
          GH_TOKEN: ${{ github.token }}
          RUN_OUTCOME: ${{ steps.run.outcome }}
          COMMIT_OUTCOME: ${{ steps.commit.outcome }}
          ISSUE_OUTCOME: ${{ steps.issue.outcome }}
          DISPATCH_OUTCOME: ${{ steps.dispatch.outcome }}
        run: |
          {
            echo "运行日志：${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"
            echo
            if [ "$COMMIT_OUTCOME" = "success" ] && [ "$DISPATCH_OUTCOME" != "success" ]; then
              echo "新一期数据已提交，但页面还没更新（同步没有触发）。手动运行 watched-sync，或者在任意一个 Issue 里勾一下。"
              if [ "$ISSUE_OUTCOME" != "success" ]; then
                echo "通知 Issue 也没开成。"
              fi
            elif [ "$COMMIT_OUTCOME" = "success" ] && [ "$ISSUE_OUTCOME" != "success" ]; then
              echo "页面会在几分钟内更新到新一期，只是通知 Issue 没开成（比如 edition 标签被删了）。"
            elif [ "$RUN_OUTCOME" = "success" ] && [ "$COMMIT_OUTCOME" != "success" ]; then
              echo "流水线跑成功了，但提交数据这一步没完成（推送被拒，或备份上传失败）。页面没有更新。能找到本次运行的 edition-backup 产物的话，这一期的数据就在里面。"
            elif [ -f out/failure.txt ]; then
              cat out/failure.txt
              echo
              echo "已发布的页面没有被改动。"
            elif [ "$RUN_OUTCOME" = "failure" ]; then
              echo "流水线失败了，但没有留下失败说明（进程被杀或超时？），详见运行日志。已发布的页面没有被改动。"
            else
              echo "失败在流水线之前的环境准备（检出代码或安装依赖），详见运行日志。已发布的页面没有被改动。"
            fi
          } > failure_body.md
          sh scripts/open_issue_once.sh "film-radar 运行失败 $(date -u +%F)" failure_body.md
```

- [ ] **Step 8：跑测试确认通过。**

Run：`.venv/bin/python -m pytest -q`
Expected：全部 PASS

- [ ] **Step 9：验红。** 每次只改一处、各自还原：①删掉 `watched-sync.yml` 检出的 `with: ref: main` → `sh scripts/redcheck.sh tests/test_workflows.py` FAIL；②把 `Rewrite issues` 一步挪到 `Commit watched list` 之前 → FAIL；③把 `Build site` 的 `if` 改成 `steps.apply.outcome == 'success'` → FAIL；④在 `open_issue_once.sh` 里把 `grep -Fxq` 改成 `grep -Fq` → `sh scripts/redcheck.sh tests/test_open_issue_once.py` FAIL（`test_only_an_exact_title_counts_as_a_duplicate`）。

- [ ] **Step 10（只在 G4 不成立时）：改用 `workflow_run`。** `watched-sync.yml` 的 `on:` 里加：

```yaml
  workflow_run:
    workflows: [edition]
    types: [completed]
```

`edition.yml` 删掉 `Trigger watched-sync` 一步、`actions: write` 权限、失败步骤里的 `DISPATCH_OUTCOME` 和第一个分支（`同步没有触发`）；`tests/test_workflows.py` 里 `test_edition_reads_github_and_triggers_the_sync` 改成断言 `SYNC["on"]["workflow_run"] == {"workflows": ["edition"], "types": ["completed"]}` 且 edition 没有 `dispatch` 步骤，`test_edition_failure_wording_checks_the_sync_trigger_first` 的顺序列表去掉前两项，`test_edition_no_longer_deploys_pages` 的权限改成 `{"contents": "write", "issues": "write"}`。跑测试确认通过。

- [ ] **Step 11：提交。**

```bash
git -C /Users/minggao/Projects/film-radar-watched add .github/workflows/watched-sync.yml .github/workflows/edition.yml scripts/open_issue_once.sh tests/test_workflows.py tests/test_open_issue_once.py pyproject.toml
git -C /Users/minggao/Projects/film-radar-watched commit -m "ci: watched-sync 工作流成为唯一部署者，出刊提交后触发同步

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13：文档同步

**Files：**
- Modify：`docs/superpowers/specs/2026-10-03-film-radar-design.md`、`CLAUDE.md`、`README.md`、`docs/superpowers/specs/2026-10-17-watched-list-design.md`（状态行）

**Interfaces：** 无代码。

- [ ] **Step 1：主设计第 11 节。** 把「**「我已经看过」（2026-10-04）**」这个小标题和它下面的五条（以「每张**重点推荐和可以看**的卡片一个按钮」开头，到「有意接受的两个取舍」那条为止）整段换成：

```markdown
**「已看过」（2026-10-04 按钮版；2026-10-18 起改为仓库里的名单，设计见 `2026-10-17-watched-list-design.md`）**

- 「已看过」记在仓库的 `data/watched.json` 里，是唯一的事实来源。标记入口是 edition Issue 正文里的勾选框（网页或手机 App 都能勾）；`watched-sync` 工作流在 Issue 被编辑后几分钟内把名单、所有 edition Issue 的勾选和页面对齐。下一期粗筛前就排除看过的片，仍在映的列进「看过、仍在映」折叠区。
- 页面生成时就把名单里的片画成已看过，所有页面都是（包括往期）：速览行标题加删除线并换空心圆点、卡片左边条变灰、海报转灰度、出现绿色「✓ 已看过」角标，另有读屏软件能读到的「（已看过）」。卡片上原来的按钮换成链接「看过了？去 Issue 打勾」（已看过的片写「去 Issue 撤销」），指向所有 edition Issue 的列表。
- 「隐藏已看过」开关保留，它只是这台设备上的显示偏好（`localStorage` 键 `film-radar:hide-seen:v1`）。计数在生成时写好；开关生成时一律带 `hidden`，脚本跑起来、本页有已看过的片才显示。旧键 `film-radar:seen:v1` 不再读取，也不删除；以前在浏览器里点过的标记没有迁移。偏好以内存为准，存储读不了、写不了时这次访问照常能切换；多个标签页之间用 `storage` 事件同步，页面从后退缓存恢复时重读。
- 有意接受的取舍：「隐藏」仍由页面末尾的脚本执行，慢速网络下已看过的片会先闪一下再收起；隐藏之后章节标题和导航里的计数不变。
```

同一节里再改三处：「**绿**＝已完成（「已看过」角标与按钮）」改成「**绿**＝已完成（「已看过」角标）」；「只有「已看过」的文字角标和按钮用绿色」改成「只有「已看过」的文字角标用绿色」；「触控目标（`.seen`、`.buy`、导航按钮）」改成「触控目标（「去 Issue 打勾」链接 `.seen`、`.buy`、导航按钮）」。「改版时被测试钉住」那一段里：删掉「按钮用 `data-seen`」这半句（连同前面的分号）；「**往期页没有过期提示脚本，但有「我已经看过」的脚本**」改成「**往期页没有过期提示脚本，但有「隐藏已看过」开关的脚本**」。

- [ ] **Step 2：主设计第 12 节。** 「步骤」改成：

```markdown
1. 检出仓库，装 Python 3.11 与依赖。
2. 运行流水线：过双周门控之后、任何 Claude 调用之前，先从 `origin/main` 取最新的 `data/watched.json`，再读所有 edition Issue，在内存里算出「名单＋还没同步的勾」，粗筛前排除看过的片（只读，不提交名单、不改 Issue）。然后生成当期 edition。
3. 把 `data/editions` 与 `out/` 备份成产物（保留 14 天），再提交 `data/editions/<id>.json`。推送前先 `pull --rebase`，最多三次。
4. 开 Issue：标题为"第 N 期 M/D：片名一、片名二、片名三"（没有重点推荐时写明"本期没有重点推荐"）；正文第一行是隐藏的 edition 标记，重点推荐、可以看、看过仍在映各一节，每部片一行勾选框（勾选＝看过），加页面链接，标签 `edition`。
5. 触发 `watched-sync`（`gh workflow run watched-sync.yml --ref main`），由它生成并部署页面。**出刊工作流不再部署页面**，整个仓库只有同步工作流一个部署者。
6. 把用量与各去向数量写进 Actions 运行摘要。
```

「失败时」那段的最后一句（「流水线失败（读 `failure.txt`）、环境准备失败、推送被拒、页面部署失败、页面已更新但通知 Issue 没开成，是五种不同的处境……」）改成：「先看触发同步：数据已提交但同步没触发，写明「页面还没更新，手动运行 watched-sync」（开 Issue 也失败时补一句）；数据已提交、同步已触发、只是 Issue 没开成，写明「页面会在几分钟内更新」；其余沿用流水线失败（读 `failure.txt`）、推送被拒、环境准备失败三种措辞。失败 Issue 由 `scripts/open_issue_once.sh` 开，同标题的还开着就不重复开。」

「权限」那段改成：「**权限**：`contents: write`、`issues: write`、`actions: write`（触发同步）。部署 Pages 的 `pages`、`id-token` 权限在 `watched-sync.yml` 上。」

在「诊断工作流」那段之前加一段：

```markdown
**同步工作流（`.github/workflows/watched-sync.yml`）**：任何 Issue 被编辑或手动、出刊触发时运行，工作流级并发组 `watched-sync`（不和出刊共用）。检出 `ref: main` → `sync-watched` 读所有 edition Issue（含已关闭的）算出新名单和改写计划 → 名单有变化先提交推送 → 再 `apply-watched-rewrites` 在新读到的正文上逐行合并改写 Issue → 拉最新 main、`build-site`、部署 Pages（每次都部署）。无法解析的 Issue 跳过并各开一个提醒；失败开「已看过同步失败」。顺序与条件由 `tests/test_workflows.py` 守着。详见 `2026-10-17-watched-list-design.md` 第 6、7 节。
```

- [ ] **Step 3：主设计第 13、14、16、17 节。**
  - 第 13 节表格：「部署或开 Issue 失败」那一行改成「出刊：开 Issue 或触发同步失败 | 开失败 Issue，措辞见第 12 节」；在它下面加两行：「已看过同步失败（读 Issue、推送、改写、部署任一步） | 开「已看过同步失败」，写明哪一步、名单有没有提交、要不要手动重跑（watched spec 第 11 节）」、「某个 edition Issue 无法解析 | 跳过它、其他 Issue 照常同步，开「已看过同步：Issue #N 无法解析」」。
  - 第 14 节未决事项⑤改成：「⑤~~「我已经看过」跨设备、并让流水线不再推荐看过的片~~（2026-10-18 已做，见 `2026-10-17-watched-list-design.md`）。」
  - 第 16 节 `render` 那条里，「**真实浏览器端到端测试**（headless Chrome，走本机 http 服务；预置 `localStorage`、点击、读回状态，覆盖存储损坏、读不了、写不了、跨标签页与后退缓存同步、隐藏开关与焦点、播报文字、伪元素文字）」改成「**真实浏览器端到端测试**（headless Chrome，走本机 http 服务；页面生成时带上已看过的片，测「隐藏已看过」开关的计数与显示、偏好的记忆与跨标签页、后退缓存同步、存储读不了或写不了、旧键不读不删、伪元素文字）」。在第 16 节末尾加一条：「- `watched`、`github`、同步与迁移子命令、工作流结构（读 YAML）、开失败 Issue 的脚本（假 `gh`）各有测试，见 watched spec 第 13 节。」
  - 第 17 节表格末尾加一行：「| 8 | 「已看过」的 Issue 勾选入口能用（G1–G6） | 见 `2026-10-17-watched-list-design.md` 第 12 节「实测结果」 | 见该节 |」

- [ ] **Step 4：`CLAUDE.md`。** 「改代码前要知道的」里，`_STYLE_BASE` 那条末尾的「「我已经看过」的浏览器行为都有测试守着」改成「「隐藏已看过」开关的浏览器行为都有测试守着」。在「页面始终浅色」那条之后加四条：

```markdown
- **`watched`（用户看过）和 `seen_before`（上一期也推荐过，决定「新」徽标）是两回事**，别混用。设计见 `docs/superpowers/specs/2026-10-17-watched-list-design.md`。
- **`data/watched.json` 只有同步（`sync-watched`）写。** 出刊运行只读：在内存里算「名单＋还没同步的勾」，不提交名单、不改 Issue。名单格式不对必须失败，绝不能当成空名单（会把所有 Issue 里的勾清掉）。
- **同步先提交名单、再改写 Issue；同步检出必须带 `ref: main`；只有同步工作流部署页面；同步不和出刊共用并发组。** 这几条由 `tests/test_workflows.py` 读 YAML 守着，改工作流前先读那个测试的说明。
- **本机跑 `run`、`sync-watched`、`migrate-issues` 要令牌：** 命令前加 `GH_TOKEN=$(gh auth token)`。没有令牌时出刊以「GitHub 接口」环节失败，不会悄悄只用文件里的名单。
```

- [ ] **Step 5：`README.md`。** 「## 页面」下那条「每张卡片有「我已经看过」按钮……下一期仍可能推荐你看过的片。」换成「- 看过的片在所有页面上都显示为「✓ 已看过」。名单在仓库里，标记方法见下面「标记看过的片」。」在「## 页面」这一节后面加一节：

```markdown
## 标记看过的片

在任意一期 edition Issue 里勾选那部片＝我已经看过，取消勾选＝撤销，网页和手机 App 都行。几分钟内 watched-sync 会把名单（`data/watched.json`）、所有期的 Issue 和页面对齐；页面有最长 10 分钟的缓存，没变化就强制刷新一下。

看过的片下一期不再参加评估，仍在映的列在页面底部和 Issue 里的「看过、仍在映」。想重新看到它的推荐，取消勾选，下一期会重新评估。重映、周年纪念版在 Cineplex 是另一个条目，需要再勾一次。

页面上的「隐藏已看过」只影响这台设备的显示。名单和勾选是公开的（仓库公开）。同步失败、或者某个 Issue 被手改坏了无法解析，会开带 `failure` 标签的 Issue 说明怎么办。
```

如果任务 1 记录了 G2 的问题，在这一节末尾加对应的一句：手机不能勾时写「手机 App 里勾不了，请在网页上勾。」；手机拒绝但不提示时写「在手机上连续勾几部时，勾完一部下拉刷新、确认勾还在再勾下一部。」

「本地开发」那节里「页面交互（「我已经看过」）有真实浏览器测试」改成「页面交互（「隐藏已看过」开关）有真实浏览器测试」。「手动跑一期」那节如果有本机运行 `run` 的命令，在命令前加 `GH_TOKEN=$(gh auth token) `，并加一句「本机跑要 GitHub 令牌（读已看过名单和 Issue），没有会以「GitHub 接口」环节失败。」

- [ ] **Step 6：watched spec 状态行。** `docs/superpowers/specs/2026-10-17-watched-list-design.md` 第 4 行的状态改成「状态：已实施（2026-10-__）。初稿 `a7cf284` 经过一轮四个角度的对抗审查……（后半句保留）」，日期填实际合并日（任务 14 合并前填）。

- [ ] **Step 7：自查。** `grep -n "我已经看过\|localStorage\|data-seen" CLAUDE.md README.md docs/superpowers/specs/2026-10-03-film-radar-design.md`，剩下的每一处都应当是讲历史（「2026-10-04 按钮版」）或讲「隐藏已看过」偏好，不能再说状态只存在浏览器里。

- [ ] **Step 8：提交。**

```bash
git -C /Users/minggao/Projects/film-radar-watched add CLAUDE.md README.md docs/superpowers/specs/2026-10-03-film-radar-design.md docs/superpowers/specs/2026-10-17-watched-list-design.md
git -C /Users/minggao/Projects/film-radar-watched commit -m "docs: 已看过改为仓库名单后的主设计、CLAUDE.md、README 同步

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14：上线（控制者和用户一起做）

**Files：**
- Delete：`.github/workflows/watched-probe.yml`（合并时）

每一个对外动作前都要用户当场确认。

- [ ] **Step 1：变基到最新 main，删掉探针。**

```bash
git -C /Users/minggao/Projects/film-radar-watched fetch origin
git -C /Users/minggao/Projects/film-radar-watched rebase origin/main
git -C /Users/minggao/Projects/film-radar-watched rm .github/workflows/watched-probe.yml
git -C /Users/minggao/Projects/film-radar-watched commit -m "ci: 删掉已看过前提探针

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 2：全量测试。**

Run：`cd /Users/minggao/Projects/film-radar-watched && .venv/bin/python -m pytest -q -rs`
Expected：全部 PASS，浏览器测试没有被跳过。

- [ ] **Step 3：整支分支审查。** 按执行方式做最后一轮独立审查（子代理用 opus，不用 fable），处理完发现再继续。

- [ ] **Step 4：请用户确认合并。** 给用户看 `git -C /Users/minggao/Projects/film-radar-watched log --oneline origin/main..feat/watched`，说明：合并后下一次出刊（10-22 周四 11:00 UTC，或之后的 11-05）就用新代码；合并到迁移完成之间页面仍是旧版。如果已经过了 10-22 且那一期是旧代码开的 Issue，它也要列进迁移名单。用户同意后：

```bash
git -C /Users/minggao/Projects/film-radar-watched push origin feat/watched:main
gh workflow list --repo AKASHA-R/film-radar
```

预期 `watched-sync` 出现在列表里，`watched-probe` 不在。

- [ ] **Step 5：列出要迁移的 Issue。**

```bash
gh issue list --repo AKASHA-R/film-radar --label edition --state all --json number,title,createdAt
```

预期：#2→2026-10-03、#3（10-04 被覆盖的重复一期）、#4→2026-10-04、#5→2026-10-08，再加任何旧代码开的新期。核对标题里的日期，确定 `--map` 列表。

- [ ] **Step 6：迁移预览。**

```bash
cd /Users/minggao/Projects/film-radar-watched && GH_TOKEN=$(gh auth token) .venv/bin/python -m film_radar.main migrate-issues --map 2=2026-10-03 --map 4=2026-10-04 --map 5=2026-10-08
```

把每个 Issue 的新正文要点（几行勾选框、第几期）告诉用户，确认后再执行下一步。

- [ ] **Step 7：执行迁移。** 同一条命令末尾加 `--apply`。完成后确认 `out/migrate-backup/` 下有 `2.md`、`4.md`、`5.md`。

- [ ] **Step 8：处理 #3（先问用户）。**

```bash
gh issue edit 3 --repo AKASHA-R/film-radar --remove-label edition
gh issue close 3 --repo AKASHA-R/film-radar
```

- [ ] **Step 9：看迁移触发的同步。** 迁移的三次编辑会各触发一次 watched-sync（同组排队、可能被顶替）。

```bash
gh run list --repo AKASHA-R/film-radar --workflow watched-sync.yml --limit 5 --json databaseId,status,conclusion,event,createdAt
gh run view RUN_ID --repo AKASHA-R/film-radar --log | grep "读到"
gh api "repos/AKASHA-R/film-radar/commits?path=data/watched.json&per_page=1" --jq length
curl -s https://akasha-r.github.io/film-radar/ | grep -c "去 Issue 打勾"
curl -s https://akasha-r.github.io/film-radar/ | grep -c "data-seen"
```

预期：最后一次运行 `success`，日志里「操作 0 个，计划改写 0 行」（幂等）；没有名单提交（`0`）；页面上有「去 Issue 打勾」、没有 `data-seen`（Pages 缓存最长 10 分钟，必要时等一等再查）。

- [ ] **Step 10：真实验证（spec 第 13 节末尾，需要用户动手）。**
  1. 请用户在 #5 里勾一部片。等那次 watched-sync 完成，查：`gh api repos/AKASHA-R/film-radar/contents/data/watched.json --jq .content | base64 -d`（名单里有这部片）；#2、#4 里同一部片（如果有）被勾上（`gh api repos/AKASHA-R/film-radar/issues/2 --jq .body`）；请用户强制刷新页面，这部片变灰、有「✓ 已看过」。
  2. 请用户取消这个勾。等同步完成，确认名单里没有它、其他 Issue 取消、页面恢复。
  3. 请用户在半分钟内连勾两部。等所有同步完成，确认 Issue、名单、页面三者一致。
  把每一步的运行编号和结果告诉用户。

- [ ] **Step 11：收尾。** 更新记忆文件 `/Users/minggao/.claude/projects/-Users-minggao/memory/project_film_radar.md`：「已看过」现在是仓库名单＋Issue 勾选，同步工作流是唯一部署者，本机跑要 `GH_TOKEN`，迁移已完成（编号映射），第一次用新代码的出刊日期待观察；`MEMORY.md` 里对应那一行同步更新。问用户要不要删掉 worktree 和 `feat/watched` 分支。
