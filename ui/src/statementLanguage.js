/**
 * statementLanguage.js — UI-UX-Implementation.md Phase A: the one place
 * that translates backend rule/status codes into the business-friendly
 * vocabulary the UI-UX brief asks for (§8, §15), so every page uses the
 * same words instead of each screen inventing its own phrasing.
 *
 * Kept as plain data/functions, not baked into a component, since two
 * different pages (Statements list, Statement Inbox) need the same
 * translation applied to two different API response shapes.
 */

/** Business-friendly summary per validation rule (R1-R7, schemas/validation.py::RuleId).
 * The backend groups review reasons by rule_id and gives a count + one raw
 * technical sample_detail (Phase A.2) — this table supplies the primary,
 * plain-language phrase; the raw detail stays available as a secondary,
 * expandable "technical details" string, never the primary label. */
export const RULE_LABELS = {
  R1_reconciliation: "stock quantities don't reconcile",
  R2_totals_crossfoot: "printed totals don't add up",
  R3_derived_columns: "a derived total doesn't match",
  R4_rate_coherence: "a rate calculation doesn't match",
  R5_sign_plausibility: "an unusual value was found",
  R6_confidence_gate: "some values need verification",
  R7_page_integrity: "a document quality issue",
};

export function ruleLabel(ruleId) {
  return RULE_LABELS[ruleId] ?? "an issue was found";
}

/**
 * normalizeReason — review_reasons entries persisted before this project's
 * UI-UX-Implementation.md Phase A backend change are still plain strings
 * (e.g. "1 field(s) below 0.85: worst is sales_quantity at 0.42") sitting
 * in the real database from earlier pipeline runs; the JSON column doesn't
 * retroactively reshape historical rows when the Python schema changes.
 * Documents processed from here on carry the new {code, message, rule_id}
 * shape. Normalizing here means either shape renders sensibly instead of
 * the old string's `.rule_id`/`.message` silently reading as undefined.
 */
export function normalizeReason(r) {
  if (typeof r === "string") return { rule_id: null, message: r };
  return r;
}

/** One reason-summary entry -> "3 quantity values need verification" */
export function summarizeReason({ rule_id, count }) {
  const label = ruleLabel(rule_id);
  return `${count} ${label}`;
}

/**
 * deriveStatementStatus — the ONE status a "statement" (Document) shows
 * across every screen (brief §15: "your entire application should use
 * these same statuses"). Deliberately not the same enum as ReviewStatus
 * (row-level) or JobStatus (background-job-level) — this is a coarser,
 * business-facing status computed from what those already expose.
 *
 * `exception` (brief §6, "VERY IMPORTANT"): a document with no identified
 * distributor, or with zero extracted rows, is a processing problem, not a
 * normal statement — it must never look like a plausible, reviewed
 * statement with nothing wrong.
 */
export function deriveStatementStatus(doc) {
  if (!doc.distributor_name || doc.row_count === 0) {
    return { key: "exception", label: "Needs Attention", icon: "alertTriangle", className: "status-exception" };
  }
  if ((doc.needs_review_count ?? doc.flagged_rows_count ?? 0) > 0) {
    return { key: "review", label: "Review Required", icon: "alertTriangle", className: "status-review" };
  }
  return { key: "approved", label: "Approved", icon: "check", className: "status-approved" };
}
