import { useState, useEffect } from "react";
import { getDocument, approveDocument, correctDocument } from "../api";
import ConfBar from "../components/ConfBar";
import StatusBadge from "../components/StatusBadge";

const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

/**
 * TRANSACTION_FIELDS — ordered list of canonical Level-3 fields shown in the review table.
 * Matches CanonicalRow fields from schemas/canonical.py.
 */
const TRANSACTION_FIELDS = [
  "product_name_raw",
  "hsn_code",
  "pack",
  "rate",
  "opening_quantity",
  "opening_value",
  "received_quantity",
  "received_value",
  "free_received_quantity",
  "sales_quantity",
  "sales_value",
  "free_sales_quantity",
  "sales_return_quantity",
  "purchase_return_quantity",
  "expired_quantity",
  "closing_quantity",
  "closing_value",
  "months_to_expiry",
  "stock_status",
];

const NUMERIC_FIELDS = new Set([
  "rate","opening_quantity","opening_value","received_quantity","received_value",
  "free_received_quantity","sales_quantity","sales_value","free_sales_quantity",
  "sales_return_quantity","purchase_return_quantity","expired_quantity",
  "closing_quantity","closing_value","months_to_expiry",
]);

/** Format field name into human-readable label */
function fieldLabel(key) {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Derive source_file path to serve the original document image.
 * source_file is an absolute path on the server, e.g. C:\...\data\input\doc1.jpg
 * The FastAPI backend mounts data/ as /api/static, so we strip everything up
 * to and including 'data/' from the path and prepend /api/static/.
 */
function imageUrl(sourceFile) {
  if (!sourceFile) return null;
  // Normalize backslashes -> forward slashes
  const normalized = sourceFile.replace(/\\/g, "/");
  // Find the 'data/' segment and take everything after it
  const idx = normalized.toLowerCase().indexOf("/data/");
  if (idx !== -1) {
    return `${BASE}/api/static${normalized.slice(idx + 5)}`; // "/data" is 5 chars
  }
  // Fallback: just use the basename under uploads/
  const fname = normalized.split("/").pop();
  return `${BASE}/api/static/uploads/${fname}`;
}

/** Single row correction panel — shown when user clicks "Correct" on a row. */
function RowCorrectPanel({ row, onSave, onCancel }) {
  const [edits, setEdits] = useState({});

  const set = (k, v) => setEdits((prev) => ({ ...prev, [k]: v }));

  const save = () => {
    const corrections = Object.entries(edits)
      .filter(([k, v]) => v !== String(row[k] ?? ""))
      .map(([field_name, corrected_value]) => ({
        transaction_id: row._transaction_id,
        field_name,
        original_value: String(row[field_name] ?? ""),
        corrected_value,
      }));
    onSave(corrections);
  };

  return (
    <div style={{ padding: "12px 0" }}>
      <div className="section-title">Correct Fields — {row.product_name_raw ?? "Row"}</div>
      {TRANSACTION_FIELDS.map((key) => {
        const orig = row[key];
        if (orig == null && !edits[key]) return null; // skip truly absent fields
        return (
          <div key={key} className="field-row">
            <span className="field-label text-sm">{fieldLabel(key)}</span>
            <span className="field-val">{String(orig ?? "—")}</span>
            <div className="field-input">
              <input
                type="text"
                placeholder={String(orig ?? "")}
                value={edits[key] ?? ""}
                onChange={(e) => set(key, e.target.value)}
              />
            </div>
          </div>
        );
      })}
      <div className="flex gap-2 mt-3">
        <button className="btn btn-success btn-sm" onClick={save}>Save Corrections</button>
        <button className="btn btn-ghost btn-sm" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

/**
 * DocumentReviewPage
 * ==================
 * Shows the original document image (left) beside a table of extracted canonical rows (right).
 * Each row has a per-field confidence bar, approve button, and correct form.
 * Corrections are sent to POST /api/review/{doc_id}/correct and promote aliases to
 * config/column_mappings.yaml via the backend's add_column_alias() feedback loop.
 */
export default function DocumentReviewPage({ documentId, onBack }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);
  const [correctingRowIdx, setCorrectingRowIdx] = useState(null);
  const [pendingCorrections, setPendingCorrections] = useState([]); // accumulated row corrections
  const [pendingMappings, setPendingMappings] = useState([]); // column alias corrections
  const [approving, setApproving] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const load = () => {
    setLoading(true);
    getDocument(documentId)
      .then(setDetail)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, [documentId]);

  const handleApproveAll = async () => {
    setApproving(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const res = await approveDocument(documentId, "Approved via UI");
      setSuccessMsg(`✅ ${res.updated_rows} rows marked as approved.`);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setApproving(false);
    }
  };

  const handleRowCorrections = (corrections) => {
    setPendingCorrections((prev) => [...prev, ...corrections]);
    setCorrectingRowIdx(null);
  };

  const handleSubmitAll = async () => {
    setSubmitting(true);
    setError(null);
    setSuccessMsg(null);
    try {
      const res = await correctDocument(documentId, {
        columnMappings: pendingMappings,
        rowCorrections: pendingCorrections,
      });
      const parts = [];
      if (res.updated_rows) parts.push(`${res.updated_rows} row corrections saved`);
      if (res.promoted_mappings?.length) {
        parts.push(`${res.promoted_mappings.length} column alias(es) promoted to column_mappings.yaml`);
      }
      setSuccessMsg(`✅ ${parts.join(" · ")}`);
      setPendingCorrections([]);
      setPendingMappings([]);
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <div className="flex items-center gap-2 mt-4"><span className="spinner" /> Loading document…</div>;
  if (error && !detail) return <div className="alert alert-error">{error}</div>;
  if (!detail) return null;

  const { document: doc, canonical_rows: rows } = detail;
  const imgSrc = imageUrl(doc.source_file);
  const flaggedRows = rows.filter((r) => r.review_status === "needs_review");
  const hasPending = pendingCorrections.length > 0 || pendingMappings.length > 0;

  return (
    <div>
      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <button className="btn btn-ghost btn-sm" onClick={onBack}>← Back</button>
        <div style={{ flex: 1 }}>
          <h2 style={{ fontSize: 17, fontWeight: 700 }}>
            {doc.distributor_name ?? "Unknown Distributor"}
            {doc.company_name && <span style={{ fontWeight: 400, color: "var(--muted)" }}> / {doc.company_name}</span>}
          </h2>
          <div className="text-sm text-muted">
            {doc.statement_from && <span>📅 {doc.statement_from} → {doc.statement_to} · </span>}
            {doc.row_count} rows · {doc.needs_review_count} flagged
          </div>
        </div>
        <div className="flex gap-2">
          {hasPending && (
            <button
              className="btn btn-primary"
              onClick={handleSubmitAll}
              disabled={submitting}
            >
              {submitting ? "Saving…" : `Submit Corrections (${pendingCorrections.length})`}
            </button>
          )}
          <button
            className="btn btn-success"
            onClick={handleApproveAll}
            disabled={approving}
          >
            {approving ? "Approving…" : "Approve All ✓"}
          </button>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {successMsg && <div className="alert alert-success">{successMsg}</div>}

      {pendingCorrections.length > 0 && (
        <div className="alert" style={{ background: "#eff6ff", border: "1px solid #bfdbfe", color: "#1e40af" }}>
          🖊 {pendingCorrections.length} unsaved correction(s). Click "Submit Corrections" to persist and promote column aliases.
        </div>
      )}

      <div className="review-split">
        {/* LEFT: Source document image */}
        <div className="card" style={{ position: "sticky", top: 72, alignSelf: "flex-start" }}>
          <div className="section-title">Source Document</div>
          {imgSrc ? (
            <img
              src={imgSrc}
              alt="Source document"
              className="doc-image"
              onError={(e) => {
                e.target.style.display = "none";
                e.target.nextSibling.style.display = "block";
              }}
            />
          ) : null}
          <div
            style={{
              display: imgSrc ? "none" : "block",
              textAlign: "center",
              padding: 32,
              color: "var(--muted)",
              background: "#f9fafb",
              borderRadius: "var(--radius)",
            }}
          >
            📄 Image not available
            {doc.source_file && (
              <div className="text-sm mt-1 font-mono">{doc.source_file}</div>
            )}
          </div>
          <div className="mt-2 text-sm text-muted">
            <div>File: <span className="font-mono">{doc.source_file?.split(/[\\/]/).pop() ?? "—"}</span></div>
            <div>Type: {doc.document_type ?? "—"}</div>
          </div>
        </div>

        {/* RIGHT: Extracted rows with confidence bars */}
        <div>
          <div className="card" style={{ marginBottom: 16 }}>
            <div className="section-title">
              Extracted Rows ({rows.length}) — {flaggedRows.length} flagged
            </div>

            {rows.length === 0 && (
              <div className="empty">No canonical rows for this document.</div>
            )}

            {rows.map((row, idx) => {
              const isFlagged = row.review_status === "needs_review";
              const isCorrectingThis = correctingRowIdx === idx;

              return (
                <div
                  key={idx}
                  style={{
                    border: "1px solid",
                    borderColor: isFlagged ? "#fbbf24" : "var(--border)",
                    borderRadius: "var(--radius)",
                    padding: 14,
                    marginBottom: 10,
                    background: isFlagged ? "#fffbeb" : "var(--surface)",
                  }}
                >
                  {/* Row header */}
                  <div className="flex items-center justify-between">
                    <div>
                      <span style={{ fontWeight: 700 }}>
                        {row.product_name_raw ?? `Row ${idx + 1}`}
                      </span>
                      {row.hsn_code && (
                        <span className="badge badge-muted" style={{ marginLeft: 8 }}>
                          HSN {row.hsn_code}
                        </span>
                      )}
                      {row.pack && (
                        <span className="text-sm text-muted" style={{ marginLeft: 6 }}>
                          {row.pack}
                        </span>
                      )}
                    </div>
                    <div className="flex gap-2 items-center">
                      <StatusBadge status={row.review_status} />
                      {!isCorrectingThis && (
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => setCorrectingRowIdx(idx)}
                        >
                          Correct
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Review reasons */}
                  {isFlagged && row.review_reasons?.length > 0 && (
                    <div className="reasons mt-1 text-sm">
                      ⚠ {Array.isArray(row.review_reasons) ? row.review_reasons.join(" · ") : row.review_reasons}
                    </div>
                  )}

                  {/* Correction form (expanded) */}
                  {isCorrectingThis && (
                    <RowCorrectPanel
                      row={row}
                      onSave={handleRowCorrections}
                      onCancel={() => setCorrectingRowIdx(null)}
                    />
                  )}

                  {/* Confidence bars for key numeric fields */}
                  {!isCorrectingThis && (
                    <div style={{ marginTop: 10, display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 16px" }}>
                      {TRANSACTION_FIELDS.filter((k) => row[k] != null || NUMERIC_FIELDS.has(k)).map((key) => {
                        const val = row[key];
                        if (val == null) return null;
                        // Confidence keys follow pattern: field_name + "_confidence" but the backend
                        // stores per-field conf in extraction_confidence dict (JSON column)
                        const conf =
                          typeof row.extraction_confidence === "object" && row.extraction_confidence !== null
                            ? row.extraction_confidence[key]
                            : null;
                        return (
                          <div key={key} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <span style={{ width: 130, fontSize: 11, color: "var(--muted)", flexShrink: 0 }}>
                              {fieldLabel(key)}
                            </span>
                            <span style={{ width: 80, fontSize: 12, fontFamily: "monospace", flexShrink: 0 }}>
                              {String(val)}
                            </span>
                            {conf != null ? (
                              <ConfBar score={conf} />
                            ) : (
                              <span style={{ fontSize: 11, color: "var(--muted)" }}>—</span>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Unresolved columns section */}
          {rows.some((r) => r.unmapped_columns && Object.keys(r.unmapped_columns).length > 0) && (
            <UnmappedColumnPanel rows={rows} onAddMapping={(m) => setPendingMappings((prev) => [...prev, m])} />
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * UnmappedColumnPanel — surface any columns that the pipeline could not resolve.
 * The human can pick a canonical field to map them to, which is then promoted
 * to column_mappings.yaml via the correct endpoint's column_mappings payload.
 */
const CANONICAL_FIELDS = [
  "product_name_raw", "hsn_code", "pack", "rate",
  "opening_quantity", "opening_value",
  "received_quantity", "received_value", "free_received_quantity",
  "sales_quantity", "sales_value", "free_sales_quantity",
  "sales_return_quantity", "purchase_return_quantity", "expired_quantity",
  "closing_quantity", "closing_value",
  "months_to_expiry", "stock_status",
  "derived_check_only",
];

function UnmappedColumnPanel({ rows, onAddMapping }) {
  // Collect unique unresolved source headers across all rows
  const headers = new Set();
  rows.forEach((r) => {
    if (r.unmapped_columns && typeof r.unmapped_columns === "object") {
      Object.keys(r.unmapped_columns).forEach((h) => headers.add(h));
    }
  });

  const [selections, setSelections] = useState({});
  const [added, setAdded] = useState(new Set());

  const promote = (header) => {
    const field = selections[header];
    if (!field) return;
    onAddMapping({ source_header: header, canonical_field: field });
    setAdded((prev) => new Set([...prev, header]));
  };

  if (headers.size === 0) return null;

  return (
    <div className="card" style={{ borderColor: "var(--warning)" }}>
      <div className="section-title" style={{ color: "var(--warning)" }}>
        ⚠ Unresolved Columns — map them to canonical fields
      </div>
      <p className="text-sm text-muted mb-4">
        These column headers were not recognized by the mapping dictionary. Select the correct canonical
        field and click Promote — the alias will be written to <code>config/column_mappings.yaml</code> and
        resolved deterministically on the next run.
      </p>
      {[...headers].map((header) => (
        <div key={header} className="field-row">
          <code className="field-label" style={{ fontSize: 12 }}>{header}</code>
          <select
            value={selections[header] ?? ""}
            onChange={(e) => setSelections((p) => ({ ...p, [header]: e.target.value }))}
            style={{ flex: 1 }}
          >
            <option value="">— select canonical field —</option>
            {CANONICAL_FIELDS.map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
          <button
            className="btn btn-primary btn-sm"
            disabled={!selections[header] || added.has(header)}
            onClick={() => promote(header)}
            style={{ marginLeft: 8 }}
          >
            {added.has(header) ? "✓ Queued" : "Promote"}
          </button>
        </div>
      ))}
      <p className="text-sm text-muted mt-2">
        Queued aliases are submitted together with row corrections when you click "Submit Corrections".
      </p>
    </div>
  );
}
