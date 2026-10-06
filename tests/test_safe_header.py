"""SafeHeader answers Textual's too-early HeaderTitle lookup instead of crashing the app."""

import pytest
from textual.css.query import NoMatches
from textual.widgets import Header

from src import safe_header
from src.safe_header import SafeHeader


def test_a_missing_header_title_becomes_a_noop_and_schedules_a_refresh(monkeypatch):
    def not_composed_yet(self, selector, expect_type=None):
        raise NoMatches("No nodes match 'HeaderTitle' on Header()")

    monkeypatch.setattr(Header, "query_one", not_composed_yet)
    header = SafeHeader()
    scheduled = []
    monkeypatch.setattr(header, "call_after_refresh", lambda callback: scheduled.append(callback))

    result = header.query_one(safe_header.HeaderTitle)
    result.update("anything")  # the no-op accepts the update Textual attempts
    assert scheduled == [header._refresh_title_later]


def test_other_lookups_still_raise(monkeypatch):
    def not_found(self, selector, expect_type=None):
        raise NoMatches("nope")

    monkeypatch.setattr(Header, "query_one", not_found)
    with pytest.raises(NoMatches):
        SafeHeader().query_one("#something-else")
