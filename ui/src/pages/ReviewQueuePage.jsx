import { useState, useEffect } from "react";
import { getReviewQueue } from "../api";
import Icon from "../components/Icon";
import StatementCard from "../components/StatementCard";
import { SkeletonCard } from "../components/Skeleton";

/** Maps ReviewQueueItem (api/schemas/api.py) onto StatementCard's normalized
 * shape — kept local to this page since StatementsPage.jsx normalizes a
 * differently-shaped response (DocumentSummaryResponse) the same way. */
function toStatementCardProps(item) {
  return {
    document_id: item.document_id,
    distributor_name: item.distributor_name,
    company_name: item.company_name,
    period: item.statement_period,
    document_type: item.document_type,
    row_count: item.total_rows,
    needs_review_count: item.flagged_rows_count,
    reason_summary: item.review_reason_summary,
    source_file: item.source_file,
  };
}

/** ReviewQueuePage — "Review Required": statements that need a human to
 * look at them, with a plain-language breakdown of why (UI-UX-Implementation.md
 * Phase A.2) instead of raw validation-rule text. */
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
      <h2 className="page-title">Review Required</h2>

      {error && <div className="alert alert-error"><Icon name="alertTriangle" size={16} />{error}</div>}

      {loading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <SkeletonCard /><SkeletonCard /><SkeletonCard />
        </div>
      ) : queue.length === 0 ? (
        <div className="empty">
          <Icon name="checkCircle" size={36} style={{ color: "var(--success)" }} />
          <p>Nothing needs your attention — every statement is approved.</p>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {queue.map((item) => (
            <StatementCard
              key={item.document_id}
              doc={toStatementCardProps(item)}
              onOpen={(docId) => onOpenDoc(docId, queue.map((q) => q.document_id))}
            />
          ))}
        </div>
      )}
    </div>
  );
}
