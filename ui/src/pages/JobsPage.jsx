import { useState, useEffect } from "react";
import { listJobs, getJob } from "../api";
import StatusBadge from "../components/StatusBadge";

/** JobsPage — table of all submitted pipeline jobs with live refresh on Processing jobs. */
export default function JobsPage() {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    try {
      const data = await listJobs();
      setJobs(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // Poll every 5 s while any jobs are in-progress
    const id = setInterval(async () => {
      const data = await listJobs().catch(() => null);
      if (data) setJobs(data);
    }, 5000);
    return () => clearInterval(id);
  }, []);

  const hasPending = jobs.some((j) => j.status === "queued" || j.status === "processing");

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="page-title" style={{ marginBottom: 0 }}>Processing Jobs</h2>
        <div className="flex items-center gap-2">
          {hasPending && <span className="spinner" />}
          <button className="btn btn-ghost btn-sm" onClick={load}>Refresh</button>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {loading ? (
        <div className="flex items-center gap-2"><span className="spinner" /> Loading…</div>
      ) : jobs.length === 0 ? (
        <div className="empty">No jobs yet. Upload a document to start.</div>
      ) : (
        <div className="card">
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Job ID</th>
                  <th>Source File</th>
                  <th>Status</th>
                  <th>Stage</th>
                  <th>Document ID</th>
                  <th>Errors</th>
                  <th>Submitted</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.job_id}>
                    <td className="font-mono text-sm">{j.job_id.slice(0, 12)}…</td>
                    <td className="truncate">{j.source_file}</td>
                    <td><StatusBadge status={j.status} /></td>
                    <td className="text-sm text-muted">{j.progress_stage ?? "—"}</td>
                    <td className="font-mono text-sm">
                      {j.document_id ? `${j.document_id.slice(0, 12)}…` : "—"}
                    </td>
                    <td>
                      {j.errors?.length > 0 ? (
                        <span className="text-sm" style={{ color: "var(--danger)" }}>
                          {j.errors.slice(0, 1).join("; ")}
                        </span>
                      ) : (
                        <span className="text-muted text-sm">—</span>
                      )}
                    </td>
                    <td className="text-sm text-muted">
                      {new Date(j.created_at).toLocaleTimeString()}
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
