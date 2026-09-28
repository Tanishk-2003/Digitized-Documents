import { useState } from "react";
import OverviewPage from "./pages/OverviewPage";
import UploadPage from "./pages/UploadPage";
import JobsPage from "./pages/JobsPage";
import StatementsPage from "./pages/StatementsPage";
import ReviewQueuePage from "./pages/ReviewQueuePage";
import DocumentReviewPage from "./pages/DocumentReviewPage";
import ApprovedDataPage from "./pages/ApprovedDataPage";
import Icon from "./components/Icon";
import { ToastProvider } from "./components/Toast";
import "./index.css";

// UI-UX-Implementation.md Phase A.1/B.1: relabeled around "Statement" as
// the central concept, Overview first (brief §18's own ideal nav order),
// Jobs demoted to a secondary "Processing" item, and Upload is reached via
// the "+ Submit Statement" header action below rather than sitting in the
// main nav (brief §3: a user thinks "I need to submit a statement," not
// "I need to navigate to the Upload module").
const TABS = [
  { id: "overview",   label: "Overview",         icon: "activity" },
  { id: "statements", label: "Statements",       icon: "documents" },
  { id: "review",     label: "Review Required",  icon: "alertTriangle" },
  { id: "approved",   label: "Approved Data",    icon: "grid" },
  { id: "processing", label: "Processing",       icon: "activity" },
];

function AppShell() {
  const [tab, setTab] = useState("overview");
  const [reviewDocId, setReviewDocId] = useState(null);
  const [reviewQueueIds, setReviewQueueIds] = useState(null); // ordered ids, set only when opened from the Review Required queue
  const [reviewOrigin, setReviewOrigin] = useState("statements"); // where Back should return to
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const openReview = (docId, queueIds = null) => {
    setReviewOrigin(tab);
    setReviewDocId(docId);
    setReviewQueueIds(queueIds);
    setTab("detail");
  };

  const navigateReview = (docId) => {
    setReviewDocId(docId);
  };

  const closeReview = () => {
    setReviewDocId(null);
    setReviewQueueIds(null);
    setTab(reviewOrigin);
  };

  const selectTab = (id) => {
    setTab(id);
    if (id !== "detail") {
      setReviewDocId(null);
      setReviewQueueIds(null);
    }
    setSidebarOpen(false);
  };

  const activeLabel = TABS.find((t) => t.id === tab)?.label ?? "Statement Review";

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

        <div className="sidebar-submit">
          <button className="btn btn-primary w-full" onClick={() => selectTab("upload")}>
            <Icon name="upload" size={14} />+ Submit Statement
          </button>
        </div>

        <div className="sidebar-footer">Local-only · no data leaves this machine</div>
      </aside>

      <div className="app-content">
        <div className="topbar">
          <button className="menu-btn" onClick={() => setSidebarOpen(true)} aria-label="Open menu">
            <Icon name="menu" size={20} />
          </button>
          <h1>{tab === "upload" ? "Submit Statement" : activeLabel}</h1>
        </div>

        <main className="main" key={tab}>
          {tab === "overview" && <OverviewPage onOpenDoc={openReview} />}
          {tab === "statements" && <StatementsPage onReview={openReview} />}
          {tab === "review" && <ReviewQueuePage onOpenDoc={openReview} />}
          {tab === "approved" && <ApprovedDataPage />}
          {tab === "processing" && <JobsPage />}
          {tab === "upload" && <UploadPage />}
          {tab === "detail" && reviewDocId && (
            <DocumentReviewPage
              documentId={reviewDocId}
              queueIds={reviewQueueIds}
              onBack={closeReview}
              onNavigate={navigateReview}
            />
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
