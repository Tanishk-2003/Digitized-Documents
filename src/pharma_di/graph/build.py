"""Builds and compiles the pipeline StateGraph (CLAUDE.md: LangGraph
orchestration, "mirroring the existing Geneilytics orchestrator pattern").

Node order mirrors IMPLEMENTATION_PLAN.md section 4.9:

    ingest -> preprocess -> quality_gate -> ocr -> segment_regions
           -> reconstruct_headers -> assemble_table -> detect_document
           -> map_columns -> assemble_canonical -> resolve_products
           -> validate -> {persist | review_queue} -> export -> END
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from pharma_di.graph import nodes
from pharma_di.graph.state import PipelineState


def build_graph() -> StateGraph:
    graph = StateGraph(PipelineState)

    graph.add_node("ingest", nodes.ingest)
    graph.add_node("preprocess", nodes.preprocess)
    graph.add_node("quality_gate", nodes.quality_gate)
    graph.add_node("ocr", nodes.ocr)
    graph.add_node("segment_regions", nodes.segment_regions)
    graph.add_node("reconstruct_headers", nodes.reconstruct_headers)
    graph.add_node("assemble_table", nodes.assemble_table)
    graph.add_node("detect_document", nodes.detect_document)
    graph.add_node("map_columns", nodes.map_columns)
    graph.add_node("assemble_canonical", nodes.assemble_canonical)
    graph.add_node("resolve_products", nodes.resolve_products)
    graph.add_node("validate", nodes.validate)
    graph.add_node("persist", nodes.persist)
    graph.add_node("review_queue", nodes.review_queue)
    graph.add_node("export", nodes.export)

    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "preprocess")
    graph.add_edge("preprocess", "quality_gate")

    graph.add_conditional_edges(
        "quality_gate",
        nodes.route_after_quality_gate,
        {"ocr": "ocr", "review_queue": "review_queue"},
    )

    graph.add_edge("ocr", "segment_regions")
    graph.add_edge("segment_regions", "reconstruct_headers")
    graph.add_edge("reconstruct_headers", "assemble_table")
    graph.add_edge("assemble_table", "detect_document")
    graph.add_edge("detect_document", "map_columns")
    graph.add_edge("map_columns", "assemble_canonical")
    graph.add_edge("assemble_canonical", "resolve_products")
    graph.add_edge("resolve_products", "validate")

    graph.add_conditional_edges(
        "validate",
        nodes.route_after_validate,
        {"persist": "persist", "review_queue": "review_queue"},
    )

    graph.add_edge("persist", "export")
    graph.add_edge("review_queue", "export")
    graph.add_edge("export", END)

    return graph


def compiled_graph():
    return build_graph().compile()
