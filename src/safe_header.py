"""A `Header` that survives Textual's own startup race (2026-10-06).

Textual's `Header` registers title watchers in its `_on_mount()`; they fire at once and do
`self.query_one(HeaderTitle).update(...)`, which raises `NoMatches` when the header's child
widgets are not composed yet. Under load (a slow CI runner, a screen pushed and popped within
milliseconds) that unhandled error in a message handler ends the whole app. Only the
`NoScreen` case is caught upstream. `SafeHeader` answers that one lookup with a no-op and
refreshes the title once the header has finished composing, so the worst case is a title that
appears a moment later instead of an app exit.

Only `HeaderTitle`, a Textual-internal class, is imported from a private module; if a Textual
release moves it, `SafeHeader` is just the plain `Header`.
"""

from textual.css.query import NoMatches
from textual.widgets import Header

try:
    from textual.widgets._header import HeaderTitle
except ImportError:  # pragma: no cover -- a future Textual layout
    HeaderTitle = None


class _NoopTitle:
    def update(self, *args, **kwargs) -> None:
        return None


class SafeHeader(Header):
    def query_one(self, selector, expect_type=None):
        try:
            return super().query_one(selector, expect_type)
        except NoMatches:
            if HeaderTitle is None or selector is not HeaderTitle:
                raise
            self.call_after_refresh(self._refresh_title_later)
            return _NoopTitle()

    def _refresh_title_later(self) -> None:
        try:
            super().query_one(HeaderTitle).update(self.format_title())
        except NoMatches:
            pass  # still not composed (the screen is going away); nothing to show
