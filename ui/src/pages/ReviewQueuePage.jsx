import { useState, useEffect } from "react";
import { getReviewQueue } from "../api";
import Icon from "../components/Icon";
import { SkeletonCard } from "../components/Skeleton";

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

      {error && <div className="alert alert-error"><Icon name="alertTriangle" size={16} />{error}</div>}

      {loading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <SkeletonCard /><SkeletonCard /><SkeletonCard />
        </div>
      ) : queue.length === 0 ? (
        <div className="empty">
          <Icon name="checkCircle" size={36} style={{ color: "var(--success)" }} />
          <p>Review queue is empty — all documents have been reviewed.</p>
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
                    {item.statement_period && <span>{item.statement_period} · </span>}
                    {item.document_type && <span>{item.document_type} · </span>}
                    {item.total_rows} rows · {" "}
                    <span style={{ color: "var(--warning)", fontWeight: 600 }}>
                      {item.flagged_rows_count} flagged
                    </span>
                  </div>
                  {item.distinct_review_reasons.length > 0 && (
                    <div className="reasons mt-1 flex items-start gap-2">
                      <Icon name="alertTriangle" size={13} style={{ marginTop: 2, flexShrink: 0 }} />
                      <span>
                        {item.distinct_review_reasons.slice(0, 3).join(" · ")}
                        {item.distinct_review_reasons.length > 3 && " …"}
                      </span>
                    </div>
                  )}
                </div>
                <button
                  className="btn btn-primary"
                  onClick={() => onOpenDoc(item.document_id)}
                >
                  Open <Icon name="arrowRight" size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
