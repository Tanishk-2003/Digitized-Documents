"""P13 unit tests for mapping/template_cache.py — the write half of the
template-fingerprint cache (detect/fingerprint.py::lookup_fingerprint was
always read-only by design; this is what actually populates it, closing a
gap that stayed open through P5-P12: config/templates.yaml never left
`fingerprints: {}` no matter how many documents ran through the pipeline).
"""
from __future__ import annotations

import yaml

from pharma_di.detect.fingerprint import leaf_fingerprint_key
from pharma_di.mapping.dictionary import FieldEntry
from pharma_di.mapping.resolver import DictionaryResolver
from pharma_di.mapping.template_cache import save_fingerprint
from pharma_di.schemas.layout import BBox, HeaderNode
from pharma_di.schemas.mapping import MappingStatus, TableContext

_FIELD_ENTRIES = [
    FieldEntry(canonical_field="opening_quantity", paths=[["opening", "qty."]], aliases=["opening stock"]),
    FieldEntry(canonical_field="opening_value", paths=[["opening", "value"]], aliases=["opening value"]),
    FieldEntry(canonical_field="rate", aliases=["rate"]),
]


def _header(path):
    return HeaderNode(path=path, bbox=BBox(x0=0, y0=0, x1=100, y1=20))


# --- save_fingerprint's own file I/O ------------------------------------------


def test_creates_the_file_when_it_does_not_exist(tmp_path):
    templates_file = tmp_path / "templates.yaml"
    assert not templates_file.exists()

    save_fingerprint("abc123", {"field:opening_quantity": "opening_quantity"}, templates_file)

    assert templates_file.exists()
    data = yaml.safe_load(templates_file.read_text(encoding="utf-8"))
    assert data == {"fingerprints": {"abc123": {"field:opening_quantity": "opening_quantity"}}}


def test_adds_a_new_fingerprint_without_disturbing_an_existing_one(tmp_path):
    templates_file = tmp_path / "templates.yaml"
    templates_file.write_text(
        yaml.safe_dump({"fingerprints": {"existing111": {"field:rate": "rate"}}}), encoding="utf-8"
    )

    save_fingerprint("new222", {"field:opening_value": "opening_value"}, templates_file)

    data = yaml.safe_load(templates_file.read_text(encoding="utf-8"))
    assert data["fingerprints"]["existing111"] == {"field:rate": "rate"}
    assert data["fingerprints"]["new222"] == {"field:opening_value": "opening_value"}


def test_overwrites_a_stale_entry_for_the_same_fingerprint_rather_than_merging(tmp_path):
    templates_file = tmp_path / "templates.yaml"
    templates_file.write_text(
        yaml.safe_dump({"fingerprints": {"abc123": {"field:rate": "wrong_field_from_a_stale_run"}}}),
        encoding="utf-8",
    )

    save_fingerprint("abc123", {"field:opening_quantity": "opening_quantity"}, templates_file)

    data = yaml.safe_load(templates_file.read_text(encoding="utf-8"))
    # Replaced entirely, not merged with the stale key — a re-resolved
    # document's mapping should not leave old, possibly-wrong keys behind.
    assert data["fingerprints"]["abc123"] == {"field:opening_quantity": "opening_quantity"}


# --- full round trip: write via template_cache, read via DictionaryResolver ---


def test_a_saved_fingerprint_is_found_on_a_later_resolve_via_tier_1(tmp_path):
    """The real point of this whole mechanism: once a table's mapping is
    cached, a LATER document sharing its fingerprint resolves via tier 1
    (MappingStatus.template_cache) rather than falling through to tiers
    2-4 again — even though the SAME dictionary is available both times
    (exactly as it always is in real use: graph/nodes.py::map_columns
    loads it fresh on every call), tier 1 is checked FIRST and short-
    circuits, which the distinct `template_cache` status (as opposed to
    `exact`) is what actually proves."""
    templates_file = tmp_path / "templates.yaml"
    fingerprint = "shared-template-abc"
    headers = [_header(["OPENING", "QTY."]), _header(["OPENING", "VALUE"])]
    ctx = TableContext(fingerprint=fingerprint)

    # First pass: no cache yet, resolves via tier 2 — then cache the result
    # exactly the way graph/nodes.py::_cache_resolved_template does (same
    # leaf_fingerprint_key function on both the write and later read side).
    first_resolver = DictionaryResolver(_FIELD_ENTRIES, {"fingerprints": {}})
    first_decisions = [first_resolver.resolve(h, ctx) for h in headers]
    assert [d.status for d in first_decisions] == [MappingStatus.exact, MappingStatus.exact]

    leaf_mapping = {
        leaf_fingerprint_key(h, _FIELD_ENTRIES): d.canonical_field for h, d in zip(headers, first_decisions)
    }
    save_fingerprint(fingerprint, leaf_mapping, templates_file)

    # Second pass: same dictionary, but now the cache is populated — tier 1
    # should hit first this time.
    templates_cfg = yaml.safe_load(templates_file.read_text(encoding="utf-8"))
    second_resolver = DictionaryResolver(_FIELD_ENTRIES, templates_cfg)
    second_decisions = [second_resolver.resolve(h, ctx) for h in headers]

    assert [d.status for d in second_decisions] == [MappingStatus.template_cache, MappingStatus.template_cache]
    assert second_decisions[0].canonical_field == "opening_quantity"
    assert second_decisions[1].canonical_field == "opening_value"


def test_ocr_noise_on_a_confidently_resolved_leaf_still_hits_the_cache(tmp_path):
    """The property doc5.jpg/doc6.jpg's real headers demonstrate
    (IMPLEMENTATION_PLAN.md P13 build notes): a leaf whose text differs
    slightly from the one that originally populated the cache (different
    OCR noise on the SAME real header) still hits tier 1, as long as both
    spellings confidently fuzzy-match the same canonical field."""
    templates_file = tmp_path / "templates.yaml"
    fingerprint = "same-template-noisy-ocr"
    ctx = TableContext(fingerprint=fingerprint)
    resolver = DictionaryResolver(_FIELD_ENTRIES, {"fingerprints": {}})

    clean_header = _header(["OPENING", "VALUE"])
    clean_decision = resolver.resolve(clean_header, ctx)
    assert clean_decision.status == MappingStatus.exact

    leaf_mapping = {leaf_fingerprint_key(clean_header, _FIELD_ENTRIES): clean_decision.canonical_field}
    save_fingerprint(fingerprint, leaf_mapping, templates_file)

    templates_cfg = yaml.safe_load(templates_file.read_text(encoding="utf-8"))
    noisy_resolver = DictionaryResolver(_FIELD_ENTRIES, templates_cfg)
    noisy_decision = noisy_resolver.resolve(_header(["OPENING", "VALDE"]), ctx)  # real doc5.jpg OCR spelling

    assert noisy_decision.status == MappingStatus.template_cache
    assert noisy_decision.canonical_field == "opening_value"
