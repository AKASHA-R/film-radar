import json
from datetime import date

import pytest
import requests

from film_radar.cineplex import (
    API_BASE, KEY_HEADER, USER_AGENT, CineplexClient, CineplexError, candidate_keys, script_urls,
)
from helpers import FakeResponse, FakeSession, fixture_json, fixture_text

HOME = fixture_text("cineplex", "homepage.html")
THEATRICAL_SRC = "https://www.cineplex.com/next-static-files/_next/static/chunks/1401-40ddb78952203580.js"
BANNER_SRC = "https://www.cineplex.com/next-static-files/_next/static/chunks/pages/_app-6c79cb18258c580e.js"
GOOD_KEY = "0123456789abcdef0123456789abcdef"
BANNER_KEY = "fedcba9876543210fedcba9876543210"

MOVIES_URL = API_BASE + "/v2/movies?language=en"
THEATRES_URL = API_BASE + "/v1/theatres?language=en&latitude=43.6532&longitude=-79.3832&range=30"
BOOKABLE_URL = API_BASE + "/v1/dates/bookable?language=en&locationId=7130"
SHOWTIMES_URL = API_BASE + "/v1/showtimes?language=en&locationId=7130&date=10/04/2026"
NO_SHOWTIMES_URL = API_BASE + "/v1/showtimes?language=en&locationId=7130&date=11/01/2026"
DETAIL_URL = "https://www.cineplex.com/movie/digger"

DENIED = '{ "statusCode": 401, "message": "Access denied due to missing subscription key." }'


def make_session(accepted_keys=(GOOD_KEY,), overrides=None):
    def movies(url, headers):
        if headers.get(KEY_HEADER) in accepted_keys:
            return FakeResponse(200, fixture_text("cineplex", "movies_v2.json"))
        return FakeResponse(401, DENIED)

    routes = {
        "https://www.cineplex.com/": FakeResponse(200, HOME),
        THEATRICAL_SRC: FakeResponse(200, fixture_text("cineplex", "chunk_theatrical.js")),
        BANNER_SRC: FakeResponse(200, fixture_text("cineplex", "chunk_banner.js")),
        MOVIES_URL: movies,
        THEATRES_URL: FakeResponse(200, fixture_text("cineplex", "theatres.json")),
        BOOKABLE_URL: FakeResponse(200, fixture_text("cineplex", "dates_bookable_7130.json")),
        SHOWTIMES_URL: FakeResponse(200, fixture_text("cineplex", "showtimes_7130_2026-10-04.json")),
        NO_SHOWTIMES_URL: FakeResponse(204, ""),
        DETAIL_URL: FakeResponse(200, fixture_text("cineplex", "movie_detail_digger.html")),
    }
    routes.update(overrides or {})
    return FakeSession(routes)


def make_client(session):
    sleeps = []
    return CineplexClient(session, sleep=sleeps.append), sleeps


def movies_payload(mutate):
    data = fixture_json("cineplex", "movies_v2.json")
    mutate(data)
    return FakeResponse(200, json.dumps(data))


# ---- 取密钥 ----

def test_script_urls_come_from_real_homepage_tags():
    urls = script_urls(HOME)
    assert len(urls) == 15
    assert THEATRICAL_SRC in urls
    assert BANNER_SRC in urls
    assert all(u.startswith("https://") for u in urls)


def test_script_urls_resolve_relative_src():
    html = '<script src="/_next/static/chunks/a.js" defer=""></script>'
    assert script_urls(html) == ["https://www.cineplex.com/_next/static/chunks/a.js"]


def test_theatrical_key_is_preferred_regardless_of_script_order():
    banner = fixture_text("cineplex", "chunk_banner.js")
    theatrical = fixture_text("cineplex", "chunk_theatrical.js")
    assert candidate_keys([banner, theatrical]) == [GOOD_KEY, BANNER_KEY]
    assert candidate_keys([theatrical, banner]) == [GOOD_KEY, BANNER_KEY]


