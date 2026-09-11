import { useState, useEffect } from "react";
import { listDocuments, exportDocumentExcel } from "../api";
import StatusBadge from "../components/StatusBadge";

/** DocumentsPage — list of all processed documents with export and review links. */
export default function DocumentsPage({ onReview }) {
  const [docs, setDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    listDocuments()
      .then(setDocs)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const downloadExcel = async (docId) => {
    try {
      const blob = await exportDocumentExcel(docId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${docId}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert(`Export failed: ${e.message}`);
    }
  };

  return (
    <div>
      <h2 className="page-title">Documents</h2>

      {error && <div className="alert alert-error">{error}</div>}

      {loading ? (
        <div className="flex items-center gap-2"><span className="spinner" /> Loading…</div>
      ) : docs.length === 0 ? (
        <div className="empty">No documents in the database yet. Upload and process a document first.</div>
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
                  <th>Rows</th>
                  <th>Needs Review</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {docs.map((d) => (
                  <tr key={d.document_id} className={d.needs_review_count > 0 ? "flagged" : ""}>
                    <td>{d.distributor_name ?? "—"}</td>
                    <td>{d.company_name ?? "—"}</td>
                    <td>
                      <span className={`badge ${d.document_type === "summary" ? "badge-info" : "badge-muted"}`}>
                        {d.document_type ?? "—"}
                      </span>
                    </td>
                    <td className="text-sm">
                      {d.statement_from ? `${d.statement_from} → ${d.statement_to ?? "?"}` : "—"}
                    </td>
                    <td>{d.row_count}</td>
                    <td>
                      {d.needs_review_count > 0 ? (
                        <span className="badge badge-warning">{d.needs_review_count}</span>
                      ) : (
                        <span className="badge badge-success">0</span>
                      )}
                    </td>
                    <td>
                      <div className="flex gap-2">
                        {d.needs_review_count > 0 && (
                          <button
                            className="btn btn-primary btn-sm"
                            onClick={() => onReview(d.document_id)}
                          >
                            Review
                          </button>
                        )}
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => downloadExcel(d.document_id)}
                        >
                          ↓ Excel
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
