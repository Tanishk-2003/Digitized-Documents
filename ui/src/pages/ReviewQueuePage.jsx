import { useState, useEffect } from "react";
import { getReviewQueue } from "../api";

/** ReviewQueuePage — lists all documents that need human review with reason summary. */
export default function ReviewQueuePage({ onOpenDoc }) {
  const [queue, setQueue] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    getReviewQueue()
      .then(setQueue)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <h2 className="page-title">Review Queue</h2>

      {error && <div className="alert alert-error">{error}</div>}

      {loading ? (
        <div className="flex items-center gap-2"><span className="spinner" /> Loading…</div>
      ) : queue.length === 0 ? (
        <div className="empty">
          <span style={{ fontSize: 32 }}>✅</span>
          <p style={{ marginTop: 12 }}>Review queue is empty — all documents have been reviewed.</p>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {queue.map((item) => (
            <div key={item.document_id} className="card">
              <div className="flex items-center justify-between">
                <div>
                  <div style={{ fontWeight: 700, fontSize: 15 }}>
                    {item.distributor_name ?? "Unknown Distributor"}
                    {item.company_name && (
                      <span style={{ fontWeight: 400, color: "var(--muted)", marginLeft: 8 }}>
                        / {item.company_name}
                      </span>
                    )}
                  </div>
                  <div className="text-sm text-muted mt-1">
                    {item.statement_period && <span>📅 {item.statement_period} · </span>}
                    {item.document_type && <span>{item.document_type} · </span>}
                    {item.total_rows} rows · {" "}
                    <span style={{ color: "var(--warning)", fontWeight: 600 }}>
                      {item.flagged_rows_count} flagged
                    </span>
                  </div>
                  {item.distinct_review_reasons.length > 0 && (
                    <div className="reasons mt-1">
                      ⚠ {item.distinct_review_reasons.slice(0, 3).join(" · ")}
                      {item.distinct_review_reasons.length > 3 && " …"}
                    </div>
                  )}
                </div>
                <button
                  className="btn btn-primary"
                  onClick={() => onOpenDoc(item.document_id)}
                >
                  Open →
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
