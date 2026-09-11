import { useState, useCallback } from "react";
import { uploadDocument } from "../api";

/**
 * UploadPage — drag-and-drop or click-to-upload document ingestion.
 * Shows live job status after submission.
 */
export default function UploadPage() {
  const [dragOver, setDragOver] = useState(false);
  const [jobs, setJobs] = useState([]);
  const [error, setError] = useState(null);

  const submit = useCallback(async (file) => {
    setError(null);
    try {
      const job = await uploadDocument(file);
      setJobs((prev) => [{ ...job, fileName: file.name }, ...prev]);
    } catch (e) {
      setError(e.message);
    }
  }, []);

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

  return (
    <div>
      <h2 className="page-title">Upload Document</h2>

      {error && <div className="alert alert-error">{error}</div>}

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
          <span style={{ fontSize: 36 }}>📄</span>
          <p style={{ fontWeight: 600, marginTop: 8 }}>
            Drag &amp; drop document images or click to browse
          </p>
          <p>Supported: JPG, PNG, TIF, PDF</p>
        </label>
      </div>

      {jobs.length > 0 && (
        <div className="card">
          <div className="section-title">Submitted Jobs</div>
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
                    <td>
                      <span className={`badge ${j.status === "completed" ? "badge-success" : j.status === "failed" ? "badge-danger" : "badge-info"}`}>
                        {j.status}
                      </span>
                    </td>
                    <td className="font-mono text-sm">{j.document_id?.slice(0, 12) ?? "—"}…</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-sm text-muted mt-2">
            ⚠ Processing runs in the background (PaddleOCR can take several minutes). Check Jobs tab for progress.
          </p>
        </div>
      )}
    </div>
  );
}
