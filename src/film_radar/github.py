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
