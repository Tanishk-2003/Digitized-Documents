"""Template-fingerprint cache writer (P13) — the missing half of the
design detect/fingerprint.py::lookup_fingerprint's own docstring already
described: "writing a NEW fingerprint into the cache is [a later phase's]
job... not here, before mapping has even run." That job was never actually
implemented through P5-P12 (confirmed: config/templates.yaml stayed
`fingerprints: {}` no matter how many documents ran through the pipeline) —
this module is that write path.

Same YAML read-modify-write shape as mapping/update.py::add_column_alias
(including its non-atomic caveat — a stale-read race between two
concurrent writers is a real but low-severity risk at this project's scale,
identical trade-off already accepted there).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from pharma_di.config import clear_config_cache


def save_fingerprint(fingerprint: str, leaf_mapping: dict[str, str], templates_file: Path) -> None:
    """Writes `{fingerprint: leaf_mapping}` into `templates_file`'s
    top-level `fingerprints` map, overwriting any prior entry for the same
    fingerprint (a re-resolved document should replace a stale cached
    mapping, not accumulate beside it).

    `templates_file` is required, not defaulted-and-auto-resolved — P11's
    own finding (the test suite silently corrupting the real
    config/column_mappings.yaml through a similar auto-resolved default)
    is exactly the mistake this signature is designed not to repeat.
    Callers resolve the path themselves (graph/nodes.py::map_columns
    already has a loaded Settings to do that with) and are explicit about
    where they're writing, including in tests.

    Eligibility (should this mapping be cached at all?) is the caller's
    job, not this function's — see graph/nodes.py::map_columns's own
    gate (every column resolved with real confidence, never unresolved or
    merely fuzzy_low_confidence) before this is ever called.
    """
    if templates_file.exists():
        with templates_file.open("r", encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
    else:
        data = {}

    data.setdefault("fingerprints", {})[fingerprint] = leaf_mapping

    templates_file.parent.mkdir(parents=True, exist_ok=True)
    with templates_file.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)
    clear_config_cache()
