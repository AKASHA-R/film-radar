"""Cineplex 客户端。

Cineplex 没有公开 API。网站前端调用 apis.cineplex.com，订阅密钥写在前端脚本里。
这里在运行时从首页引用的脚本里取密钥，只读调用。密钥只留在内存里。
"""
from __future__ import annotations

import json
import re
import time
from datetime import date
from typing import Callable

API_BASE = "https://apis.cineplex.com/prod/cpx/theatrical/api"
SITE = "https://www.cineplex.com"
KEY_HEADER = "Ocp-Apim-Subscription-Key"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_SCRIPT_SRC = re.compile(r'<script[^>]+src="([^"]*/_next/static/[^"]+\.js)"')
_ANY_KEY = re.compile(r'"Ocp-Apim-Subscription-Key":"([0-9a-f]{32})"')
_THEATRICAL_KEY = re.compile(
    r'cpx/theatrical/api"[^;]{0,300}?"Ocp-Apim-Subscription-Key":"([0-9a-f]{32})"'
)
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)

MOVIE_FIELDS = {
    "id": int,
    "name": str,
    "releaseDate": str,
    "filmUrl": str,
    "language": str,
    "genres": list,
    "filmCategories": list,
    "ratings": list,
    "distributor": str,
    "runtimeInMinutes": int,
    "isNowPlaying": bool,
    "isComingSoon": bool,
    "isEvent": bool,
}
THEATRE_FIELDS = {"theatreId": int, "theatreName": str, "location": dict}


class CineplexError(Exception):
    pass


def script_urls(homepage_html: str) -> list[str]:
    urls: list[str] = []
    for src in _SCRIPT_SRC.findall(homepage_html):
        url = src if src.startswith("http") else SITE + src
        if url not in urls:
            urls.append(url)
    return urls


def candidate_keys(scripts: list[str]) -> list[str]:
    """先列与电影接口基址写在同一语句里的密钥，再列其余密钥。"""
    preferred: list[str] = []
    for text in scripts:
        for key in _THEATRICAL_KEY.findall(text):
            if key not in preferred:
                preferred.append(key)
    others: list[str] = []
    for text in scripts:
        for key in _ANY_KEY.findall(text):
            if key not in preferred and key not in others:
                others.append(key)
    return preferred + others


def require(obj, spec: dict, where: str) -> None:
    if not isinstance(obj, dict):
        raise CineplexError(f"{where}: 期望对象，实为 {type(obj).__name__}")
    for name, expected in spec.items():
        if name not in obj:
            raise CineplexError(f"{where}: 缺少字段 {name}")
        if not isinstance(obj[name], expected):
            raise CineplexError(
                f"{where}: 字段 {name} 类型异常，实为 {type(obj[name]).__name__}"
            )


