"""The tournament calendar (cat=ts_calendar): parsing a page of made-up rows that mirror the real markup."""

import pytest

from src import scraper
from src.models import Tournament


def _row(
    ident,
    stamp,
    name,
    subtitle="Round A",
    holes=18,
    guests=True,
    deadline=None,
    register="live",
) -> str:
    """One calendar row shaped like the real page (confirmed 2026-10-16); the names are invented."""
    gate = " pcco-disabled" if register == "disabled" else ""
    when = f'<span class="hidden x1">Registration deadline: {deadline}</span>' if deadline else ""
    icon = "fa-check" if guests else "fa-times"
    return f"""<tr class="tk-pointer month_10 year_2026 pcco-xcal-list-item" data-id="{ident}" data-category="G">
      <td class="tk-intern tk-public numholes-{holes}"><time datetime="{stamp}" class="icon"></time></td>
      <td class="tk-body-name">course name and group<span class="tk-turnier"></span><span class="tk-public">{name}</span>
        <span class="tk-club">{subtitle}</span><br><span class="tk-club">{stamp}</span>
        <span class="tk-art">tk-art 1 Maximum HCP: 54,0</span>{when}</td>
      <td class="tk-td-intern"><i class="fa {icon} tk-icon tk-icon-guest"></i></td>
      <td class="hidden-all"><button>Save to calendar</button></td>
      <td class="hidden-all"><a class="btn{gate}">Register</a></td>
      <td class="hidden-all"><a class="href-detail" href="/clubs/0000009/app.php?cat=ts_calendar&sub=detail&id={ident}">Details</a></td>
      <td class="hidden-all"><a class="href-entrylist" href="/clubs/0000009/app.php?cat=ts_calendar&sub=entrylist&id={ident}">Entry list</a></td>
    </tr>"""


def _page(*rows: str) -> str:
    return f'<html><body class="cat-ts_calendar"><table><tbody>{"".join(rows)}</tbody></table></body></html>'


def test_a_row_is_read_in_full():
    page = _page(
        _row(
            "501",
            "Sun., 2026-10-18, 11:00 o'clock",
            "Autumn Trophy",
            "Round B",
            16,
            True,
            "Thu, 2026-10-15, 10:00 o'clock",
            "disabled",
        )
    )
    assert scraper._parse_tournaments_html(page) == [
        Tournament(
            id="501",
            date="2026-10-18",
            time="11:00",
            name="Autumn Trophy",
            subtitle="Round B",
            holes=16,
            guests=True,
            deadline="2026-10-15 10:00",
            register_open=False,
        )
    ]


def test_a_date_without_a_time_and_a_row_without_deadline_or_guests():
    [item] = scraper._parse_tournaments_html(_page(_row("7", "Sat., 2026-10-17", "Club Masters", guests=False)))
    assert (item.date, item.time, item.deadline, item.guests, item.register_open) == ("2026-10-17", None, None, False, True)


def test_the_german_page_reads_the_same():
    page = _page(_row("9", "So., 18.10.2026, 09:30 Uhr", "Herbstpokal", deadline="Do., 15.10.2026, 10:00 Uhr"))
    [item] = scraper._parse_tournaments_html(page)
    assert (item.date, item.time, item.deadline, item.subtitle) == ("2026-10-18", "09:30", "2026-10-15 10:00", "Round A")


def test_rows_come_out_in_date_order_and_the_entry_list_is_never_read():
    page = _page(
        _row("2", "Tue., 2026-11-03, 15:00 o'clock", "Later"), _row("1", "Sun., 2026-10-18, 11:00 o'clock", "Sooner")
    )
    found = scraper._parse_tournaments_html(page)
    assert [item.name for item in found] == ["Sooner", "Later"]
    assert not any("entry" in repr(item).lower() for item in found)


def test_a_calendar_without_tournaments_is_empty_and_an_unknown_page_is_refused():
    assert scraper._parse_tournaments_html('<html><body class="cat-ts_calendar"><p>No events</p></body></html>') == []
    with pytest.raises(NotImplementedError):
        scraper._parse_tournaments_html("<html><body><h1>Something else</h1></body></html>")
