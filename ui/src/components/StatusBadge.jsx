/** StatusBadge — maps review_status / job status strings to coloured badges. */
const MAP = {
  needs_review:    ["badge-warning",  "Needs Review"],
  auto_accepted:   ["badge-success",  "Auto-accepted"],
  human_corrected: ["badge-info",     "Corrected"],
  queued:          ["badge-muted",    "Queued"],
  processing:      ["badge-info",     "Processing"],
  completed:       ["badge-success",  "Complete"],
  failed:          ["badge-danger",   "Failed"],
};

export default function StatusBadge({ status }) {
  const [cls, label] = MAP[status] ?? ["badge-muted", status ?? "—"];
  return <span className={`badge ${cls}`}>{label}</span>;
}
