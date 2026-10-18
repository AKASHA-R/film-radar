import pytest
import requests

from film_radar.github import API, GitHubClient, GitHubError, client_from_env
from film_radar.watched import Issue
from helpers import FakeGitHub

REPO = "AKASHA-R/film-radar"
FIRST = f"{API}/repos/{REPO}/issues?labels=edition&state=all&per_page=100"
SECOND = f"{API}/repositories/1/issues?labels=edition&state=all&per_page=100&page=2"
BOT = {"login": "github-actions[bot]"}
NOT_JSON = object()


class Response:
    def __init__(self, status=200, data=None, link="", text=""):
        self.status_code = status
        self._data = data
        self.text = text
        self.headers = {"Link": link} if link else {}

    def json(self):
        if self._data is NOT_JSON:                      # 和 requests 一样：正文不是 JSON 时抛 ValueError 的子类
            raise requests.JSONDecodeError("Expecting value", self.text, 0)
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


def test_edition_issues_opened_by_hand_are_read_too():
    """推送失败后，用户照 README 从 edition-backup 产物手工开 edition Issue；只认机器人开的话，里面的勾永远不生效。
    是不是程序管理的 Issue 由 edition 标签和 parse_issue 的标记规则决定，不看作者。"""
    gh, _ = client({("GET", FIRST): Response(data=[item(7, user={"login": "AKASHA-R"}), item(8, user=None), item(5),
                                                  item(4, user={"login": "AKASHA-R"}, pull_request={"url": "x"})])})
    assert [i.number for i in gh.edition_issues()] == [7, 8, 5]


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
    (Response(data=NOT_JSON, text="<html>Sign in to the Wi-Fi</html>"), "不是 JSON"),     # 代理或认证页回了 200
])
def test_http_and_network_errors_become_github_errors(route, message):
    gh, _ = client({("GET", FIRST): route, ("GET", f"{API}/repos/{REPO}/issues/5"): route})
    with pytest.raises(GitHubError, match=message):
        gh.edition_issues()
    with pytest.raises(GitHubError, match=message):
        gh.issue_body(5)


def test_http_errors_say_what_github_said():
    """403 有好几种原因（权限不够、限流），只写状态码的话失败 Issue 里看不出是哪一种。"""
    url = f"{API}/repos/{REPO}/issues/5"
    gh, _ = client({("PATCH", url): Response(status=403, text='{"message":"Resource not accessible by integration",\n'
                                                                 '"documentation_url":"https://docs.github.com"}')})
    with pytest.raises(GitHubError) as caught:
        gh.update_body(5, "新正文")
    message = str(caught.value)
    assert message.startswith(f"PATCH {url}: HTTP 403 ") and "Resource not accessible by integration" in message
    assert "\n" not in message


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
