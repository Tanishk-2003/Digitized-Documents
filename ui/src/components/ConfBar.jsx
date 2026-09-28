import Icon from "./Icon";

/** Confidence bar component.
 * score: 0.0 – 1.0 float from the pipeline's per-field extraction_confidence.
 *
 * `variant="business"` (UI-UX-Implementation.md Phase A.4, brief §8): leads
 * with a plain-language verdict (✓ Verified / ⚠ Needs verification /
 * ✕ Could not extract) instead of a bare percentage — the number is still
 * there, just demoted to a hover tooltip via the native `title` attribute
 * rather than being the primary, always-visible text.
 */
const THRESHOLDS = { high: 0.9, medium: 0.75 };

function bucket(score) {
  if (score == null) return "low";
  return score >= THRESHOLDS.high ? "high" : score >= THRESHOLDS.medium ? "medium" : "low";
}

const BUSINESS_LABEL = {
  high: { text: "Verified", icon: "check", className: "conf-high" },
  medium: { text: "Needs verification", icon: "alertTriangle", className: "conf-medium" },
  low: { text: "Could not verify", icon: "x", className: "conf-low" },
};

export default function ConfBar({ score, variant = "technical" }) {
  if (score == null && variant === "technical") return <span className="text-muted text-sm">—</span>;

  const cls = `conf-${bucket(score)}`;

  if (variant === "business") {
    const { text, icon, className } = BUSINESS_LABEL[bucket(score)];
    return (
      <span
        className={`conf-business-label ${className}`}
        title={score != null ? `Extraction confidence: ${Math.round(score * 100)}%` : "No confidence score recorded"}
      >
        <Icon name={icon} size={12} />
        {text}
      </span>
    );
  }

  const pct = Math.round(score * 100);
  return (
    <div className="conf-bar-wrap">
      <div className="conf-bar">
        <div className={`conf-bar-fill ${cls}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-sm text-muted">{pct}%</span>
    </div>
  );
}
