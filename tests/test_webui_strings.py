"""Every text the web UI's scripts ask for exists in English and German (2026-10-10).

The page's own strings are in src/webui/static/strings.json; the app catalog (src/i18n.py) fills in
what the terminal app already says (settings labels, the heatmap legend ...). A key the scripts use
that neither has would show as the raw key on screen, so look for those here.
"""

import json
import re
from pathlib import Path

from src import i18n
from src.webui import data  # noqa: F401  (imported so a broken package fails here, not in the browser)

STATIC = Path(__file__).resolve().parent.parent / "src" / "webui" / "static"
LOCAL = json.loads((STATIC / "strings.json").read_text(encoding="utf-8"))
NAMESPACES = (
    "action|addclub|ai|booking|club|cond|empty|error|heatmap|legend|login|players|preferences|preview|reason|search|settings|tip|updated"
)
LITERAL = re.compile(rf"""['"]((?:{NAMESPACES})(?:\.[a-z_0-9]+)+|updated_\w+|expand|collapse|free|anonymous|refreshing|legend|club|course)['"]""")
# keys built at run time: (prefix, the suffixes the scripts build)
DYNAMIC = {
    "cond.": ["sun", "partly", "cloud", "fog", "drizzle", "rain", "snow", "storm"],
    "reason.": ["dry", "calm", "mild", "room_around", "quiet", "daylight_spare"],
    "login.": ["username_required", "password_required", "bad_input"],
    "ai.": ["provider_required", "unknown_provider", "api_key_required", "bad_input", "invalid_key", "network_error"],
    "addclub.refresh_": ["needs_login", "needs_a_club", "fetch_failed"],
    "preview.": ["no_tee_sheet", "login_required", "course_fetch_failed", "missing_club_id"],
    "heatmap.": ["tournament", "public_holiday", "vacation"],
    "players.sort.": ["name", "friend", "gender", "handicap", "member"],
    "players.member_status.": ["member", "guest"],
    "search.flag.": ["rain", "wind", "temp"],
    "search.flag_tip.": ["rain", "wind", "temp"],
}


def _used_keys() -> set[str]:
    keys = set()
    for script in STATIC.glob("*.js"):
        text = script.read_text(encoding="utf-8")
        keys.update(match.group(1) for match in LITERAL.finditer(text))
    for prefix, suffixes in DYNAMIC.items():
        keys.update(prefix + suffix for suffix in suffixes)
    # a literal that is only the start of a dynamic key ("cond.", "login.") is not a key itself
    return {key for key in keys if not key.endswith(".") and key not in DYNAMIC}


def _known(language: str) -> set[str]:
    return set(LOCAL[language]) | set(i18n._STRINGS[language])


def test_both_languages_carry_the_same_page_strings():
    assert set(LOCAL["en"]) == set(LOCAL["de"])


def test_every_key_the_scripts_use_exists_in_english_and_german():
    used = _used_keys()
    assert len(used) > 100  # the scan found the scripts' keys
    for language in ("en", "de"):
        missing = sorted(used - _known(language))
        assert not missing, f"{language}: missing {missing}"


def test_placeholders_match_between_languages():
    for key, english in LOCAL["en"].items():
        german = LOCAL["de"][key]
        assert sorted(re.findall(r"\{(\w+)\}", english)) == sorted(re.findall(r"\{(\w+)\}", german)), key


def test_no_string_is_left_untranslated_by_accident():
    same = [k for k, v in LOCAL["en"].items() if v == LOCAL["de"][k] and len(v) > 12 and k != "app.title"]
    assert not same, same
