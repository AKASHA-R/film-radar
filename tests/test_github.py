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
