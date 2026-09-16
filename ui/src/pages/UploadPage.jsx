import { useState, useCallback } from "react";
import { uploadDocument } from "../api";
import Icon from "../components/Icon";
import StatusBadge from "../components/StatusBadge";
import { useToast } from "../components/Toast";

/**
 * UploadPage — drag-and-drop or click-to-upload document ingestion.
 * Shows live job status after submission.
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

  return (
    <div>
      <h2 className="page-title">Upload Document</h2>

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
          <p className="upload-title">Drag &amp; drop document images, or click to browse</p>
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
                    <td><StatusBadge status={j.status} /></td>
                    <td className="font-mono text-sm">{j.document_id?.slice(0, 12) ?? "—"}…</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-sm text-muted mt-2 flex items-center gap-2">
            <Icon name="activity" size={13} />
            Processing runs in the background (PaddleOCR can take several minutes). Check the Jobs tab for progress.
          </p>
        </div>
      )}
    </div>
  );
}
