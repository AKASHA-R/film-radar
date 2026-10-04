# film-radar

多伦多院线双周推荐页。先读 `README.md`；设计决策与 Cineplex 接口实测记录在 `docs/superpowers/specs/2026-10-03-film-radar-design.md`。

## 环境

- 解释器只用 `.venv/bin/python`（Python 3.11）。系统的 `python3` 是 3.9，跑不了。
- 测试：`.venv/bin/python -m pytest -q`。测试不访问网络、不调 Claude。

## 改代码前要知道的

- **是否活动场只看片单，不看排片接口。** 排片接口里每部片的 `isEvent` 不可信。
- **不能按 `isEvent` 一刀切过滤。** 动画重映、活动场恐怖片在 Cineplex 那边都标成 event。只过滤 `filmCategories` 命中 `non_film_categories` 的。
- **所有 Claude 调用走 `llm.py`。** `triage` 和 `review` 只接收一个 caller，不直接碰 SDK。
- **来源白名单只从搜索结果块（`web_search_tool_result`）和 API 附带的引用里取。** 模型写的正文、思考、搜索请求都不算，代码执行结果块（`code_execution_tool_result`）也不算：搜索工具会让模型写代码调用搜索，那些结果是模型自己代码的产出，stderr 会回显它写的网址。依据与实测见 spec 第 9 节。
- **精评的搜索要直接调用（`allowed_callers=["direct"]`）并在提示词里写明预算，别改回默认。** 默认的动态过滤让模型在代码里批量搜索，用光 `max_uses` 后会把已拿到的结果当成「搜索失败」全扔掉（Ninja Scroll 4K 零来源）。也别换成 `response_inclusion=excluded`，它会让白名单取不到网址。依据见 spec 第 9 节「搜索额度」。
- **失败不落盘。** `main.py` 在流水线成功之后才写当期数据和站点。任何异常都要留下 `out/failure.txt`，工作流的失败 Issue 靠它写明环节。
- `config/taste_profile.md` 是喂给模型的提示词输入，不是工程文档。不要往里写系统机制。
- Cineplex 订阅密钥只在内存里用，不写进任何文件。夹具里的两把是假值。

## 验红

改护栏类代码后做缺陷注入时，用 `sh scripts/redcheck.sh <测试文件>`，不要直接跑 pytest。Python 的字节码缓存只看源文件的修改时间（秒级）和大小，同一秒内大小不变的修改会用到旧缓存，出现假红或假绿。

## 测试数据

`tests/fixtures/cineplex/` 是 2026-10-03 的真实响应裁剪件，用它的测试以 2026-10-03 为运行日期。需要变体时在测试里复制一条真实记录改单个字段，不要手写整条记录。`tests/fixtures/claude/research.json` 是一次真实联网搜索调用的响应（长字符串已截断），白名单提取的测试靠它认真实形状。
