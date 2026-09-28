# UI/UX Implementation Plan — Business Workflow Redesign

## Source and scope

Based on `UI-UX improvements.docx` (owner-provided review of the six screens built through P17). The document's own thesis: the backend and information architecture are already right for the intended MVP flow —

```
Submit → Process → Validate → Review exceptions → Approve → Standardized output
```

— but the UI currently *communicates* "I am an OCR system that extracted some rows and wants you to review them" when it should communicate "I received your stockist statements, processed them, identified the exceptions, and only need you to review the few things that require attention." The brief is explicit that this is a **reframing of the existing flow**, not new functionality, and it names its own non-goals for this round: no AI chatbot, forecasting, complex dashboards, maps, charts, RBAC, notification engines, workflow automation, distributor portals, or advanced analytics. Those stay out of scope here regardless of how natural they'd be to bolt on.

The document supplies its own priority order (its "P0 / P1 / P2"). This plan adopts that ordering, cross-checked against the real codebase below, and renumbers the work as **Phase A / B / C** so it isn't confused with this project's existing `IMPLEMENTATION_PLAN.md` P-numbering (P0–P17) — the two documents describe different halves of the project (pipeline vs. this UI language/workflow pass) and are meant to be read side by side, not merged.

## Technical grounding — verified against the real codebase before planning anything

Four things the brief either assumes or leaves implicit needed checking against actual code before they could be scoped honestly:

1. **"Statement" is not a new backend entity.** `persist/models.py::Document` already is one row per uploaded statement/page, with `distributor_name`, `company_name`, `statement_from/to`, `document_type`, `source_file`, and a `created_at` timestamp — everything the brief's "Statement" concept needs already exists. This phase relabels and reframes the existing `Document`/`Transaction`/`ReviewRecord` model in the UI's language; it does not require a new table or migration.

2. **Review-reason text is not purely a frontend formatting problem — the raw string IS the stored data.** Confirmed directly: `validate/confidence.py` builds `review_reasons` entries as `f"{len(below_threshold)} field(s) below {min_confidence:g}: worst is {worst_field} at {below_threshold[worst_field]:.2f}"` and `ReviewRecord.review_reasons` / `ReviewQueueItem.distinct_review_reasons` store and transmit exactly that string, with no structured (code, human-summary, technical-detail) split anywhere in `schemas/api.py`. "Make it business-friendly" therefore has a real backend-schema component — see Phase A.2 below — not just a JSX/copy edit. This directly qualifies the brief's own claim (§10) that its changes won't need "significant backend changes": most of the brief doesn't, but this specific item does.