def test_key_is_extracted_and_sent_on_api_calls():
    session = make_session()
    client, _ = make_client(session)
    assert client.key() == GOOD_KEY
    client.theatres(43.6532, -79.3832)
    url, headers = session.calls[-1]
    assert url == THEATRES_URL
    assert headers[KEY_HEADER] == GOOD_KEY


def test_falls_back_to_other_key_when_preferred_is_rejected():
    client, _ = make_client(make_session(accepted_keys=(BANNER_KEY,)))
    assert client.key() == BANNER_KEY


def test_fails_when_every_key_is_rejected():
    client, _ = make_client(make_session(accepted_keys=()))
    with pytest.raises(CineplexError, match="均被接口拒绝") as info:
        client.key()
    assert GOOD_KEY not in str(info.value)
    assert BANNER_KEY not in str(info.value)


def test_fails_when_no_key_in_scripts():
    session = make_session(overrides={
        THEATRICAL_SRC: FakeResponse(200, "let l=1;"),
        BANNER_SRC: FakeResponse(200, "let m=2;"),
    })
    client, _ = make_client(session)
    with pytest.raises(CineplexError, match="没有找到订阅密钥"):
        client.key()


def test_fails_when_homepage_has_no_scripts():
    session = make_session(overrides={"https://www.cineplex.com/": FakeResponse(200, "<html></html>")})
    client, _ = make_client(session)
    with pytest.raises(CineplexError, match="脚本"):
        client.key()


def test_fails_when_homepage_is_blocked():
    session = make_session(overrides={"https://www.cineplex.com/": FakeResponse(403, "")})
    client, _ = make_client(session)
    with pytest.raises(CineplexError, match="首页: HTTP 403"):
        client.key()


# ---- 片单 ----

def test_movies_returns_all_items_with_film_categories():
    client, _ = make_client(make_session())
    movies = client.movies()
    assert len(movies) == 29
    ninja = next(m for m in movies if m["id"] == 61994)
    assert ninja["isEvent"] is True
    assert "Anime" in ninja["filmCategories"]


def test_movies_does_not_fetch_the_list_twice():
    session = make_session()
    client, _ = make_client(session)
    client.movies()
    client.movies()
    assert [url for url, _ in session.calls].count(MOVIES_URL) == 1


def test_movies_rejects_item_missing_a_required_field():
    def drop(data):
        del data["items"][3]["filmCategories"]

    client, _ = make_client(make_session(overrides={MOVIES_URL: lambda u, h: movies_payload(drop)}))
    with pytest.raises(CineplexError, match=r"片单\[3\].*filmCategories"):
        client.movies()


def test_movies_rejects_wrong_type():
    def wrong(data):
        data["items"][0]["isEvent"] = "false"

    client, _ = make_client(make_session(overrides={MOVIES_URL: lambda u, h: movies_payload(wrong)}))
    with pytest.raises(CineplexError, match=r"片单\[0\].*isEvent"):
        client.movies()


@pytest.mark.parametrize("bad", ["", "not-a-date", "2026-13-45T00:00:00"])
def test_movies_rejects_unparseable_release_date(bad):
    def break_date(data):
        data["items"][5]["releaseDate"] = bad

    client, _ = make_client(make_session(overrides={MOVIES_URL: lambda u, h: movies_payload(break_date)}))
    with pytest.raises(CineplexError, match=r"片单\[5\].*releaseDate"):
        client.movies()


def test_movies_accepts_missing_poster():
    def no_poster(data):
        data["items"][0]["mediumPosterImageUrl"] = None

    client, _ = make_client(make_session(overrides={MOVIES_URL: lambda u, h: movies_payload(no_poster)}))
    assert len(client.movies()) == 29


def test_movies_rejects_payload_without_items():
    session = make_session(overrides={MOVIES_URL: lambda u, h: FakeResponse(200, '{"totalCount": 0}')})
    client, _ = make_client(session)
    with pytest.raises(CineplexError, match="items"):
        client.movies()


