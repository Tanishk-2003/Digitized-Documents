import { useState, useCallback, useEffect } from "react";
import { uploadDocument, listJobs } from "../api";
import Icon from "../components/Icon";
import StatusBadge from "../components/StatusBadge";
import { useToast } from "../components/Toast";

const STEPS = [
  "We read the statement",
  "We standardize the stock & sales data",
  "We validate the extracted values",
  "We ask you to review only uncertain items",
  "Approved data becomes available for export",
];

/**
 * UploadPage — UI-UX-Implementation.md Phase B.3: reframed as submission,
 * not a generic file-upload utility (brief §13/§14) — the drop zone speaks
 * in terms of "statement," a "What happens next" explainer builds trust
 * that a photographed statement turns into checked data automatically, and
 * a live summary line ("N submitted, M processed, K need attention")
 * replaces having to read a raw per-job table to know whether it worked.
 * Job status polling reuses JobsPage's own interval pattern.
 */
export default function UploadPage() {
  const [dragOver, setDragOver] = useState(false);
  const [jobs, setJobs] = useState([]);
  const showToast = useToast();

  const submit = useCallback(
    async (file) => {
      try {
        const job = await uploadDocument(file);
        setJobs((prev) => [{ ...job, fileName: file.name }, ...prev]);
        showToast(`${file.name} queued for processing`);
      } catch (e) {
        showToast(`Upload failed: ${e.message}`, { type: "error" });
      }
    },
    [showToast],
  );

  const onDrop = useCallback(
    (e) => {
      e.preventDefault();
      setDragOver(false);
      Array.from(e.dataTransfer.files).forEach(submit);
    },
    [submit],
  );

  const onFileChange = (e) => {
    Array.from(e.target.files).forEach(submit);
    e.target.value = "";
  };

  useEffect(() => {
    if (jobs.length === 0) return undefined;
    const id = setInterval(async () => {
      const all = await listJobs().catch(() => null);
      if (!all) return;
      setJobs((prev) => prev.map((j) => {
        const fresh = all.find((a) => a.job_id === j.job_id);
        return fresh ? { ...fresh, fileName: j.fileName } : j;
      }));
    }, 3000);
    return () => clearInterval(id);
  }, [jobs.length]);

  const completedCount = jobs.filter((j) => j.status === "completed").length;
  const failedCount = jobs.filter((j) => j.status === "failed").length;
  const inProgressCount = jobs.length - completedCount - failedCount;

  return (
    <div>
      <h2 className="page-title">Submit Stock &amp; Sale Statement</h2>
      <p className="text-sm text-muted mb-4" style={{ marginTop: -12 }}>
        Upload the statement received from your stockist/distributor.
      </p>

      <div className="card mb-4">
        <label
          className={`upload-zone${dragOver ? " drag-over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
        >
          <input
            type="file"
            accept=".jpg,.jpeg,.png,.tif,.tiff,.pdf"
            multiple
            style={{ display: "none" }}
            onChange={onFileChange}
          />
          <div className="upload-icon">
            <Icon name="upload" size={24} />
          </div>
          <p className="upload-title">Drop statement here, or Browse files</p>
          <p>PDF · JPG · PNG · TIFF</p>
        </label>
      </div>

      {jobs.length > 0 && (
        <div className="card mb-4">
          <div className="section-title">Submitted Statements</div>
          <p className="text-sm mb-3">
            <strong>{jobs.length}</strong> statement{jobs.length === 1 ? "" : "s"} submitted
            {completedCount > 0 && <span> · <strong style={{ color: "var(--success)" }}>{completedCount}</strong> processed successfully</span>}
            {failedCount > 0 && <span> · <strong style={{ color: "var(--danger)" }}>{failedCount}</strong> need{failedCount === 1 ? "s" : ""} attention</span>}
            {inProgressCount > 0 && <span> · <strong>{inProgressCount}</strong> still processing</span>}
          </p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>File</th>
                  <th>Job ID</th>
                  <th>Status</th>
                  <th>Document ID</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.job_id}>
                    <td className="truncate">{j.fileName}</td>
                    <td className="font-mono text-sm">{j.job_id.slice(0, 12)}…</td>
                    <td><StatusBadge status={j.status} /></td>
                    <td className="font-mono text-sm">{j.document_id?.slice(0, 12) ?? "—"}…</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card">
        <div className="section-title">What happens next</div>
        <ol className="whats-next-list">
          {STEPS.map((step, i) => (
            <li key={i}>
              <span className="whats-next-num">{i + 1}</span>
              {step}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
