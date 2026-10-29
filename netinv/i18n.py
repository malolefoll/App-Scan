"""Tiny translation helper.

Every user-facing string lives in locales/<lang>.json. To add a language,
copy locales/en.json to locales/<code>.json and translate the values.
"""

from __future__ import annotations

import json
import locale
import os
from functools import cache
from importlib import resources

DEFAULT_LANG = "en"


def available_languages() -> list[str]:
    folder = resources.files("netinv").joinpath("locales")
    return sorted(p.name[:-5] for p in folder.iterdir() if p.name.endswith(".json"))


@cache
def _load(lang: str) -> dict[str, str]:
    path = resources.files("netinv").joinpath(f"locales/{lang}.json")
    return json.loads(path.read_text(encoding="utf-8"))


def detect_language() -> str:
    """Pick the language from NETINV_LANG, then LANG / system locale, else English."""
    candidates = [os.environ.get("NETINV_LANG"), os.environ.get("LANG")]
    try:
        candidates.append(locale.getlocale()[0])
    except ValueError:
        pass
    langs = available_languages()
    for c in candidates:
        if c:
            code = c.split(".")[0].split("_")[0].lower()
            if code in langs:
                return code
    return DEFAULT_LANG


class Translator:
    def __init__(self, lang: str | None = None):
        lang = lang or detect_language()
        if lang not in available_languages():
            lang = DEFAULT_LANG
        self.lang = lang
        self._messages = _load(lang)
        self._fallback = _load(DEFAULT_LANG)

    def __call__(self, key: str, **kwargs) -> str:
        template = self._messages.get(key) or self._fallback.get(key) or key
        return template.format(**kwargs)
