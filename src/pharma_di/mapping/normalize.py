"""Header text normalization (IMPLEMENTATION_PLAN.md section 4.6):

- `basic_normalize_path` is tier 2's transform — lowercase + strip only,
  the exact same logic as `HeaderNode.normalized_key` (schemas/layout.py),
  replicated here as a standalone function so it can be applied to
  config-file path lists too, not just an already-constructed HeaderNode.
- `expand_abbreviations` is tier 3's transform — strip punctuation, expand
  a whole-word abbreviation table, collapse whitespace. Deliberately
  a SEPARATE, later tier than tier 2: `config/column_mappings.yaml` already
  lists multiple exact path variants for the same field (e.g.
  opening_quantity's paths include both ["opening","qty."] and
  ["opening","qty"]) precisely so common, anticipated variants match at
  tier 2 without needing any transformation — tier 3 only has to cover
  what tier 2's explicit variants don't.
"""
from __future__ import annotations

import re

# Default abbreviation table (IMPLEMENTATION_PLAN.md section 4.6's exact
# entries) — used when a caller doesn't pass its own. P12: the live pipeline
# now passes config.py::load_abbreviations()'s config-driven table instead
# (config/column_mappings.yaml's `abbreviations:` key) via
# mapping/resolver.py::DictionaryResolver, so a new distributor's own
# abbreviation style is a config change, not a code change; this module
# constant remains the default for direct callers (e.g. unit tests) that
# don't pass one.
_ABBREVIATIONS = {
    "qty": "quantity",
    "rcvd": "received",
    "rtn": "return",
    "prch": "purchase",
    "clos": "closing",
    "retn": "return",
    "recpt": "receipt",
    "op": "opening",
}

_PUNCTUATION_PATTERN = re.compile(r"[.,;:'\"/\\()\[\]]")
_WHITESPACE_PATTERN = re.compile(r"\s+")


def basic_normalize_path(path: list[str]) -> str:
    return "|".join(p.strip().lower() for p in path)


def expand_abbreviations(text: str, abbreviations: dict[str, str] | None = None) -> str:
    """Whole-word only, so e.g. "op" doesn't fire inside "opening" or
    "shop" — split on whitespace first, substitute per word, rejoin.
    `abbreviations` defaults to this module's own table when not given."""
    table = abbreviations if abbreviations is not None else _ABBREVIATIONS
    lowered = text.lower()
    despuncted = _PUNCTUATION_PATTERN.sub(" ", lowered)
    words = [table.get(w, w) for w in despuncted.split()]
    return _WHITESPACE_PATTERN.sub(" ", " ".join(words)).strip()


def expand_abbreviations_path(path: list[str], abbreviations: dict[str, str] | None = None) -> str:
    return "|".join(expand_abbreviations(p, abbreviations) for p in path)
