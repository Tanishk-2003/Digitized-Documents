import { useState, useEffect } from "react";
import { getDocument, approveDocument, correctDocument } from "../api";
import ConfBar from "../components/ConfBar";
import Icon from "../components/Icon";
import { useToast } from "../components/Toast";
import { normalizeReason, ruleLabel } from "../statementLanguage";

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
  const normalized = sourceFile.replace(/\\/g, "/");
  const idx = normalized.toLowerCase().indexOf("/data/");
  if (idx !== -1) {
    return `${BASE}/api/static${normalized.slice(idx + 5)}`;
  }
  const fname = normalized.split("/").pop();
  return `${BASE}/api/static/uploads/${fname}`;
}

function SourceDocumentPanel({ doc }) {
  const imgSrc = imageUrl(doc.source_file);
  return (
    <div className="card" style={{ position: "sticky", top: 20, alignSelf: "flex-start" }}>
      <div className="section-title">Original Statement</div>
      {imgSrc ? (
        <img
          src={imgSrc}
          alt="Source document"
          className="doc-image"
          onError={(e) => {
            e.target.style.display = "none";
            e.target.nextSibling.style.display = "flex";
          }}
        />
      ) : null}
      <div className="doc-image-empty flex-col items-center" style={{ display: imgSrc ? "none" : "flex" }}>
        <Icon name="image" size={28} style={{ marginBottom: 8 }} />
        Image not available
      </div>
      <div className="mt-2 text-sm text-muted">
        <div>File: <span className="font-mono">{doc.source_file?.split(/[\\/]/).pop() ?? "—"}</span></div>
      </div>
    </div>
  );
}

/**
 * IssuePanel — one flagged row shown as a single focused "issue" (brief §7/§10):
 * every field of the row, a plain-language reason for why it's flagged, and
 * Correct/Accept actions. Not decomposed to one issue per field — R1/R2/R3/
 * R5/R7 are row- or table-level checks with no single implicated field, so
 * "one issue = one flagged row" is the honest granularity the real
 * validation data supports (R6_confidence_gate, the one genuinely per-field
 * rule, still highlights its specific low-confidence fields within the row).
 */
