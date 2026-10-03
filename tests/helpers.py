"""测试共用：夹具读取与假的 HTTP 会话。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


def fixture_text(*parts: str) -> str:
    return FIXTURES.joinpath(*parts).read_text(encoding="utf-8")


def fixture_json(*parts: str):
    return json.loads(fixture_text(*parts))


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = ""):
        self.status_code = status_code
        self.text = text

    def json(self):
        return json.loads(self.text)


class FakeSession:
    """按完整 URL 查表返回响应。表里的值可以是 FakeResponse，也可以是 (url, headers) -> FakeResponse 的函数。

    没登记的 `_next/static` 脚本返回空脚本，其余没登记的 URL 返回 404。
    """

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, headers=None, timeout=None):
        headers = dict(headers or {})
        self.calls.append((url, headers))
        if url in self.routes:
            route = self.routes[url]
            return route(url, headers) if callable(route) else route
        if "/_next/static/" in url:
            return FakeResponse(200, "")
        return FakeResponse(404, "")
