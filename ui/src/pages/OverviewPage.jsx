import { useState, useEffect } from "react";
import { getOverview } from "../api";
import Icon from "../components/Icon";
import StatusPill from "../components/StatusPill";
import { Skeleton } from "../components/Skeleton";

/**
 * OverviewPage — UI-UX-Implementation.md Phase B.1: a workflow dashboard,
 * not a BI dashboard (brief §4's own framing) — "what has happened, what
 * needs my attention," answerable in five seconds. `received` isn't scoped
 * to a calendar period (see schemas/api.py::OverviewResponse's own
 * docstring for why); a true period picker belongs with the brief's own
 * explicitly-deferred "analytics" phase, not this one.
 */
function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

const TILES = [
  { key: "received", label: "Received", sub: "statements", icon: "documents", tone: "neutral" },
  { key: "processing", label: "Processing", sub: "in progress", icon: "activity", tone: "processing" },
  { key: "review_required", label: "Review Required", sub: "need attention", icon: "alertTriangle", tone: "review" },
  { key: "approved", label: "Approved", sub: "statements", icon: "check", tone: "approved" },
  { key: "exceptions", label: "Exceptions", sub: "couldn't be processed", icon: "x", tone: "exception" },
];

export default function OverviewPage({ onOpenDoc }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    getOverview()
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div className="mb-4">
        <div className="text-sm text-muted">{greeting()}</div>
        <h2 className="page-title" style={{ marginBottom: 0 }}>Stock &amp; Sale Statements</h2>
      </div>

      {error && <div className="alert alert-error"><Icon name="alertTriangle" size={16} />{error}</div>}

      {loading ? (
        <div className="overview-grid">
          {TILES.map((t) => <div key={t.key} className="card overview-tile"><Skeleton width="60%" height={28} /><Skeleton width="80%" height={12} style={{ marginTop: 8 }} /></div>)}
        </div>
      ) : data ? (
        <>
          <div className="overview-grid mb-4">
            {TILES.map((t) => (
              <div key={t.key} className={`card overview-tile overview-tile-${t.tone}`}>
                <div className="overview-tile-icon"><Icon name={t.icon} size={16} /></div>
                <div className="overview-tile-value">{data[t.key]}</div>
                <div className="overview-tile-label">{t.label}</div>
                <div className="text-sm text-muted">{t.sub}</div>
              </div>
            ))}
          </div>

          <div className="card">
            <div className="section-title">Recent Statements</div>
            {data.recent.length === 0 ? (
              <div className="empty"><Icon name="documents" size={32} /><p>Nothing submitted yet.</p></div>
            ) : (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr><th>Distributor</th><th>Period</th><th>Status</th><th></th></tr>
                  </thead>
                  <tbody>
                    {data.recent.map((d) => (
                      <tr key={d.document_id}>
                        <td>{d.distributor_name ?? "Unidentified"}</td>
                        <td className="text-sm">{d.statement_from ? `${d.statement_from} → ${d.statement_to ?? "?"}` : "—"}</td>
                        <td><StatusPill doc={d} /></td>
                        <td>
                          <button className="btn btn-ghost btn-sm" onClick={() => onOpenDoc(d.document_id)}>
                            Open<Icon name="arrowRight" size={12} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}
