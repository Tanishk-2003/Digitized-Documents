/**
 * API client for the Pharma DI FastAPI backend (http://localhost:8000).
 * All endpoints are documented in src/pharma_di/api/routes_*.py.
 */

const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

async function json(res) {
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

// ---------- Document / Job endpoints ----------

export async function uploadDocument(file, onProgress) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/api/documents/upload`, {
    method: "POST",
    body: form,
  });
  return json(res);
}

export async function listDocuments() {
  return json(await fetch(`${BASE}/api/documents`));
}

export async function getDocument(documentId) {
  return json(await fetch(`${BASE}/api/documents/${documentId}`));
}

export async function exportDocumentExcel(documentId) {
  const res = await fetch(`${BASE}/api/documents/${documentId}/export/excel`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.blob();
}

export async function listJobs() {
  return json(await fetch(`${BASE}/api/jobs`));
}

export async function getJob(jobId) {
  return json(await fetch(`${BASE}/api/jobs/${jobId}`));
}

// ---------- Review queue endpoints ----------

export async function getReviewQueue() {
  return json(await fetch(`${BASE}/api/review-queue`));
}

export async function approveDocument(documentId, notes) {
  const res = await fetch(`${BASE}/api/review/${documentId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ notes: notes || null }),
  });
  return json(res);
}

export async function correctDocument(documentId, { columnMappings, rowCorrections, notes }) {
  const res = await fetch(`${BASE}/api/review/${documentId}/correct`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      column_mappings: columnMappings || [],
      row_corrections: rowCorrections || [],
      notes: notes || null,
    }),
  });
  return json(res);
}
