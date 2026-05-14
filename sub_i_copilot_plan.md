# Handoff Copilot — Original Plan

*Working project doc. For me and Claude to iterate on as I build. (The project was originally called "Sub-I Co-Pilot"; it's now Handoff Copilot. The filename stays `sub_i_copilot_plan.md` since other docs link to it.)*

> **Note (2026-05-12).** This is the *original* plan, preserved as an artifact. For the current state of the app, see [`README.md`](README.md) and [`BUILD_SPEC.md`](BUILD_SPEC.md). The biggest deltas from this plan:
> - **Watch-outs and time-bucketing collapsed into one LLM call.** The plan had three separate calls (extraction, watch-outs generation, time-bucketing). They were merged into a single extraction call by adding `Task.when` (enum) and `Contingency` (trigger/action) to the schema. Cheaper, faster, less hallucination surface.
> - **Rendering uses HTML + browser-print, not WeasyPrint.** WeasyPrint had Windows install pain; the HTML one-pager via Ctrl+P → Save as PDF turned out to be good enough.
> - **A UI shipped.** This plan said "no UI beyond a CLI." That changed — `app.py` is a Streamlit webapp with four input tabs (Upload / Record / Paste / Demo) and three output tabs (Print sheet / Shift mode / Timeline), deployable to Streamlit Cloud.
> - **Eval loop is still TODO.** Phase 7 of the build order. The methodology in this doc still applies.

---

## What this is

A vibe-coded personal tool for processing clinical handoffs. Input: a voice memo of a handoff for a panel of 4 to 6 patients. Output: a printable one-page reference sheet I carry during my shift.

The tool exists because the cognitive load of receiving handoff and then carrying that information across a 12+ hour shift is real, and the existing options (writing it down by hand, typing into a list, using a paper sign-out template) don't surface the things I most want surfaced: anticipated overnight events, medication-specific monitoring, and decision triggers per patient.

## Why I'm building it

Three reasons, in order.

1. **I'm a sub-I.** The cognitive load is high and I want a personal tool that fits how I actually work on shift.
2. **Reps with composable agent systems.** Multi-step LLM workflows with structured outputs, eval loops, and modular prompts. This is the cleanest project I could think of where I'd actually use the output every day.
3. **The clinical reasoning question is genuinely interesting.** Can a system that knows nothing about a patient except the I-PASS handoff generate clinically meaningful anticipatory guidance? If the answer is yes, the design space is much bigger than handoffs.

## Scope

### What it does

1. Transcribes a voice memo of a verbal handoff
2. Extracts structured I-PASS data per patient
3. Generates a watch-outs list per patient via clinical reasoning over the structured handoff
4. Time-buckets the watch-outs into a shift checklist
5. Renders all of the above as a single-page printable PDF

### What it does not do

- No live updates during shift (if I need to update, I write on the paper)
- No end-of-shift sign-out generation
- No UI beyond a CLI
- No real-time / streaming ASR
- No integration with the EHR or any clinical system

The one-pager is the deliverable. Keeping the scope this tight is what makes the project actually finishable.

---

## Design decisions

### Synthetic data only

All development and evaluation use synthetic handoffs. No real PHI through commercial APIs, even for a personal tool. I'll write 10 to 15 synthetic handoffs based on case patterns I've seen on rotations, using publicly available I-PASS training examples as starting templates.

### Audio + text inputs

The system accepts either a voice memo or pasted text. Audio is the natural use case; text is what I use during development so I can iterate on prompts without re-running ASR every time.

### ASR

Whisper API or `whisper.cpp` locally. Either is fine. The system is latency-insensitive for my use case since I process the handoff once at the start of shift.

### Patient segmentation

One LLM call with a strict structured-output schema (`{patients: [{...}, ...]}`) that handles segmentation and extraction in a single step. Modern frontier models handle this cleanly when the schema is enforced via the API's structured output mechanism.

### Rendering

Markdown → HTML → PDF via WeasyPrint. Designed to look like something I'd actually carry: single sheet, black ink, simple typography, designed for print.

---

## Schema

The clinical artifact at the center of the project. Tuned to how I actually receive handoffs.

```
Patient {
  identifier:        string    // "Bed 5" or "Mr. K"
  one_liner:         string    // age, sex, admission Dx, current hospital day
  illness_severity:  enum      // "stable" | "watcher" | "unstable"  (I-PASS S)
  active_issues:     [string]
  active_meds:       [{name, dose, route, frequency, indication, notable_levels}]
  pending_results:   [string]
  contingencies:     [{trigger, action}]
  code_status:       string
  family_situation:  string?
  confidence_flags:  [{field, reason}]  // where audio was unclear
  completeness_gaps: [string]  // I-PASS fields missing from this handoff
}
```

The `confidence_flags` and `completeness_gaps` arrays matter most. They encode uncertainty directly into the data model rather than letting the model confabulate to fill in missing fields.

---

## Watch-outs generation

Separate LLM call per patient. The prompt should:

- Generate three categories: **anticipated overnight events**, **medication-specific monitoring**, **decision triggers**
- Cap at 5 items per category
- Each item must be specific to this patient and supported by the handoff data ("K+ 3.4 this morning, on IV Lasix BID, expect hypoK by AM, check 04:00 BMP" rather than "watch for hypokalemia on Lasix")
- Decision triggers must include both the finding and the action ("SBP < 90 → call resident")
- If information needed for good anticipation is missing, surface it as an "I'd want to know" list rather than guess
- Never generate items not supported by the handoff data

The driving rule: hallucinated watch-outs are worse than missing ones.

---

## Time-bucketing

A small LLM call classifies each watch-out into a standard shift checkpoint:

- At signout (now)
- 22:00 (pre-bed med pass)
- 00:00 (lab draws, IV med checks)
- 04:00 (AM labs)
- Pre-rounds (~05:00-06:00)
- PRN (event-triggered)

Standard nursing shift structure. Keeps the bucketing logic simple and debuggable.

---

## Output: the one-pager

Single sheet, designed to print and carry. Layout:

- **Header**: date, name, shift hours
- **Per patient**: identifier, one-liner, illness severity, top 3 watch-outs
- **Bottom**: time-bucketed checklist for the whole panel
- **"I'd want to know" section** if any patients had completeness gaps

Portrait orientation, ~11pt body, scannable while walking.

---

## Eval plan

The piece I care most about getting right.

### Build the gold set first

For each synthetic handoff, write my own watch-outs list *before* running the system. That's the gold standard.

### Score on three dimensions

- **Precision**: of the agent's watch-outs, what fraction are clinically valid? Three buckets: clearly correct, debatable, clearly wrong.
- **Recall**: of my gold watch-outs, what fraction did the agent catch (exact or near-equivalent)?
- **Hallucination**: did the agent generate any items not supported by the handoff? Binary, per patient.

N of 10 is enough. The point is real numbers and real failure cases.

### Drill into two failure cases

- One where the agent missed something important. Explain why, fix via prompt or schema change.
- One where the agent generated something wrong. Explain why, constrain the prompt.

Save a before/after comparison on at least one case.

---

## Things to avoid

- **Building a UI.** A CLI is enough.
- **Over-engineering the architecture.** Python + a few API calls is the right shape. Resist langchain-style abstractions.
- **Using a frontier reasoning model for extraction.** A Sonnet- or GPT-4o-class model with structured outputs is faster and produces cleaner results.
- **Chasing real-time ASR.** Batch processing of a recorded voice memo is the use case.
- **Trying to handle every clinical edge case in v1.** The eval will surface what matters; iterate from there.

---

## Tech stack

- Python 3.11+
- Anthropic or OpenAI API (Sonnet-class or GPT-4o-class)
- Whisper (local or API)
- WeasyPrint for PDF rendering
- Pydantic for schema validation
- `.env` for keys, gitignored

## Planned project structure

```
sub-i-copilot/
├── README.md
├── pyproject.toml
├── .env.example
├── src/
│   ├── transcribe.py
│   ├── extract.py
│   ├── watchouts.py
│   ├── schedule.py
│   ├── render.py
│   └── pipeline.py
├── prompts/
│   ├── extraction.md
│   └── watchouts.md
├── data/
│   ├── synthetic_handoffs/
│   └── gold_watchouts/
├── evals/
│   ├── run_eval.py
│   └── results/
└── outputs/
    └── example_one_pager.pdf
```

---

## Open questions (revisit during/after build)

- Should watch-outs be strictly per-patient, or should the system also generate cross-patient considerations ("two patients on heparin, prioritize the one with the most recent dose change")?
- Should each generated watch-out have a confidence score, or is the binary "supported by handoff" filter enough?
- Is the right output one sheet per shift, or one card per patient that I flip through?
- Should time-bucketing be informed by patient-specific monitoring needs (e.g., a patient on Q1H neuro checks has a different bucket structure than a stable medicine patient)?
- What's the right way to handle situations where the handoff itself was bad? Surface the gaps loudly, or attempt to generate watch-outs anyway with warnings?
