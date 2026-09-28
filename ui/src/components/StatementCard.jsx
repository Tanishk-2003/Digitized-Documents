import Icon from "./Icon";
import { deriveStatementStatus, summarizeReason } from "../statementLanguage";

/**
 * StatementCard — the one card design used everywhere a "statement"
 * (Document) is listed: the Statements list and the Review Required view
 * (UI-UX-Implementation.md Phase A.1a — one underlying list, one language,
 * not two screens that can drift apart).
 *
 * Expects a normalized shape so it doesn't care which of the two API
 * responses (DocumentSummaryResponse vs. ReviewQueueItem) produced it:
 *   { document_id, distributor_name, company_name, period, document_type,
 *     row_count, needs_review_count, reason_summary?, source_file }
 */
export default function StatementCard({ doc, onOpen }) {
  const status = deriveStatementStatus(doc);

  if (status.key === "exception") {
    // Brief §6 ("VERY IMPORTANT"): never render this as if it were a normal,
    // reviewed statement — no product/row counts, a plain explanation, and
    // a single action that goes straight to the document, not a review flow
    // implying there's extracted data worth reviewing.
    return (
      <div className="card statement-card statement-card-exception">
        <div className="statement-card-icon">
          <Icon name="alertTriangle" size={20} />
        </div>
        <div style={{ flex: 1 }}>
          <div className="statement-card-title">Distributor could not be identified</div>
          <div className="text-sm text-muted mt-1">
            Document: <span className="font-mono">{doc.source_file?.split(/[\\/]/).pop() ?? "unknown file"}</span>
          </div>
          <div className="text-sm text-muted mt-1">
            We couldn't confidently identify the stockist from this document.
          </div>
        </div>
        <button className="btn btn-ghost" onClick={() => onOpen(doc.document_id)}>
          Review Document <Icon name="arrowRight" size={14} />
        </button>
      </div>
    );
  }

  const productLabel =
    doc.document_type === "summary"
      ? "Company-level summary"
      : `${doc.row_count} product${doc.row_count === 1 ? "" : "s"} extracted`;

  return (
    <div className={`card statement-card${status.key === "review" ? " statement-card-review" : ""}`}>
      <div style={{ flex: 1 }}>
        <div className="statement-card-title">
          {doc.distributor_name}
          {doc.company_name && <span className="statement-card-company"> / {doc.company_name}</span>}
        </div>
        <div className="text-sm text-muted mt-1">
          {doc.period && <span>{doc.period} · </span>}
          {productLabel}
        </div>
        {status.key === "review" ? (
          <div className="reasons mt-1 flex items-center gap-2">
            <Icon name="alertTriangle" size={13} />
            <span>{doc.needs_review_count} item{doc.needs_review_count === 1 ? "" : "s"} need{doc.needs_review_count === 1 ? "s" : ""} your attention</span>
          </div>
        ) : (
          <div className="mt-1 flex items-center gap-2" style={{ color: "var(--success)", fontSize: 12, fontWeight: 600 }}>
            <Icon name="check" size={13} />
            <span>All clear</span>
          </div>
        )}
        {doc.reason_summary?.length > 0 && (
          <ul className="statement-card-reasons">
            {doc.reason_summary.slice(0, 3).map((r) => (
              <li key={r.rule_id} title={r.sample_detail}>{summarizeReason(r)}</li>
            ))}
          </ul>
        )}
      </div>
      <button className={`btn ${status.key === "review" ? "btn-primary" : "btn-ghost"}`} onClick={() => onOpen(doc.document_id)}>
        {status.key === "review" ? "Review Statement" : "View"} <Icon name="arrowRight" size={14} />
      </button>
    </div>
  );
}