function IssuePanel({ row, issueNumber, totalIssues, onAccept, onSaveCorrection }) {
  const [correcting, setCorrecting] = useState(false);
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
    onSaveCorrection(corrections);
    setCorrecting(false);
    setEdits({});
  };

  const reasons = (row.review_reasons ?? []).map(normalizeReason);
  const visibleFields = TRANSACTION_FIELDS.filter((k) => row[k] != null || NUMERIC_FIELDS.has(k));

  return (
    <div className="card issue-panel">
      <div className="flex items-center justify-between mb-2">
        <div className="section-title" style={{ marginBottom: 0 }}>
          Issue {issueNumber} of {totalIssues}
        </div>
        <span className="badge badge-warning">Needs your attention</span>
      </div>

      <div className="issue-panel-title">{row.product_name_raw ?? "This row"}</div>
      {row.hsn_code && <span className="badge badge-muted mt-1">HSN {row.hsn_code}</span>}

      {reasons.length > 0 && (
        <div className="alert alert-info mt-2" style={{ marginBottom: 0 }}>
          <Icon name="alertTriangle" size={15} />
          <div>
            {reasons.map((r, i) => (
              <div key={i}>
                {ruleLabel(r.rule_id)}
                {i === 0 && (
                  <details style={{ display: "inline" }}>
                    <summary style={{ display: "inline", cursor: "pointer", marginLeft: 6, fontSize: 11, color: "var(--muted)" }}>
                      technical detail
                    </summary>
                    <span className="text-sm text-muted"> — {r.message}</span>
                  </details>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {correcting ? (
        <div style={{ marginTop: 14 }}>
          {visibleFields.map((key) => {
            const orig = row[key];
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
            <button className="btn btn-success btn-sm" onClick={save}><Icon name="check" size={13} />Save &amp; Next Issue</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setCorrecting(false)}>Cancel</button>
          </div>
        </div>
      ) : (
        <>
          <div className="row-card-field-grid mt-3">
            {visibleFields.map((key) => {
              const val = row[key];
              if (val == null) return null;
              const conf =
                typeof row.extraction_confidence === "object" && row.extraction_confidence !== null
                  ? row.extraction_confidence[key]
                  : null;
              return (
                <div key={key} className="row-card-field">
                  <span className="row-card-field-label">{fieldLabel(key)}</span>
                  <span className="row-card-field-val">{String(val)}</span>
                  {conf != null ? <ConfBar score={conf} variant="business" /> : <span style={{ fontSize: 11, color: "var(--muted)" }}>—</span>}
                </div>
              );
            })}
          </div>
          <div className="flex gap-2 mt-4">
            <button className="btn btn-ghost" onClick={() => setCorrecting(true)}><Icon name="edit" size={13} />Correct</button>
            <button className="btn btn-primary" onClick={onAccept}><Icon name="check" size={13} />Accept</button>
          </div>
        </>
      )}
    </div>
  );
}

/**
 * DocumentReviewPage
 * ==================
 * UI-UX-Implementation.md Phase A.4: an issue-by-issue review workflow
 * (Review issue -> Correct/Accept -> auto-advance -> Approve Statement)
 * replacing the old "open every row's edit form individually" pattern, plus
 * gated approval (can't approve while issues remain) and, when opened from
 * the Review Required queue, Previous/Next Statement navigation so a
 * reviewer working through many statements never has to go back to the
 * list between them.
 *
 * All of this runs over the *existing* /api/review/{id}/correct and
 * /api/review/{id}/approve endpoints — Accept/Correct-and-save only update
 * local state as the reviewer moves through the queue; the network calls
 * happen once, when they click "Approve Statement" (correct_document first
 * if anything was corrected, then approve_document to flip any remaining
 * accepted-as-is rows) — see UI-UX-Implementation.md's grounding note 4.
 */
export default function DocumentReviewPage({ documentId, queueIds, onBack, onNavigate }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [resolvedIndices, setResolvedIndices] = useState(new Set());
  const [pendingCorrections, setPendingCorrections] = useState([]);
  const [pendingMappings, setPendingMappings] = useState([]);
  const [approving, setApproving] = useState(false);
  const showToast = useToast();

  const load = () => {
    setLoading(true);
    setResolvedIndices(new Set());
    setPendingCorrections([]);
    setPendingMappings([]);
    getDocument(documentId)
      .then(setDetail)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, [documentId]);

  const handleAccept = (rowIdx) => {
    setResolvedIndices((prev) => new Set(prev).add(rowIdx));
  };

  const handleSaveCorrection = (rowIdx, corrections) => {
    setPendingCorrections((prev) => [...prev, ...corrections]);
    setResolvedIndices((prev) => new Set(prev).add(rowIdx));
  };

  const handleApproveStatement = async () => {
    setApproving(true);
    setError(null);
    try {
      if (pendingCorrections.length > 0 || pendingMappings.length > 0) {
        await correctDocument(documentId, { columnMappings: pendingMappings, rowCorrections: pendingCorrections });
      }
      await approveDocument(documentId, "Approved via UI");
      showToast("Statement approved");
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setApproving(false);
    }
  };

  if (loading) return <div className="flex items-center gap-2 mt-4"><span className="spinner" /> Loading statement…</div>;
  if (error && !detail) return <div className="alert alert-error"><Icon name="alertTriangle" size={16} />{error}</div>;
  if (!detail) return null;

  const { document: doc, canonical_rows: allRows } = detail;
  const rows = allRows.map((r, idx) => ({ ...r, _rowIdx: idx }));
  const flaggedRows = rows.filter((r) => r.review_status === "needs_review");
  const currentIssue = flaggedRows.find((r) => !resolvedIndices.has(r._rowIdx));
  const allResolved = flaggedRows.length === 0 || !currentIssue;
  const resolvedCount = flaggedRows.filter((r) => resolvedIndices.has(r._rowIdx)).length;

  const queuePos = queueIds ? queueIds.indexOf(documentId) : -1;
  const hasPrev = queueIds && queuePos > 0;
  const hasNext = queueIds && queuePos >= 0 && queuePos < queueIds.length - 1;

  return (
    <div>
      {queueIds && queuePos >= 0 && (
        <div className="statement-nav mb-3">
          <button className="btn btn-ghost btn-sm" disabled={!hasPrev} onClick={() => onNavigate(queueIds[queuePos - 1])}>
            <Icon name="arrowLeft" size={13} />Previous Statement
          </button>
          <span className="text-sm text-muted">{queuePos + 1} of {queueIds.length}</span>
          <button className="btn btn-ghost btn-sm" disabled={!hasNext} onClick={() => onNavigate(queueIds[queuePos + 1])}>
            Next Statement<Icon name="arrowRight" size={13} />
          </button>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center gap-2 mb-4">
        <button className="btn btn-ghost btn-sm" onClick={onBack}><Icon name="arrowLeft" size={14} />Back</button>
        <div style={{ flex: 1 }}>
          <h2 style={{ fontSize: 17, fontWeight: 700 }}>
            {doc.distributor_name ?? "Unknown Distributor"}
            {doc.company_name && <span style={{ fontWeight: 400, color: "var(--muted)" }}> / {doc.company_name}</span>}
          </h2>
          <div className="text-sm text-muted">
            {doc.statement_from && <span>{doc.statement_from} → {doc.statement_to} · </span>}
            {doc.row_count} products
          </div>
        </div>
        {allResolved ? (
          <button className="btn btn-success" onClick={handleApproveStatement} disabled={approving}>
            {approving ? <span className="spinner" /> : <Icon name="check" size={14} />}
            {approving ? "Approving…" : "Approve Statement"}
          </button>
        ) : (
          <span className="badge badge-warning">{flaggedRows.length - resolvedCount} issue{flaggedRows.length - resolvedCount === 1 ? "" : "s"} remaining</span>
        )}
      </div>

      {error && <div className="alert alert-error"><Icon name="alertTriangle" size={16} />{error}</div>}

      {allResolved && flaggedRows.length > 0 && (
        <div className="alert alert-success">
          <Icon name="checkCircle" size={16} />
          All {flaggedRows.length} issue{flaggedRows.length === 1 ? "" : "s"} resolved — {doc.row_count} of {doc.row_count} products verified.
        </div>
      )}

      <div className="review-split">
        <SourceDocumentPanel doc={doc} />

        <div>
          {!allResolved && currentIssue ? (
            <IssuePanel
              row={currentIssue}
              issueNumber={resolvedCount + 1}
              totalIssues={flaggedRows.length}
              onAccept={() => handleAccept(currentIssue._rowIdx)}
              onSaveCorrection={(corrections) => handleSaveCorrection(currentIssue._rowIdx, corrections)}
            />
          ) : (
            <div className="card">
              <div className="section-title">All Products ({rows.length})</div>
              {rows.map((row) => {
                // row.review_status still reflects server state as of the
                // last load() — it stays "needs_review" until the reviewer
                // actually clicks Approve Statement, so a row's LOCAL
                // resolution (accepted vs. corrected vs. never flagged) has
                // to be derived from resolvedIndices/pendingCorrections
                // here, not read off review_status directly.
                const wasCorrected = pendingCorrections.some((c) => c.transaction_id === row._transaction_id);
                const label = row.review_status === "auto_accepted" ? "Verified" : wasCorrected ? "Corrected" : "Accepted";
                return (
                  <div key={row._rowIdx} className="flex items-center justify-between" style={{ padding: "8px 0", borderBottom: "1px solid var(--bg)" }}>
                    <span className="text-sm">{row.product_name_raw ?? `Row ${row._rowIdx + 1}`}</span>
                    <span className="badge badge-success">
                      <Icon name="check" size={11} />
                      {label}
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          {rows.some((r) => r.unmapped_columns && Object.keys(r.unmapped_columns).length > 0) && (
            <div className="mt-4">
              <UnmappedColumnPanel rows={rows} onAddMapping={(m) => setPendingMappings((prev) => [...prev, m])} />
            </div>
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
    <div className="card" style={{ borderColor: "var(--warning-border)" }}>
      <div className="section-title flex items-center gap-2" style={{ color: "var(--warning)" }}>
        <Icon name="alertTriangle" size={13} />Unresolved Columns — map them to canonical fields
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
            {added.has(header) ? <><Icon name="check" size={12} />Queued</> : "Promote"}
          </button>
        </div>
      ))}
      <p className="text-sm text-muted mt-2">
        Queued aliases are submitted together when you approve the statement.
      </p>
    </div>
  );
}
