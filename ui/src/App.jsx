import { useState } from "react";
import UploadPage from "./pages/UploadPage";
import JobsPage from "./pages/JobsPage";
import DocumentsPage from "./pages/DocumentsPage";
import ReviewQueuePage from "./pages/ReviewQueuePage";
import DocumentReviewPage from "./pages/DocumentReviewPage";
import FinalOutputPage from "./pages/FinalOutputPage";
import Icon from "./components/Icon";
import { ToastProvider } from "./components/Toast";
import "./index.css";

const TABS = [
  { id: "queue",     label: "Review Queue",  icon: "queue" },
  { id: "documents", label: "Documents",     icon: "documents" },
  { id: "final",     label: "Final Output",  icon: "grid" },
  { id: "jobs",      label: "Jobs",          icon: "activity" },
  { id: "upload",    label: "Upload",        icon: "upload" },
];

function AppShell() {
  const [tab, setTab] = useState("queue");
  const [reviewDocId, setReviewDocId] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const openReview = (docId) => {
    setReviewDocId(docId);
    setTab("review");
  };

  const closeReview = () => {
    setReviewDocId(null);
    setTab("queue");
  };

  const selectTab = (id) => {
    setTab(id);
    if (id !== "review") setReviewDocId(null);
    setSidebarOpen(false);
  };

  const activeLabel = TABS.find((t) => t.id === tab)?.label ?? "Document Review";

  return (
    <div className="app-shell">
      {sidebarOpen && <div className="sidebar-backdrop open" onClick={() => setSidebarOpen(false)} />}

      <aside className={`sidebar${sidebarOpen ? " open" : ""}`}>
        <div className="sidebar-brand">
          <div className="logo-mark">
            <Icon name="grid" size={15} style={{ color: "#fff" }} />
          </div>
          <div>
            <h1>Pharma DI</h1>
            <div className="subtitle">Stock &amp; Sale Intelligence</div>
          </div>
          <button className="sidebar-close" onClick={() => setSidebarOpen(false)} aria-label="Close menu">
            <Icon name="x" size={18} />
          </button>
        </div>

        <nav className="sidebar-nav">
          {TABS.map((t) => (
            <a
              key={t.id}
              href="#"
              className={tab === t.id ? "active" : ""}
              onClick={(e) => {
                e.preventDefault();
                selectTab(t.id);
              }}
            >
              <Icon name={t.icon} size={17} />
              {t.label}
            </a>
          ))}
        </nav>

        <div className="sidebar-footer">Local-only · no data leaves this machine</div>
      </aside>

      <div className="app-content">
        <div className="topbar">
          <button className="menu-btn" onClick={() => setSidebarOpen(true)} aria-label="Open menu">
            <Icon name="menu" size={20} />
          </button>
          <h1>{activeLabel}</h1>
        </div>

        <main className="main" key={tab}>
          {tab === "queue" && <ReviewQueuePage onOpenDoc={openReview} />}
          {tab === "documents" && <DocumentsPage onReview={openReview} />}
          {tab === "final" && <FinalOutputPage />}
          {tab === "jobs" && <JobsPage />}
          {tab === "upload" && <UploadPage />}
          {tab === "review" && reviewDocId && (
            <DocumentReviewPage documentId={reviewDocId} onBack={closeReview} />
          )}
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <AppShell />
    </ToastProvider>
  );
}
