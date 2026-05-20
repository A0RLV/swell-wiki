"""Tests for the ClientRouter email-domain mapping (ingest/fathom.py)."""

from __future__ import annotations

from ingest.fathom import ClientRouter


def test_route_basic_match():
    r = ClientRouter({"target-darts.com": "target-darts"})
    assert r.route({"invitees": [{"email": "chris@target-darts.com"}]}) == "target-darts"


def test_route_first_match_wins():
    r = ClientRouter({"a.com": "alpha", "b.com": "beta"})
    item = {"invitees": [{"email": "x@unknown.com"}, {"email": "y@b.com"}]}
    assert r.route(item) == "beta"


def test_route_case_insensitive():
    r = ClientRouter({"Target-Darts.COM": "target-darts"})
    assert r.route({"invitees": [{"email": "Chris@Target-Darts.com"}]}) == "target-darts"


def test_route_no_invitees_returns_default():
    r = ClientRouter({}, default="house")
    assert r.route({"invitees": []}) == "house"
    assert r.route({}) == "house"


def test_route_unknown_domain_returns_default():
    r = ClientRouter({"a.com": "alpha"}, default=None)
    assert r.route({"invitees": [{"email": "x@elsewhere.com"}]}) is None


def test_route_malformed_email():
    r = ClientRouter({"a.com": "alpha"}, default="fallback")
    item = {"invitees": [{"email": ""}, {"email": "noatsign"}]}
    assert r.route(item) == "fallback"


def test_route_missing_email_key():
    r = ClientRouter({"a.com": "alpha"}, default="fallback")
    assert r.route({"invitees": [{"name": "Anonymous"}]}) == "fallback"