class CineplexClient:
    def __init__(self, session, sleep: Callable[[float], None] = time.sleep, min_interval: float = 0.3):
        self._session = session
        self._sleep = sleep
        self._min_interval = min_interval
        self._key: str | None = None
        self._movies_response = None

    def _get(self, url: str, headers: dict | None = None):
        self._sleep(self._min_interval)
        merged = {"User-Agent": USER_AGENT}
        merged.update(headers or {})
        return self._session.get(url, headers=merged, timeout=30)

    @staticmethod
    def _json(response, where: str):
        try:
            return response.json()
        except ValueError as e:
            raise CineplexError(f"{where}: 响应不是 JSON") from e

    def _api(self, path: str, where: str):
        """返回解析后的 JSON；HTTP 204 返回 None。"""
        response = self._get(API_BASE + path, {KEY_HEADER: self.key()})
        if response.status_code == 204:
            return None
        if response.status_code != 200:
            raise CineplexError(f"{where}: HTTP {response.status_code}")
        return self._json(response, where)

    def key(self) -> str:
        if self._key is not None:
            return self._key
        home = self._get(SITE + "/")
        if home.status_code != 200:
            raise CineplexError(f"首页: HTTP {home.status_code}")
        urls = script_urls(home.text)
        if not urls:
            raise CineplexError("首页: 没有找到 _next/static 脚本")
        scripts = []
        for url in urls:
            response = self._get(url)
            if response.status_code == 200:
                scripts.append(response.text)
        keys = candidate_keys(scripts)
        if not keys:
            raise CineplexError("前端脚本里没有找到订阅密钥")
        for key in keys:
            response = self._get(API_BASE + "/v2/movies?language=en", {KEY_HEADER: key})
            if response.status_code == 200:
                self._key = key
                self._movies_response = response
                return key
        raise CineplexError(f"找到 {len(keys)} 把密钥，均被接口拒绝")

    def movies(self) -> list[dict]:
        self.key()  # 试密钥时已经把片单取回来了
        data = self._json(self._movies_response, "片单")
        require(data, {"items": list}, "片单")
        for i, item in enumerate(data["items"]):
            where = f"片单[{i}]"
            require(item, MOVIE_FIELDS, where)
            try:
                date.fromisoformat(item["releaseDate"][:10])
            except ValueError as e:
                raise CineplexError(f"{where}: releaseDate 无法解析: {item['releaseDate']!r}") from e
        return data["items"]

    def theatres(self, lat: float, lon: float) -> list[dict]:
        data = self._api(
            f"/v1/theatres?language=en&latitude={lat}&longitude={lon}&range=30", "影院"
        )
        require(data, {"nearbyTheatres": list, "otherTheatres": list}, "影院")
        theatres = data["nearbyTheatres"] + data["otherTheatres"]
        for i, theatre in enumerate(theatres):
            require(theatre, THEATRE_FIELDS, f"影院[{i}]")
            require(theatre["location"], {"distanceToOriginInMeters": (int, float)}, f"影院[{i}].location")
        return theatres

    def bookable_dates(self, theatre_id: int) -> list[date]:
        data = self._api(f"/v1/dates/bookable?language=en&locationId={theatre_id}", "可订票日期")
        if data is None:
            return []
        if not isinstance(data, list):
            raise CineplexError("可订票日期: 期望数组")
        try:
            return [date.fromisoformat(value[:10]) for value in data]
        except (TypeError, ValueError) as e:
            raise CineplexError("可订票日期: 日期格式异常") from e

    def showtimes(self, theatre_id: int, day: date) -> list[int]:
        data = self._api(
            f"/v1/showtimes?language=en&locationId={theatre_id}&date={day.strftime('%m/%d/%Y')}",
            "排片",
        )
        if data is None:  # 204：当天没有排片
            return []
        if not isinstance(data, list) or not data:
            raise CineplexError("排片: 期望非空数组")
        require(data[0], {"dates": list}, "排片[0]")
        ids: list[int] = []
        for entry in data[0]["dates"]:
            require(entry, {"movies": list}, "排片.dates")
            for movie in entry["movies"]:
                require(movie, {"id": int}, "排片.movies")
                if movie["id"] not in ids:
                    ids.append(movie["id"])
        return ids

    def movie_details(self, film_url: str) -> dict:
        where = f"详情页 {film_url}"
        response = self._get(f"{SITE}/movie/{film_url}")
        if response.status_code != 200:
            raise CineplexError(f"{where}: HTTP {response.status_code}")
        match = _NEXT_DATA.search(response.text)
        if not match:
            raise CineplexError(f"{where}: 没有 __NEXT_DATA__")
        try:
            details = json.loads(match.group(1))["props"]["pageProps"]["movieDetails"]
        except (ValueError, KeyError, TypeError) as e:
            raise CineplexError(f"{where}: 结构异常") from e
        require(details, {"synopsis": str}, where)
        return {
            "synopsis": details["synopsis"],
            "director": details.get("director") or "",
            "starring": details.get("starring") or "",
        }
