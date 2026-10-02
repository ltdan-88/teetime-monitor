"""YAML loading shared by every config file this app reads.

PyYAML implements YAML 1.1, where a bare `on`/`off`/`yes`/`no` is a boolean. Our
files are also written by the GUI (macos/Sources/YAML.swift), and a bare
`hcp_preference: off` there loaded as `False` and crashed the Preferences
dropdown (2026-10-01). This loader treats only `true`/`false` as booleans, so
those words stay the plain strings a person (or the GUI) meant.
"""

import re

import yaml


class _Loader(yaml.SafeLoader):
    pass


_BOOL_TAG = "tag:yaml.org,2002:bool"
_Loader.yaml_implicit_resolvers = {
    first_char: [(tag, regexp) for tag, regexp in resolvers if tag != _BOOL_TAG]
    for first_char, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver(_BOOL_TAG, re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF"))


def safe_load(stream):
    return yaml.load(stream, Loader=_Loader)
