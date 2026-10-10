# OpenCTT - course timetabler. Derived from OpenCTT by Ivan Ćurak.
# This program is free software; you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation; either version 2 of
# the License, or (at your option) any later version. See the LICENSE file.
"""Translations without a build step: the English source text is the key, catalogs live in octt/locales.

Pure Python, so the rules / reports layers can use it too. Missing keys fall back to English, never crash.
  tr("Add room…")                      -> translated text   (modules import it as: from octt.i18n import t as tr)
  tr("{n} lessons left", n=3)          -> str.format with the translated pattern
  N_("Mon")                            -> marks a literal for the catalogs; translate later with tr()
"""
import importlib

LANGUAGES = {"en": "English", "fr": "Français", "ar": "العربية"}  # always shown in their own script
RTL = {"ar"}
_lang = "en"
_cache: dict[str, dict] = {}


def set_language(code: str) -> str:
    global _lang
    _lang = code if code in LANGUAGES else "en"
    return _lang


def language() -> str:
    return _lang


def is_rtl() -> bool:
    return _lang in RTL


def catalog(code: str) -> dict:
    if code not in _cache:
        _cache[code] = {} if code == "en" else importlib.import_module(f"octt.locales.{code}").MESSAGES
    return _cache[code]


def menu_path(*parts: str) -> str:
    """'Data ▸ Add group…' in the current language (arrow mirrored for right-to-left, & mnemonics dropped).
    Pass N_("...") literals so the catalogs pick them up."""
    return (" ◂ " if is_rtl() else " ▸ ").join(t(p).replace("&", "") for p in parts)


def N_(msg: str) -> str:
    return msg


def t(msg: str, **kw) -> str:
    text = catalog(_lang).get(msg, msg)
    if not kw:
        return text
    try:
        return text.format(**kw)
    except (KeyError, IndexError, ValueError):  # a broken translation must not take the app down
        return msg.format(**kw)