3. **Evidence-linking (click a field, highlight the matching region on the source image, §7's "even better") needs OCR bounding boxes that do not currently survive to the API.** `schemas/ocr.py::OcrToken.bbox` exists at the OCR stage, but a repo-wide check found no `bbox`/bounding-box field anywhere in `schemas/canonical.py` (`TransactionRecord`/`CanonicalRow`) — it's discarded well before persistence. Wiring this through OCR → layout/table-assembly → mapping → canonical assembly → `persist/models.py` → the API is real, multi-stage plumbing work, not a UI change. The brief itself hedges this as "even better," not a hard requirement — treated here as an explicit stretch goal (Phase C), not something attempted inside Phase A's "fix Review Detail" item.

4. **Today's correction model is whole-row, not per-field/per-issue.** `DocumentReviewPage.jsx`'s `RowCorrectPanel` opens a form editing every field of one row at once; there is no concept of "the 6th of 6 issues on this statement" server- or client-side. The brief's §9/§10 "issue-by-issue" flow (Review issue → Correct → Save → Next issue → Approve, with `X of Y` navigation) is a genuine client-side state-machine redesign layered on the *existing* `/api/review/{id}/correct` endpoint — confirmed workable without a new endpoint (each "Save & Next Issue" click can submit one `row_corrections` entry against the current endpoint), matching the brief's claim that this specific item needs no backend change.

5. **A consistent status vocabulary is already half-built.** `ReviewStatus` (`auto_accepted`/`needs_review`/`human_corrected`) and `JobStatus` (`queued`/`processing`/`completed`/`failed`) already exist as real enums, and P17's `StatusBadge.jsx` already centralizes their color/label mapping in one place. The brief's ask (§15: a single ●/✓/⚠/✕ vocabulary used everywhere) is mostly a matter of extending that one component and using it uniformly, not inventing a new status system.

## Phase A — do first (the brief's own "P0")

Matches the brief's §21 table and §"prioritizing your UI work" list items 1–4.

**A.1 — Sidebar / information architecture relabel**
- Rename nav: `Review Queue` → **Statement Inbox**, `Documents` → folded into the Statements concept (see A.1a), `Final Output` → **Approved Data**, `Jobs` → demoted to a secondary **Processing** item.
- Proposed sidebar (adapting the brief's §3/§18 mockup to the 6 real screens that exist today, not inventing new ones): `Overview` (Phase B) · `Statements` · `Review Required` · `Approved Data` · `Processing`.
- `+ Submit Statement` becomes a persistent header action (opens the upload flow, e.g. as a modal or a dedicated route) rather than a full standalone nav tab — per the brief's §3 reasoning ("a user thinks 'I need to submit a statement,' not 'I need to navigate to the Upload module'").
- **A.1a — Reconcile `Documents` and `Review Queue` into one "Statements" list, per the brief's §21 table row for Documents ("make it the main Statement list rather than raw document storage").** Concretely: `DocumentsPage.jsx` becomes the canonical Statements list (one row per `Document`, status-driven, using the vocabulary from A.4), and "Review Required" becomes a *filtered view* of the same underlying data (`needs_review_count > 0`), not a second, differently-shaped screen. This avoids the two pages drifting into inconsistent language over time, which is exactly the kind of thing the brief is trying to eliminate.

**A.2 — Statement Inbox: business-oriented cards + a real backend change for review reasons**
- Card language: distributor/company, period, `"{N} products extracted"`, `"{K} require review"`, a single `[Review Statement →]` action — matching brief §5's mockup, replacing the current raw `1 field(s) below 0.85: worst is dump_quantity at 0.83` display.
- **Backend change required** (per grounding point 2 above): extend the validation engine's reason-producing code (`validate/confidence.py`, `validate/rules.py`, `validate/derived.py` — wherever a `review_reasons` string is appended) to emit a structured shape instead of one pre-formatted sentence, e.g.:
  ```python
  {"code": "low_confidence", "field": "dump_quantity", "summary": "1 quantity value is uncertain", "detail": "field(s) below 0.85: worst is dump_quantity at 0.83"}
  ```
  `ReviewRecord.review_reasons` (JSON column, already schema-flexible) and `ReviewQueueItem.distinct_review_reasons` / the per-row reasons surfaced in `DocumentDetailResponse` change from `list[str]` to `list[dict]`. The frontend renders `summary` as primary language and keeps `detail` available behind a "technical details" disclosure — satisfying the brief's own "keep the technical information available, but don't make it primary" instruction (§8) applied to reasons, not just confidence numbers.
  - **This is the one place in Phase A that touches the pipeline, not just the UI** — needs its own small test pass (existing `test_validate_real_images.py` reason-string assertions will need updating to the new shape) before the frontend work lands, so it should be sequenced as its own first step within Phase A, verified against the 6 real documents' existing, already-characterized findings (e.g. doc6's real R2 discrepancy, doc5's real D4 negative-receipt case) so the *content* of every reason stays correct — only its shape changes.

**A.3 — "Unknown Distributor" / zero-row records become a distinct exception state, not a normal card**
- Per brief §6 (marked "VERY IMPORTANT"): a document where `distributor_name` is null should never render as a plausible-looking `"Unknown Distributor · 0 rows · 0 flagged · Open"` card.
- Concretely: in `ReviewQueuePage.jsx`/the new Statements list, branch on `distributor_name == null` (or `total_rows == 0`) into a visually distinct exception card: `⚠ Distributor could not be identified`, the source filename, `"We couldn't confidently identify the stockist from the document"`, `[Review Document]`. Zero-row, unidentified documents should not count toward — or appear inside — the normal "N statements need review" figures; they're a processing exception, a different bucket.
- No backend change needed — `distributor_id`/`distributor_name` nullability and `total_rows`/`row_count` are already exposed by `DocumentSummaryResponse`/`ReviewQueueItem` exactly as needed; this is a frontend branching + copy change.

**A.4 — Review Detail: issue-by-issue correction workflow + gated Approve**
- Per grounding point 4: replace `RowCorrectPanel`'s "open a form, edit every field, Save Corrections" with an issue queue derived client-side from the rows already flagged `needs_review` (and, ideally, from per-field confidence <threshold within an otherwise-accepted row — needs a small client-side helper to flatten "flagged rows" + "individual low-confidence fields within accepted rows" into one ordered issue list). UI per brief §10: `{issue X of Y}`, one field's current value + reason + `[Correct value]` + `[Save & Next Issue]`, auto-advancing.
- Add `← Previous Statement | {X of Y} | Next Statement →` at the page level (brief §10) — requires the caller (`App.jsx`) to pass the review queue's ordered document-id list into `DocumentReviewPage`, not just the single id it opens today; a small, contained prop-drilling change, no new endpoint.
- **Gate "Approve All"** per brief §9: while `flagged_rows_count > 0`, show `[Review {N} Issues]` instead of an unconditionally-clickable `Approve All`; once every issue in the current statement's queue is resolved, switch to `✓ All issues resolved` + `[Approve Statement]`. Optionally (brief's stated fallback for MVP simplicity) offer `Approve verified rows ({N})` as a secondary action that calls the *existing* `approve_document` endpoint scoped to non-flagged rows only — no new endpoint required, since `approve_document` already iterates `ReviewRecord`s and only touches ones matching a status filter (today: `needs_review`); this just needs the "verified-only" subset already implied by that same filter.
- Field-level language per brief §8: replace bare `42%` displays with a primary `✓ Verified` / `⚠ Needs verification` / `✕ Could not extract` label (three buckets derived from the existing confidence float — thresholds already exist as `ACCEPT_THRESHOLD`/`LOW_CONFIDENCE_THRESHOLD` in `mapping/fuzzy.py`'s config-driven settings, reusable here without inventing new numbers), with the raw `Extraction confidence: 42%` demoted into a tooltip/detail toggle. `ConfBar.jsx` gets a `variant="business"` mode rather than being replaced.

**A.5 — Final Output → "Approved Data" rename + schema/export sanity pass**
- Straightforward rename of the nav item and page heading (`FinalOutputPage.jsx` → keep the file, or rename to `ApprovedDataPage.jsx` for clarity — recommend the rename, since P16/P17 already established the pattern of the file name matching the page's purpose).
- Brief's §21 table also asks to "show proper Stock & Sale columns" — the 12-column `FinalStockSaleRow` schema (P14) already *is* the correct Stock & Sale shape per this project's own `IMPLEMENTATION_PLAN.md`; this item is verification (confirm nothing regressed) rather than new design, unless the owner wants column relabeling to match the brief's more business-friendly field names (e.g. `stockist_distributor_name` → "Distributor" as a column header, which the existing `FinalOutputPage.jsx` already does at the display layer).

## Phase B — then add (the brief's own "P1")

**B.1 — Overview page (new)**
- New `OverviewPage.jsx` + a new nav entry, first item in the sidebar. Per brief §4's mockup: a greeting line, current period, 4–5 stat tiles (Received / Processing / Review Required / Approved / — Exceptions folded into the A.3 exception bucket rather than a separate top-level number, to avoid double-counting against "Review Required"), and a short "Recent Statements" list reusing the same status vocabulary as everywhere else.
- **Backend**: needs one new aggregate endpoint, e.g. `GET /api/overview`, returning the counts (`received`, `processing`, `review_required`, `approved`, `exceptions`) plus the N most recent `DocumentSummaryResponse`-shaped rows. This is a read-only aggregation over existing tables (`Document`/`Transaction`/`ReviewRecord`/`JobManager`'s in-memory jobs for the "processing" count) — no schema change, one new route + one new repository query function, following the exact pattern `routes_documents.py::list_documents` already uses.

**B.2 — Submission progress surfaced per-statement**
- Per brief §12: inside the Statements list / a statement's own row, show a small checklist (`Uploading ✓ / Processing ✓ / Extracting ✓ / Validation ⏳`) instead of sending the user to the separate, technical Jobs page to understand where a statement is. Data already exists (`JobResponse.progress_stage`, `.status`); this is a mapping/rendering change linking a `Document.id` back to its originating `Job.document_id` (already a field on `JobResponse` today) so the Statements list can show live-ish status without a page navigation.
- Jobs page itself stays, demoted to the "Processing" sidebar item per brief §21's table row (`⚠️ Keep as secondary Processing screen`) — no removal, just de-emphasis, matching the brief's own explicit instruction not to hide operationally-useful detail, only to stop leading with it.

**B.3 — Upload → "Submit Statement" reframe**
- Rename `UploadPage.jsx` heading/copy per brief §13 (`Submit Stock & Sale Statement`, `Drop statement here / or Browse files`, the explicit `PDF • JPG • PNG • TIFF` format line already matches `_ALLOWED_EXTENSIONS` in `routes_documents.py`).
- Add the brief's §14 "What happens next" 5-step explainer as static copy beneath the drop zone — no backend change, pure content addition reflecting the pipeline's real stages (already accurately nameable from `PipelineState`'s own node trace: ingest/preprocess → OCR/layout/mapping → validate → review → export).
- Post-upload summary per brief §13's second mockup (`"3 statements submitted / 2 processed successfully / 1 needs attention"`) — achievable client-side today by polling the submitted jobs' `JobResponse.status`, same mechanism `JobsPage.jsx` already uses.

## Phase C — explicitly deferred (the brief's own "P2," plus this plan's own stretch items)

Not built in this pass; listed so they aren't silently reconsidered later without a deliberate decision:

- Evidence-linking / click-to-highlight on the source image (grounding point 3) — real OCR-bbox plumbing work, no small version of this exists.
- "Submission health" collection-progress bar (brief §16) — a nice-to-have on top of Phase B.1's Overview page; skipped for this pass since the brief itself frames it as "because eventually Zorvia may have many distributors," not a current need.
- Everything the brief itself names as out of scope: analytics, stock trends, distributor performance, actionable insights, AI chatbot, forecasting, complex dashboards, maps, charts, advanced RBAC, notification engines, workflow automation, distributor portals.

## Open questions worth the owner's confirmation before Phase A starts

Stated as explicit assumptions rather than left blank, per this project's own working convention — correct any that are wrong:

1. **"Statements" replacing "Documents" as a nav concept** — assumed to mean UI relabeling only; API routes/response field names (`document_id`, `/api/documents`) stay as-is internally, since renaming those would ripple into every existing test and the UI/README already written for P16. Only user-facing labels change.
2. **Review-reasons schema change (A.2)** — assumed acceptable to change `review_reasons`/`distinct_review_reasons` from `list[str]` to `list[dict]`, which is a breaking API response shape change for anything currently parsing those fields (today: only this project's own frontend does). Flagged because it's the one Phase A item that isn't purely additive.
3. **Per-field vs. per-row correction (A.4)** — assumed the issue queue can be built by flattening existing `review_reasons`/per-field confidence data client-side, without needing the backend to pre-compute an ordered "issue list." If the owner wants issue ordering/grouping logic to live server-side instead (e.g. for consistency across future non-web clients), that's a small additional backend endpoint, not a blocker to starting.
4. **Scope of the "Statement Inbox = filtered Statements list" merge (A.1a)** — assumed rather than keeping Review Queue and Documents as two separately-maintained pages. If the owner specifically wants them to stay separate screens with independent designs, A.1a is dropped and each page gets its own smaller language pass instead.

## Verification approach (unchanged from this project's own established discipline)

Every phase item gets built, then checked against real data — the same standard `IMPLEMENTATION_PLAN.md`'s P0–P17 held throughout: run the full test suite after any backend change (A.2's reason-shape change specifically needs its own before/after check against all 6 real documents' already-characterized findings, not just "tests pass"), and test every UI change live in a browser against the real API before calling it done, per this project's standing rule that UI work isn't verified by a clean build alone.

## Suggested sequencing

Phase A lands as one reviewable unit before Phase B starts, matching how every phase in `IMPLEMENTATION_PLAN.md` shipped — implement, verify against real data, get a look before moving on, rather than building all of Phase A + B together and reviewing once at the end.
