import { useState, useEffect, useRef } from "react";
import { listDocuments, listJobs, exportDocumentExcel } from "../api";
import Icon from "../components/Icon";
import StatusPill from "../components/StatusPill";
import { deriveStatementStatus } from "../statementLanguage";
import { SkeletonTable } from "../components/Skeleton";
import { useToast } from "../components/Toast";

/**
 * StatementsPage — UI-UX-Implementation.md Phase A.1a: the main Statement
 * list (was DocumentsPage, framed as raw document storage). Every statement
 * ever processed, one row each, using the same status vocabulary
 * (statementLanguage.js) as the Review Required view (ReviewQueuePage.jsx)
 * so the two screens can never drift into describing the same underlying
 * data in different language — the actual problem the brief's "make
 * Documents the main Statement list" note (§21) was about. The two screens
 * stay visually distinct on purpose (a compact table here for scanning
 * every statement vs. StatementCard's richer per-item breakdown there,
 * where there are usually far fewer items) — a deliberate difference in
 * density for different use cases, not the inconsistency being fixed.
 */
export default function StatementsPage({ onReview }) {
  const [docs, setDocs] = useState([]);
  const [pendingJobs, setPendingJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [exportingId, setExportingId] = useState(null);
  const showToast = useToast();

  const loadDocs = () => {
    listDocuments()
      .then(setDocs)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(loadDocs, []);

  // UI-UX-Implementation.md Phase B.2: a statement mid-pipeline has no
  // Document row yet (persistence is the second-to-last node in the graph,
  // so by the time a row exists its job has already finished) — the only
  // way to show "your statement is still processing" here, rather than
  // sending the user to the separate Processing/Jobs page, is to surface
  // the still-in-flight jobs themselves alongside the real rows. Polls
  // while any are queued/processing, same interval JobsPage already uses.
  // When a job drops out of that set (finished, one way or another), the
  // real Statements list is re-fetched so the row that just appeared
  // doesn't wait for a manual page reload to show up.
  const prevPendingIds = useRef(new Set());
  useEffect(() => {
    const refresh = async () => {
      const all = await listJobs().catch(() => null);
      if (!all) return;
      const stillPending = all.filter((j) => j.status === "queued" || j.status === "processing");
      const newIds = new Set(stillPending.map((j) => j.job_id));
      const someJobFinished = [...prevPendingIds.current].some((id) => !newIds.has(id));
      prevPendingIds.current = newIds;
      setPendingJobs(stillPending);
      if (someJobFinished) loadDocs();
    };
    refresh();
    const id = setInterval(refresh, 4000);
    return () => clearInterval(id);
  }, []);

  const downloadExcel = async (docId) => {
    setExportingId(docId);
    try {
      const blob = await exportDocumentExcel(docId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${docId}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
      showToast(`Exported ${docId}.xlsx`);
    } catch (e) {
      showToast(`Export failed: ${e.message}`, { type: "error" });
    } finally {
      setExportingId(null);
    }
  };

  return (
    <div>
      <h2 className="page-title">Statements</h2>

      {error && <div className="alert alert-error"><Icon name="alertTriangle" size={16} />{error}</div>}

      {pendingJobs.length > 0 && (
        <div className="card mb-4">
          <div className="section-title">Currently Processing</div>
          {pendingJobs.map((j) => (
            <div key={j.job_id} className="flex items-center gap-2" style={{ padding: "6px 0" }}>
              <span className="spinner" />
              <span className="text-sm truncate" style={{ maxWidth: 260 }}>{j.source_file?.split(/[\\/]/).pop() ?? j.job_id}</span>
              <span className="text-sm text-muted">— {j.progress_stage ?? j.status}…</span>
            </div>
          ))}
        </div>
      )}

      {loading ? (
        <SkeletonTable rows={5} cols={7} />
      ) : docs.length === 0 ? (
        <div className="empty">
          <Icon name="documents" size={36} />
          <p>No statements yet. Submit one to get started.</p>
        </div>
      ) : (
        <div className="card">
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Distributor</th>
                  <th>Company</th>
                  <th>Type</th>
                  <th>Period</th>
                  <th>Products</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {docs.map((d) => {
                  const status = deriveStatementStatus(d);
                  const isException = status.key === "exception";
                  return (
                    <tr key={d.document_id} className={status.key === "review" ? "flagged" : ""}>
                      {isException ? (
                        <td colSpan={2}>
                          <span className="text-sm" style={{ color: "var(--danger)" }}>
                            Distributor could not be identified
                          </span>
                          <div className="text-sm text-muted font-mono">{d.source_file?.split(/[\\/]/).pop()}</div>
                        </td>
                      ) : (
                        <>
                          <td>{d.distributor_name ?? "—"}</td>
                          <td>{d.company_name ?? "—"}</td>
                        </>
                      )}
                      <td>
                        <span className={`badge ${d.document_type === "summary" ? "badge-info" : "badge-muted"}`}>
                          {d.document_type ?? "—"}
                        </span>
                      </td>
                      <td className="text-sm">
                        {d.statement_from ? `${d.statement_from} → ${d.statement_to ?? "?"}` : "—"}
                      </td>
                      <td>{isException ? "—" : d.row_count}</td>
                      <td><StatusPill doc={d} /></td>
                      <td>
                        <div className="flex gap-2">
                          {status.key !== "approved" && (
                            <button className="btn btn-primary btn-sm" onClick={() => onReview(d.document_id)}>
                              {isException ? "Review Document" : "Review"}
                            </button>
                          )}
                          {!isException && (
                            <button
                              className="btn btn-ghost btn-sm"
                              onClick={() => downloadExcel(d.document_id)}
                              disabled={exportingId === d.document_id}
                            >
                              {exportingId === d.document_id ? <span className="spinner" /> : <Icon name="download" size={13} />}
                              Excel
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
