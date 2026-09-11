/** Confidence bar component.
 * score: 0.0 – 1.0 float from the pipeline's per-field extraction_confidence.
 */
export default function ConfBar({ score }) {
  if (score == null) return <span className="text-muted text-sm">—</span>;
  const pct = Math.round(score * 100);
  const cls = score >= 0.9 ? "conf-high" : score >= 0.75 ? "conf-medium" : "conf-low";
  return (
    <div className="conf-bar-wrap">
      <div className="conf-bar">
        <div className={`conf-bar-fill ${cls}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-sm text-muted">{pct}%</span>
    </div>
  );
}
