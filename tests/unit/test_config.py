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

    # DUMP QTY must NOT be mapped yet (open decision D2) — asserting its absence
    # guards against someone "resolving" the ambiguity by silently guessing.
    all_aliases = set()
    for entry in mappings.values():
        all_aliases.update(a.lower() for a in entry.get("aliases", []))
    assert "dump qty" not in all_aliases
    assert "dump" not in all_aliases


def test_distributors_cover_all_six_observed_documents():
    distributors = load_distributors()
    all_docs = {d for entry in distributors["distributors"] for d in entry["source_documents"]}
    assert all_docs == {f"doc{i}.jpg" for i in range(1, 7)}


def test_validation_rules_cover_both_confirmed_families():
    rules = load_validation_rules()
    assert "nabin" in rules["families"]
    assert "marg" in rules["families"]
    assert rules["rate_coherence"]["tolerance_pct"] == 0.5


def test_templates_cache_starts_empty():
    templates = load_templates()
    assert templates["fingerprints"] == {}