# ---- 影院 ----

def test_theatres_merges_nearby_and_other():
    client, _ = make_client(make_session())
    theatres = client.theatres(43.6532, -79.3832)
    assert len(theatres) == 31
    assert all(isinstance(t["location"]["distanceToOriginInMeters"], float) for t in theatres)
    assert theatres[0]["theatreId"] == 7130


def test_theatres_rejects_missing_distance():
    data = fixture_json("cineplex", "theatres.json")
    del data["otherTheatres"][0]["location"]["distanceToOriginInMeters"]
    session = make_session(overrides={THEATRES_URL: FakeResponse(200, json.dumps(data))})
    client, _ = make_client(session)
    with pytest.raises(CineplexError, match="distanceToOriginInMeters"):
        client.theatres(43.6532, -79.3832)


# ---- 可订票日期与排片 ----

def test_bookable_dates_are_parsed():
    client, _ = make_client(make_session())
    days = client.bookable_dates(7130)
    assert len(days) == 92
    assert days[0] == date(2026, 10, 3)
    assert date(2026, 11, 1) not in days


def test_showtimes_returns_film_ids_including_event_films():
    client, _ = make_client(make_session())
    ids = client.showtimes(7130, date(2026, 10, 4))
    assert sorted(ids) == [37885, 38401, 38459, 61994, 61995]


def test_showtimes_204_means_no_showtimes():
    client, _ = make_client(make_session())
    assert client.showtimes(7130, date(2026, 11, 1)) == []


def test_showtimes_server_error_is_a_failure():
    session = make_session(overrides={SHOWTIMES_URL: FakeResponse(500, "")})
    client, _ = make_client(session)
    with pytest.raises(CineplexError, match="排片: HTTP 500"):
        client.showtimes(7130, date(2026, 10, 4))


def test_showtimes_rejects_non_json():
    session = make_session(overrides={SHOWTIMES_URL: FakeResponse(200, "<html>blocked</html>")})
    client, _ = make_client(session)
    with pytest.raises(CineplexError, match="排片: 响应不是 JSON"):
        client.showtimes(7130, date(2026, 10, 4))


# ---- 详情页 ----

def test_movie_details_from_real_page():
    client, _ = make_client(make_session())
    details = client.movie_details("digger")
    assert details["synopsis"].startswith("Academy Award winner Tom Cruise")
    assert details["director"] == "Alejandro G. Iñárritu"
    assert details["starring"] == "Tom Cruise"
    assert set(details) == {"synopsis", "director", "starring"}


def test_movie_details_without_next_data():
    session = make_session(overrides={DETAIL_URL: FakeResponse(200, "<html><body>nothing</body></html>")})
    client, _ = make_client(session)
    with pytest.raises(CineplexError, match="__NEXT_DATA__"):
        client.movie_details("digger")


def test_movie_details_404():
    client, _ = make_client(make_session())
    with pytest.raises(CineplexError, match="HTTP 404"):
        client.movie_details("no-such-film")


# ---- 请求卫生 ----

def test_network_errors_become_cineplex_errors():
    """requests 的超时、连接重置不是 CineplexError。不包起来，main 就认不出这是"Cineplex 抓取"环节的失败。"""
    class Down:
        def get(self, url, headers=None, timeout=None):
            raise requests.ConnectionError("Connection reset by peer")

    client = CineplexClient(Down(), sleep=lambda seconds: None)
    with pytest.raises(CineplexError, match="网络错误.*ConnectionError"):
        client.movies()


def test_every_request_is_throttled_and_carries_user_agent():
    session = make_session()
    client, sleeps = make_client(session)
    client.movies()
    client.showtimes(7130, date(2026, 10, 4))
    assert len(sleeps) == len(session.calls)
    assert all(s == 0.3 for s in sleeps)
    assert all(headers["User-Agent"] == USER_AGENT for _, headers in session.calls)
