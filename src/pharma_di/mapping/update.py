"""Configuration updater for human review feedback loop (IMPLEMENTATION_PLAN.md P9/P10).
Appends confirmed column aliases and mappings to config/column_mappings.yaml
and flushes the cached configuration so subsequent pipeline runs resolve
the new alias deterministically.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml

from pharma_di.config import clear_config_cache, load_settings


def add_column_alias(
    canonical_field: str,
    alias: str,
    mappings_file: Path | None = None,
) -> bool:
    """Adds a new alias to a canonical field in column_mappings.yaml if not already present."""
    if mappings_file is None:
        settings = load_settings()
        mappings_file = settings.resolve_path("column_mappings")

    if not mappings_file.exists():
        return False

    with mappings_file.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}

    alias_clean = alias.strip().lower()
    if not alias_clean:
        return False

    needs_write = False
    if canonical_field not in data:
        data[canonical_field] = {"aliases": [alias_clean]}
        needs_write = True
    else:
        field_dict = data[canonical_field]
        if "aliases" not in field_dict:
            field_dict["aliases"] = []
        aliases: list[str] = field_dict["aliases"]
        if alias_clean not in [a.lower() for a in aliases]:
            aliases.append(alias_clean)
            needs_write = True

    if needs_write:
        with mappings_file.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)
        clear_config_cache()

    return True
