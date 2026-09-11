import { useState } from "react";
import UploadPage from "./pages/UploadPage";
import JobsPage from "./pages/JobsPage";
import DocumentsPage from "./pages/DocumentsPage";
import ReviewQueuePage from "./pages/ReviewQueuePage";
import DocumentReviewPage from "./pages/DocumentReviewPage";
import "./index.css";

const TABS = [
  { id: "queue",     label: "Review Queue" },
  { id: "documents", label: "Documents" },
  { id: "jobs",      label: "Jobs" },
  { id: "upload",    label: "Upload" },
];

export default function App() {
  const [tab, setTab] = useState("queue");
  const [reviewDocId, setReviewDocId] = useState(null);

  const openReview = (docId) => {
    setReviewDocId(docId);
    setTab("review");
  };

  const closeReview = () => {
    setReviewDocId(null);
    setTab("queue");
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>💊 Pharma DI</h1>
        <nav>
          {TABS.map((t) => (
            <a
              key={t.id}
              href="#"
              className={tab === t.id ? "active" : ""}
              onClick={(e) => {
                e.preventDefault();
                setTab(t.id);
                if (t.id !== "review") setReviewDocId(null);
              }}
            >
              {t.label}
            </a>
          ))}
        </nav>
      </header>

      <main className="main">
        {tab === "queue" && <ReviewQueuePage onOpenDoc={openReview} />}
        {tab === "documents" && <DocumentsPage onReview={openReview} />}
        {tab === "jobs" && <JobsPage />}
        {tab === "upload" && <UploadPage />}
        {tab === "review" && reviewDocId && (
          <DocumentReviewPage documentId={reviewDocId} onBack={closeReview} />
        )}
      </main>
    </div>
  );
}
