from datetime import date

from film_radar.candidates import build_candidates
from helpers import fixture_json, make_candidate


def test_make_candidate_has_exactly_the_keys_of_a_real_candidate(settings):
    movies = fixture_json("cineplex", "movies_v2.json")["items"]
    real = build_candidates(movies, [], date(2026, 10, 3), settings)[0][0]
    fake = make_candidate(1)
    assert set(fake) == set(real)
    assert set(fake["versions"][0]) == set(real["versions"][0])
