#!/usr/bin/env python
"""CLI entry point for the pipeline scaffold (P0).

    python scripts/run_pipeline.py --input data/input/doc4.jpg --debug

Runs the full LangGraph node sequence (build_graph in src/pharma_di/graph)
against one source image. In P0 every node past `ingest` is a no-op, so the
point of this script is to prove the scaffold itself works: the state schema
validates at every node boundary, the graph traverses every node in order,
and the result is a real, schema-valid (if mostly-null) PipelineState —
written both to stdout and to data/interim/<document_id>/pipeline_result.json
for inspection.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pharma_di.graph.build import compiled_graph  # noqa: E402
from pharma_di.graph.state import PipelineState  # noqa: E402


def run_pipeline(input_path: Path, debug: bool = False) -> PipelineState:
    document_id = f"{input_path.stem}-{uuid.uuid4().hex[:8]}"
    initial_state = PipelineState(
        source_file=str(input_path),
        document_id=document_id,
        debug=debug,
    )

    graph = compiled_graph()
    result = graph.invoke(initial_state)

    # LangGraph returns a dict keyed by the state schema's fields; re-validate
    # into PipelineState so callers get the same typed object they put in.
    final_state = PipelineState.model_validate(result)
    return final_state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Path to a source document image")
    parser.add_argument("--debug", action="store_true", help="Verbose trace output")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = REPO_ROOT / input_path

    if not input_path.exists():
        print(f"ERROR: input file not found: {input_path}", file=sys.stderr)
        return 1

    final_state = run_pipeline(input_path, debug=args.debug)

    out_dir = REPO_ROOT / "data" / "interim" / final_state.document_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pipeline_result.json"
    out_path.write_text(final_state.model_dump_json(indent=2), encoding="utf-8")

    if args.debug:
        print(f"document_id: {final_state.document_id}")
        print(f"trace ({len(final_state.trace)} nodes): {' -> '.join(final_state.trace)}")
        print(f"errors: {final_state.errors}")
        print(f"image size: {final_state.image_width}x{final_state.image_height}")
        print(f"routed_to_review: {final_state.routed_to_review}  persisted: {final_state.persisted}")
        print(f"result written to: {out_path}")
    else:
        print(json.dumps({"document_id": final_state.document_id, "trace": final_state.trace, "output": str(out_path)}))

    return 0 if not final_state.errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
