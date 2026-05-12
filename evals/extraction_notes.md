# Extraction Notes

Observations from Phase 1 testing. These are logged here so Phase 7 (eval loop)
has a starting list of known issues to verify or dismiss with real numbers.

## Test run: 01_copd_lopez.txt — 2026-05-11

Model: claude-sonnet-4-5 (EXTRACTION_MODEL in src/extract.py)

### Observations

**illness_severity: "watcher" vs. gold "stable"**
- Model returned "watcher"; hand-written gold said "stable"
- Assessment: model is arguably more correct. Patient is on day 3/5 prednisone taper,
  still has active respiratory monitoring triggers, and anticipated discharge is conditional
  ("if stable"). "Watcher" is a defensible read. Gold standard may need updating, not the model.
- Action: watch for systematic severity inflation across all 10 handoffs. If model
  trends toward "watcher" for patients that were genuinely stable, revisit the
  extraction prompt's severity guidance.

**active_meds[prednisone].notable_levels — missing course-day**
- Handoff stated "prednisone day three of five"; model left notable_levels null.
- The schema field description says "last measured value or other notable monitoring data."
  Course-day counts ("day X of Y") are clinically meaningful for short courses but
  the field description doesn't make that explicit.
- Potential fix: add "course-day notation (e.g. 'day 3 of 5')" to the notable_levels
  field description in schema.py, or add an explicit instruction to the extraction prompt.

**active_meds[*].route — some blank**
- Routes were sparse. Less critical than dosing/indication, but relevant for
  monitoring (e.g. IV vs. PO furosemide has very different expected effect timing).
- Potential fix: add instruction to extraction prompt to infer standard routes when
  not stated (e.g. azithromycin is almost always PO for outpatient-to-inpatient bridge).

## Test run: 01_copd_lopez.txt + 02_hf_patel.txt — 2026-05-11 (post-fix)

After updating the `notable_levels` field description in schema.py:

- Maria Lopez (COPD): `notable_levels` now captures "day 3 of 5" for prednisone AND
  "spaced from q4h to q6h today" for duonebs. Both fixes landed.
- James Patel (HFrEF): extraction looks clean, including the held lisinopril
  with AKI reason (the "held with reason" example in the new description worked).

## Realism gap: synthetic scripts vs. real handoffs

Sub-I noted that real voice memos will differ from the synthetic scripts in ways
that matter for downstream rendering and any later supplementation logic:

- **Implicit thresholds.** Real handoffs often skip thresholds that interns are
  expected to know (e.g., "replete K and Mg" without saying "if K<4, Mg<2").
  The synthetic scripts state thresholds explicitly. If we ever add a
  medication-monitoring supplement (the deferred "25% layer"), it should be
  comfortable filling in standard thresholds for explicitly-named drugs.
- **Less formal speech.** Synthetic scripts read like written paragraphs. Real
  speech has hedges, restarts, filler words, and is generally messier.
- **Interruptions.** Real handoffs get interrupted (pages, questions). The
  transcript may have partial sentences, doubled-back-on facts, side comments
  about a different patient.

Action: when we move from synthetic scripts to real-recording testing (post-Phase
6 / ASR), revisit the extraction prompt to handle disfluencies and consider how
implicit clinical thresholds should be surfaced (probably via completeness_gaps
rather than fabrication).

## Notes on gold watchouts methodology

Gold watchouts in data/gold_watchouts/gold_watchouts.md were generated with LLM
assistance and then revised by the sub-I. This is a pragmatic choice — the primary
goal of this project is learning the vibe-coding / Claude Code workflow, not
pressure-testing clinical judgment rigorously. The gold set is still useful as a
structured reference for Phase 7 comparison; just interpret precision/recall numbers
with that methodological caveat in mind.
