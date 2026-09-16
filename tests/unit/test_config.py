"""P0: the config loader is a real deliverable — every stage reads mapping
dictionaries, distributor masters, and validation formulas through it rather
than hardcoding them, per CLAUDE.md's working conventions."""
from __future__ import annotations

from pharma_di.config import (
    load_column_mappings,
    load_distributors,
    load_settings,
    load_templates,
    load_validation_rules,
)


def test_settings_load_and_validate():
    settings = load_settings()
    assert settings.semantic_mapping.fallback == "none", (
        "MVP must ship with no LLM fallback wired up (IMPLEMENTATION_PLAN.md section 0)"
    )
    assert settings.ocr.engine == "paddleocr"
    assert settings.resolve_path("data_input").name == "input"


def test_column_mappings_cover_the_core_canonical_fields():
    mappings = load_column_mappings()
    # Spot-check fields required by CLAUDE.md's canonical schema table.
    for field in [
        "opening_quantity",
        "received_quantity",
        "sales_quantity",
        "sales_return_quantity",
        "closing_quantity",
        "hsn_code",
        "rate",
    ]:
        assert field in mappings, f"canonical field {field!r} missing from column_mappings.yaml"

    # The many-to-one return split (New Tripura: Market Return / Return Outward /
    # Short Quantity) must be configured to sum, not silently pick one.
    assert mappings["sales_return_quantity"].get("combine") == "sum"

    # D2 ("DUMP QTY semantics... Left unresolved until answered") is
    # deliberately resolved as of P14 — NOT by guessing which candidate
    # interpretation (expired stock? breakage? near-expiry return?) is
    # correct, but by giving it its own verbatim dump_quantity field,
    # distinct from expired_quantity. This guard now checks the opposite
    # of what it used to: that the resolution landed on its OWN field
    # rather than being silently folded into an existing one (which would
    # be exactly the kind of guess D2 always warned against).
    assert "dump_quantity" in mappings
    assert "dump qty" in {a.lower() for a in mappings["dump_quantity"].get("aliases", [])}
    for field, entry in mappings.items():
        if field in {"dump_quantity", "abbreviations"}:
            continue
        aliases = {a.lower() for a in entry.get("aliases", [])}
        assert "dump qty" not in aliases, f"'dump qty' must resolve only to dump_quantity, not {field!r}"


def test_distributors_cover_all_six_observed_documents():
    distributors = load_distributors()
    all_docs = {d for entry in distributors["distributors"] for d in entry["source_documents"]}
    assert all_docs == {f"doc{i}.jpg" for i in range(1, 7)}


def test_validation_rules_cover_both_confirmed_families():
    rules = load_validation_rules()
    assert "nabin" in rules["families"]
    assert "marg" in rules["families"]
    assert rules["rate_coherence"]["tolerance_pct"] == 0.5


def test_templates_cache_has_the_expected_shape():
    # P0-P12: this file's `fingerprints` map was ALWAYS empty, because
    # nothing ever wrote to it (detect/fingerprint.py::lookup_fingerprint
    # was read-only by design; the write path didn't exist until P13). This
    # test used to assert exactly that emptiness — no longer meaningful
    # now that P13 gives templates.yaml a real write path
    # (mapping/template_cache.py::save_fingerprint) and a real pipeline run
    # against doc6.jpg was deliberately left populated in it (see P13 build
    # notes) as genuine, working production state, not test pollution. The
    # actual lasting invariant is structural, not "currently empty" — a
    # config file whose shape every caller (mapping/resolver.py::
    # DictionaryResolver, mapping/template_cache.py::save_fingerprint) can
    # rely on regardless of how many real fingerprints have accumulated.
    templates = load_templates()
    assert isinstance(templates["fingerprints"], dict)
