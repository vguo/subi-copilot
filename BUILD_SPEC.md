# Sub-I Handoff Co-Pilot — Build Spec

A self-contained specification for rebuilding this app from scratch. Pair this file with the synthetic handoff scripts in `data/synthetic_handoffs/` and any LLM with code-writing ability should be able to produce a working end-to-end implementation.

---

## 1. What you are building

**Goal.** A personal tool that turns a verbal sign-out (voice memo or pasted transcript) into a printable one-page reference sheet that an overnight intern can carry on shift. One sheet per shift, up to 6 patient cards on letter paper.

**Audience.** A single sub-intern using it for their own shifts. Synthetic / training data only. No PHI, no multi-user concerns, no HIPAA scope, no auth.

**Why it has to exist.** Verbal handoffs disappear the instant the day team walks out the door. The receiver re-derives clinical context all night from memory and chart-diving. A static one-pager is the cheapest possible intervention: capture what was said, structure it, print it, carry it.

**Non-goals.** No clinical decision support. No drug-interaction checking. No EHR integration. No vital-signs ingestion. No multi-tenant deployment. No real-time updates during the shift.

---

## 2. Pipeline architecture

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Audio /     │ →  │  Transcript  │ →  │  Structured  │ →  │  HTML one-   │
│  pasted text │    │  (text)      │    │  extraction  │    │  pager       │
└──────────────┘    └──────────────┘    │  (Pydantic)  │    │  (printable) │
                                         └──────────────┘    └──────────────┘
     ↑                    ↑                    ↑                    ↑
  3 inputs:           faster-          Anthropic Claude         Deterministic
  upload audio        whisper          Sonnet via tool-use      Python →
  record audio        (local CPU,      (Pydantic-shaped         HTML/CSS grid,
  paste text          no API)          tool input)              no LLM here
```

**Key invariant: rendering is deterministic.** No LLM is called in the render step. Whatever appears on the printed sheet was extracted from the speaker's words. This is the "verbatim-first" stance — the speaker said it, the model parsed it into a slot, the renderer drew it. The model is not inventing watch-outs or filling gaps with general clinical knowledge.

---

## 3. Design philosophy (non-negotiable)

These shaped every other decision. Preserve them.

1. **Verbatim-first.** ~75% of content on the sheet must trace back to specific phrases the speaker said. No hallucinated contingencies, no inferred home meds, no "based on the diagnosis, you should also watch for..." additions. The Claude extraction is the only LLM call and it is constrained by a tool-use schema.

2. **Uncertainty is data, not noise.** Two fields are load-bearing for honesty: `confidence_flags` (per-field uncertainty markers) and `completeness_gaps` (clinically significant absences). Better to flag "code status not stated" than to silently default to "full code."

3. **One LLM call per transcript.** Not three. The original plan had separate calls for extraction, time-bucketing, and watch-out generation — they were all collapsed into one extraction call by adding `Task.when` (enum) and `Contingency` (trigger/action pair) directly to the schema. Cheaper, faster, less hallucination surface.

4. **Cache aggressively.** Same transcript + same prompt + same schema + same model = identical extraction. Hash all four, write JSON to disk, skip the API. Auto-invalidates when any input changes.

5. **The card is small.** 6 cards on letter at 8pt body font. The schema descriptions enforce brevity: `day_events` max 3 items, no fact in two fields, one-liner carries a trajectory phrase so downstream fields don't repeat it.

6. **Print is the deployment target.** The one-pager renders to HTML, but the intent is browser → Ctrl+P → Save as PDF → print. CSS uses `@page letter` and explicit point sizes, not responsive units.

---

## 4. Tech stack

| Layer       | Choice                | Why                                                      |
|-------------|-----------------------|----------------------------------------------------------|
| Language    | Python 3.11+          | Type hints, Pydantic v2, broad ecosystem                 |
| Schema      | Pydantic v2           | Validates LLM output, generates JSON schema for tool-use |
| LLM         | Anthropic Claude Sonnet 4.5 | Tool-use produces clean structured JSON               |
| ASR         | faster-whisper        | Local CPU inference, no API key, ~4x faster than reference openai-whisper |
| UI          | Streamlit             | Fastest path to a usable webapp for one user             |
| Rendering   | String-templated HTML | Deterministic, debuggable, no template engine needed     |
| Deploy      | Streamlit Cloud       | Free tier, push-to-deploy from GitHub                    |
| Env config  | python-dotenv         | `.env` locally, `st.secrets` on Streamlit Cloud          |

Avoid: WeasyPrint (PDF dependency hell on Windows), Jinja (overkill for one template), LangChain (adds layers that hide the actual API call), Docker (one user, doesn't need it).

---

## 5. Project layout

```
sub-i-copilot/
├── app.py                          Streamlit webapp (presentation only)
├── pyproject.toml                  Local dev: pip install -e .
├── requirements.txt                Streamlit Cloud deployment
├── .env.example                    Template; user copies to .env
├── .gitignore                      Excludes .env, .cache, outputs, .venv
├── README.md
├── DEPLOY.md                       Step-by-step deploy to Streamlit Cloud
├── BUILD_SPEC.md                   This file
├── src/
│   ├── __init__.py                 (empty, makes src a package)
│   ├── schema.py                   Pydantic models — the data contract
│   ├── extract.py                  Transcript → HandoffExtraction (cached)
│   ├── transcribe.py               Audio → transcript (faster-whisper)
│   ├── render.py                   HandoffExtraction → HTML
│   ├── pipeline.py                 Thin orchestrator
│   └── demo_data.py                Hard-coded demo transcript + extraction
├── prompts/
│   ├── extraction.md               System prompt for the extraction call
│   └── one_pager.html              HTML/CSS template, contains {{CARDS}} sentinel
├── data/
│   └── synthetic_handoffs/         Fictional handoff transcripts (.txt)
├── outputs/                        Rendered HTML output (gitignored)
└── .cache/
    └── extractions/                Cached extraction JSON keyed by hash (gitignored)
```

---

## 6. The data model (verbatim — this is the contract)

`src/schema.py`. Pydantic v2. Every other module references these types.

```python
"""Pydantic schema for structured handoff extraction."""

from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class IllnessSeverity(str, Enum):
    STABLE = "stable"
    WATCHER = "watcher"
    UNSTABLE = "unstable"


class TaskTiming(str, Enum):
    """When an overnight task should be performed.

    Buckets match the standard nursing shift checkpoints. The enum values
    are the labels rendered on the one-pager, so they should read well to
    a tired intern at 03:00.
    """
    NOW = "now"               # do at start of shift / right after signout
    EVENING = "22:00"         # pre-bed med pass
    OVERNIGHT = "00:00"       # midnight lab draws, IV med checks
    AM_LABS = "04:00"         # AM lab draws
    PRE_ROUNDS = "pre-rounds" # ~05:00-06:00 review / re-check
    PRN = "PRN"               # event-triggered (often paired with a contingency)
    ANYTIME = "anytime"       # no specific time — do whenever during shift


class Task(BaseModel):
    description: str = Field(description="Short imperative phrase, e.g. 'replete K if <4'.")
    when: TaskTiming = Field(
        default=TaskTiming.ANYTIME,
        description=(
            "Time bucket when the task should be performed. Pick a specific time bucket "
            "if the handoff suggests one (e.g. 'morning BMP' -> 04:00, 'NPO after midnight' "
            "-> 22:00, 'check fingerstick before bed' -> 22:00). Use 'anytime' only when "
            "there is no temporal cue at all."
        ),
    )


class Medication(BaseModel):
    name: str = Field(description="Drug name, e.g. 'furosemide' or 'ceftriaxone'.")
    dose: Optional[str] = Field(default=None, description="e.g. '80 mg', '24 units'.")
    route: Optional[str] = Field(default=None, description="e.g. 'IV', 'PO', 'subQ'.")
    frequency: Optional[str] = Field(default=None, description="e.g. 'BID', 'qHS', 'q6h'.")
    indication: Optional[str] = Field(default=None, description="Why the patient is on it, if stated.")
    notable_levels: Optional[str] = Field(
        default=None,
        description=(
            "Any notable status fact about this drug if stated. Examples: "
            "course-day notation ('day 3 of 5'), therapeutic level ('vanco trough 18'), "
            "last measured value, recent dose change ('spaced from q4h to q6h today'), "
            "or 'held' with reason."
        ),
    )


class Contingency(BaseModel):
    trigger: str = Field(description="The 'if X happens' part. Be specific and concrete.")
    action: str = Field(description="The 'then do Y' part. Include the actor if specified.")


class ConfidenceFlag(BaseModel):
    field: str = Field(description="The schema field this flag applies to, e.g. 'active_meds[0].dose'.")
    reason: str = Field(description="Why the extraction is uncertain, e.g. 'audio unclear', 'two values mentioned'.")


class Patient(BaseModel):
    identifier: str = Field(description="Short reference, e.g. 'Bed 12, 7 East' or 'Mr. Lopez'.")
    one_liner: str = Field(
        description=(
            "Age, sex, key PMH, admission diagnosis, hospital day if stated, AND a short "
            "trajectory phrase capturing the patient's current direction "
            "(e.g. 'breathing improving on IV Lasix', 'now off insulin drip, gap closed', "
            "'post-large-volume para, mental status improved'). Dense one-sentence summary."
        )
    )
    illness_severity: IllnessSeverity = Field(
        description="I-PASS severity. 'watcher' is the default when not explicitly stated and the patient is not clearly stable or unstable.",
    )
    active_issues: list[str] = Field(default_factory=list)
    day_events: list[str] = Field(
        default_factory=list,
        description=(
            "AT MOST 3 most important things that happened TODAY: clinical changes "
            "('creatinine bumped 1.6 -> 1.8'), interventions ('IV Lasix 80mg x2, 2L net "
            "negative'), procedures ('paracentesis 4L removed'), or important results "
            "('cultures growing E. coli, sensitivities pending'). Short bullet phrases. "
            "Do NOT repeat anything already captured in `one_liner` — if the one-liner says "
            "'breathing improving on IV Lasix', do not also list 'breathing improved' or "
            "'received IV Lasix' here. Pick at most the 3 most relevant remaining facts."
        ),
    )
    exam_findings: list[str] = Field(
        default_factory=list,
        description=(
            "Relevant abnormal or notable exam findings mentioned by the speaker. "
            "Only findings the speaker explicitly described. Do not infer findings "
            "from diagnosis. Do NOT repeat anything already in `one_liner` or `day_events`."
        ),
    )
    active_meds: list[Medication] = Field(default_factory=list)
    pending_results: list[str] = Field(default_factory=list, description="Labs, imaging, consult recs awaited.")
    tasks: list[Task] = Field(
        default_factory=list,
        description=(
            "Standing actions for the overnight receiver. Capture monitoring directives, "
            "explicit orders, things to avoid, results to chase, or active care. "
            "Each task gets a `when` bucket. Do NOT duplicate contingencies — those are "
            "conditional 'if X then Y' items and live in their own field."
        ),
    )
    contingencies: list[Contingency] = Field(default_factory=list)
    code_status: str = Field(description="e.g. 'full code', 'DNR/DNI', 'DNR ok to intubate'. Use 'not stated' if absent.")
    family_situation: Optional[str] = None
    confidence_flags: list[ConfidenceFlag] = Field(default_factory=list)
    completeness_gaps: list[str] = Field(
        default_factory=list,
        description=(
            "ONLY clinically significant gaps that would change overnight management. "
            "Always flag if absent: code status, contingencies/triggers, illness severity. "
            "Do NOT flag: missing hospital day, unstated medication doses (when drug names "
            "are clear), absent family situation, 'no meds mentioned'. This list prints in "
            "red on a one-pager — keep it for things the receiver needs to know are missing."
        ),
    )


class HandoffExtraction(BaseModel):
    """Top-level container. The extraction LLM call returns one of these."""
    patients: list[Patient]
```

### Why these specific fields

- **`one_liner` carries a trajectory phrase** ("breathing improving on IV Lasix") because we found that without it, the one-liner repeated facts that also appeared in `day_events` and `exam_findings`. The trajectory phrase is the headline; downstream fields fill in detail.
- **`day_events` max 3** because the card is small. Without this cap, the model would list every event of the day and overflow the box.
- **`Task.when` is an enum, not a free-text time** because we render time-bucket pills (`22:00`, `04:00`, `pre-rounds`) on the card and they need a fixed vocabulary to display cleanly.
- **`Contingency` is `trigger` + `action`, not free text** because the renderer prints them as "If TRIGGER → ACTION" and needs the two parts split.
- **`confidence_flags` and `completeness_gaps` are separate** because they answer different questions. Confidence = "I extracted this but I'm not sure I got it right." Completeness = "The speaker didn't tell me this and it matters."

---

## 7. The extraction prompt (verbatim)

`prompts/extraction.md`. This is the system prompt passed to Claude. Tool-use forces Pydantic-shaped output; this prompt shapes the *judgment* the model uses to fill the slots.

```markdown
# Handoff Extraction Prompt

You are extracting structured information from a verbal internal medicine handoff (sign-out) transcript. The transcript may cover one or more patients in sequence.

For each patient, populate the schema fields. Your output will be consumed by a downstream agent that generates anticipatory guidance for overnight care, so the *accuracy* and *uncertainty calibration* of your extraction matter more than its completeness.

## Hard rules

1. **Never invent information.** If the transcript does not state something, leave the field empty or null. Do not infer routes, doses, frequencies, or indications that were not said aloud.
2. **Surface uncertainty explicitly.** If a field was ambiguous, partially audible, or the speaker hedged, add an entry to `confidence_flags` with the field path and a short reason. Do not "clean up" ambiguity by picking the most likely value silently.
3. **Track completeness — but selectively.** `completeness_gaps` is for clinically significant absences only. ALWAYS flag if missing: `"code status not stated"`, `"no contingencies given"`, `"illness severity unclear"`. DO NOT flag: missing hospital day, missing medication doses (when drug names are clear), missing family situation, "no meds mentioned" when none are clinically expected, missing pending results. The list prints in red on a printed one-pager — reserve it for gaps that would actually change overnight management.
4. **Patient boundaries are real, even when the speaker is messy.** A voice memo often covers multiple patients in sequence and includes pivots, interruptions, and self-corrections. Handle them carefully:
   - **Pivots back.** If the speaker pivots to an earlier patient ("oh, going back to Lopez..."), attribute that content to the correct patient, not the most recent one.
   - **Self-corrections.** If the speaker corrects themselves ("actually that K+ was for Patel, not Lopez"), use the correction and drop the original.
   - **Ambiguous pronouns.** Pronouns ("she", "he") are unreliable across patients. Anchor on names, bed locations, and specific clinical context. If a statement could apply to multiple patients, add a `confidence_flag` to whichever patient you assign it to.
   - **Interruptions.** If the speaker breaks mid-thought to address something else and returns later, stitch the patient's content back together — don't fragment into separate "patients."
5. **Each fact lives in exactly one field.** The card is small. If a fact fits naturally in `one_liner`, do not repeat it in `day_events` or `exam_findings`. Priority order for the same fact: `one_liner` first, then `day_events`, then `exam_findings`. Example: "breathing improving on IV Lasix" → goes in `one_liner` (as a trajectory phrase) and NOT in `day_events` ("received IV Lasix") or `exam_findings` ("breathing improved").

## Field guidance

- `identifier`: prefer the most useful short reference for the receiver. If the speaker said both a name and a bed, combine them (e.g. `"Maria Lopez, 7 East Bed 12"`).
- `one_liner`: dense one-sentence summary — age, sex, key PMH, admission diagnosis, hospital day if stated, **plus a short trajectory phrase** capturing the patient's current direction.
- `illness_severity`: map to one of `stable`, `watcher`, `unstable`. If the speaker did not use these words explicitly, infer conservatively from clinical content but add a `confidence_flag` noting it was inferred.
- `active_meds`: include only drugs that are part of the *current* inpatient plan or being actively managed. Do not include home meds unless the speaker brought them up.
- `day_events`: **AT MOST 3** short bullets of what happened today. Phrases, not sentences. If a fact already appears in `one_liner`, **do not repeat it here**.
- `exam_findings`: notable exam findings the speaker explicitly mentioned. Do not infer findings the speaker did not state. Do NOT repeat anything already in `one_liner` or `day_events`.
- `tasks`: standing actions the receiver should perform overnight regardless of any trigger. Each task is one short imperative phrase. Do NOT put conditional `if X then Y` items here — those go in `contingencies`.
  - For each task, set `when` to the time bucket the handoff implies: `now`, `22:00`, `00:00`, `04:00`, `pre-rounds`, `PRN`, or `anytime`. Examples: "morning BMP" → `04:00`; "NPO after midnight" → `22:00`.
- `contingencies`: every conditional "if X then Y" the speaker said. Both `trigger` and `action` should be concrete enough that the receiver can act on them without re-asking.
- `code_status`: use the speaker's exact framing. If absent, use `"not stated"` and add to `completeness_gaps`.

## Output

Call the `record_handoff` tool with a single `patients` array. Do not return prose.
```

---

## 8. The extraction module

`src/extract.py`. Calls Anthropic with tool-use, caches result to disk.

**Key design choices:**

- **Tool-use, not "return JSON" in prose.** The Anthropic API gets a `tools=[...]` parameter where the tool's `input_schema` is `HandoffExtraction.model_json_schema()`. We `tool_choice={"type": "tool", "name": "record_handoff"}` to force the model to call the tool. This is dramatically more reliable than asking the model to emit JSON in a code block. The tool input is already-validated structured data; we feed it to `HandoffExtraction.model_validate(tool_use_block.input)`.

- **Disk cache keyed by hash(model + prompt + schema + transcript).** SHA256 of all four concatenated with `\x1f` separator, take first 16 hex chars. Write extraction JSON to `.cache/extractions/<key>.json`. Auto-invalidates when prompt, schema, model, or transcript changes. No manual cache-busting needed.

- **`is_cached(transcript) -> bool`** is a sibling helper so the UI can show "cached/free" vs "fresh/~$0.04" hints *before* the user clicks the button.

- **`force_fresh=True` parameter** to bypass cache without changing the transcript. Useful for prompt iteration.

- **Model: `claude-sonnet-4-5`** is the right tier — fast, cheap, clean structured output. Don't use Opus for this.

```python
EXTRACTION_MODEL = "claude-sonnet-4-5"

def _cache_key(transcript: str) -> str:
    schema_str = json.dumps(HandoffExtraction.model_json_schema(), sort_keys=True)
    prompt = _load_prompt()
    blob = f"{EXTRACTION_MODEL}\x1f{schema_str}\x1f{prompt}\x1f{transcript}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

def extract_handoff(transcript, *, client=None) -> HandoffExtraction:
    client = client or Anthropic()
    response = client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=8000,
        system=_load_prompt(),
        tools=[{
            "name": "record_handoff",
            "description": "Record the structured handoff extraction for one or more patients.",
            "input_schema": HandoffExtraction.model_json_schema(),
        }],
        tool_choice={"type": "tool", "name": "record_handoff"},
        messages=[{"role": "user", "content": transcript}],
    )
    tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use_block is None:
        raise ValueError("Extraction model did not call the record_handoff tool.")
    return HandoffExtraction.model_validate(tool_use_block.input)
```

`load_dotenv()` is called at module import so the Anthropic SDK finds `ANTHROPIC_API_KEY` in `os.environ`.

---

## 9. The transcription module

`src/transcribe.py`. Wraps faster-whisper for local CPU inference.

**Why faster-whisper, not openai-whisper:** ~4x faster on CPU via CTranslate2 and skips the ffmpeg install pain on Windows.

**Key trick: `HANDOFF_INITIAL_PROMPT`.** Whisper accepts an `initial_prompt` that biases the decoder toward specific vocabulary without retraining. Without it, "furosemide" becomes "for a samide" and "Lasix" becomes "lay six." With it, drug/lab/location names come through cleanly. The prompt string isn't itself transcribed; it just nudges token probabilities.

```python
HANDOFF_INITIAL_PROMPT = (
    "Internal medicine handoff. Drugs: furosemide, Lasix, lisinopril, carvedilol, "
    "prednisone, azithromycin, ceftriaxone, doxycycline, vancomycin, heparin, "
    "apixaban, pantoprazole, metoprolol, atorvastatin, aspirin, spironolactone, "
    "hydrochlorothiazide, losartan, cefazolin, lactulose, insulin, glargine, "
    "lispro, albuterol, duonebs. Labs: BMP, CBC, troponin, BNP, lactate, "
    "hemoglobin, creatinine, potassium, sodium, magnesium, glucose, INR, lactate, "
    "procalcitonin. Locations: bed, east, west, north, south, stepdown, telemetry. "
    "Vitals: heart rate, blood pressure, oxygen saturation, respiratory rate."
)

DEFAULT_MODEL_SIZE = "small"  # ~470MB; right balance for clean voice memos

def _get_model(model_size):
    # int8 quantization on CPU: ~half memory, ~2x speed, negligible accuracy loss.
    return WhisperModel(model_size, device="cpu", compute_type="int8")

def transcribe(audio_path, *, model_size=DEFAULT_MODEL_SIZE) -> str:
    model = _get_model(model_size)
    segments, _ = model.transcribe(
        str(audio_path),
        vad_filter=True,                      # drops long silences
        initial_prompt=HANDOFF_INITIAL_PROMPT, # biases toward medical vocab
    )
    return " ".join(seg.text.strip() for seg in segments)
```

Module-level dict cache (`_MODEL_CACHE`) so repeated calls in one process don't re-load the model.

---

## 10. The render module

`src/render.py`. **No LLM here.** Deterministic Python that walks `HandoffExtraction` and string-interpolates the HTML template.

```python
TIMING_ORDER = {
    TaskTiming.NOW: 0, TaskTiming.EVENING: 1, TaskTiming.OVERNIGHT: 2,
    TaskTiming.AM_LABS: 3, TaskTiming.PRE_ROUNDS: 4, TaskTiming.PRN: 5,
    TaskTiming.ANYTIME: 6,
}
CARDS_PER_SHEET = 6
```

**Card layout** (per patient):
- Header: `identifier` + severity badge (`stable` / `watcher` / `unstable`, styled CSS class)
- One-liner (italic, muted color)
- "Today" section: bulleted `day_events`
- "Exam" inline section: semicolon-joined `exam_findings`
- "Tasks" section: bulleted, each task prefixed with checkbox glyph (☐) and time-bucket pill (e.g. `22:00`). Sorted by `TIMING_ORDER`. `anytime` items have no pill.
- "If/Then" section: contingencies rendered as `If TRIGGER → ACTION`
- Red callout: `completeness_gaps` rendered as `Missing: X; Y; Z` (only if non-empty)
- Footer: meds (semicolon-joined, with notable_levels italicized in parens), pending results, code status

**HTML escaping:** every string from the extraction is run through `html.escape()` before insertion. Use a `_esc()` helper that also handles `None → ""`.

**Padding:** if `len(patients) < 6`, append `<div class="card blank"></div>` placeholders so the 2×3 grid stays visually intact.

**Template substitution:** `prompts/one_pager.html` contains a `{{CARDS}}` sentinel. `render_sheet()` reads the template, joins card HTMLs with newlines, and does a single `.replace("{{CARDS}}", cards_html)`. No Jinja or other engine.

---

## 11. The HTML/CSS template (verbatim)

`prompts/one_pager.html`. Print-first. Use the file as-is.

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Handoff One-Pager</title>
<style>
  @page { size: letter; margin: 0.25in; }

  :root {
    --ink: #000; --muted: #444; --rule: #888;
    --severity-bg: #eee; --when-bg: #222; --when-fg: #fff;
  }
  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0;
    font-family: "Helvetica Neue", Arial, sans-serif;
    color: var(--ink); font-size: 8pt; line-height: 1.22;
  }

  .sheet {
    width: 8in; height: 10.5in;
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: repeat(3, 1fr);
    gap: 0.1in;
  }

  .card { border: 0.6pt solid var(--ink); padding: 0.1in 0.12in;
          overflow: hidden; display: flex; flex-direction: column; }
  .card.blank { border: 0.6pt dashed #ccc; }

  .card-header {
    display: flex; justify-content: space-between; align-items: baseline;
    border-bottom: 0.5pt solid var(--rule);
    padding-bottom: 2pt; margin-bottom: 3pt;
  }
  .ident { font-weight: 700; font-size: 10pt; }   /* Name/location stays at 10pt */
  .severity {
    font-size: 7pt; text-transform: uppercase; letter-spacing: 0.5pt;
    background: var(--severity-bg); padding: 1pt 4pt; border: 0.5pt solid var(--rule);
  }
  .severity.unstable { background: #000; color: #fff; }
  .severity.watcher  { background: #ddd; }
  .severity.stable   { background: #fff; }

  .oneliner { font-style: italic; color: var(--muted); margin-bottom: 3pt; }
  .section { margin-bottom: 3pt; }
  .section-label, .section-label-inline {
    font-weight: 700; font-size: 7pt; text-transform: uppercase;
    letter-spacing: 0.4pt; color: var(--muted);
  }
  .exam { font-size: 7.5pt; }

  ul { margin: 0; padding-left: 0; list-style: none; }
  .bullets li::before { content: "• "; color: var(--muted); }
  .tasks li { margin-bottom: 1pt; }
  .tasks li::before { content: "☐ "; color: var(--ink); }

  .when {
    display: inline-block;
    background: var(--when-bg); color: var(--when-fg);
    font-size: 6.5pt; font-weight: 700;
    padding: 0.5pt 3pt; margin-right: 3pt;
    border-radius: 1.5pt; vertical-align: 1pt; letter-spacing: 0.3pt;
  }

  .conts li { margin-bottom: 1pt; }
  .conts .trig { font-weight: 700; }
  .conts .arrow { margin: 0 2pt; }

  .footer {
    margin-top: auto; font-size: 7pt; color: var(--muted);
    border-top: 0.5pt dotted var(--rule); padding-top: 2pt;
    display: flex; flex-direction: column; gap: 1pt;
  }
  .footer .label {
    font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.3pt; color: var(--ink);
  }
  .gaps { font-size: 7pt; color: #b00; margin-top: 2pt; }
</style>
</head>
<body>
<div class="sheet">
{{CARDS}}
</div>
</body>
</html>
```

---

## 12. The pipeline module

`src/pipeline.py`. Thin orchestrator so business logic lives in one place.

```python
def process_text(transcript: str) -> tuple[HandoffExtraction, str]:
    extraction = extract_handoff_cached(transcript)
    html_out = render_sheet(extraction)
    return extraction, html_out

def process_audio(audio_path, *, model_size="small") -> tuple[str, HandoffExtraction, str]:
    from .transcribe import transcribe  # lazy: avoid ctranslate2 import for text-only callers
    transcript = transcribe(audio_path, model_size=model_size)
    extraction, html_out = process_text(transcript)
    return transcript, extraction, html_out
```

The lazy import is important: `faster-whisper` pulls in `ctranslate2`, which is heavy. Text-only callers shouldn't pay that cost.

---

## 13. The Streamlit app

`app.py`. Presentation only — no business logic.

### Page-level setup

```python
st.set_page_config(page_title="Sub-I Handoff Co-Pilot", page_icon=":clipboard:", layout="wide")
```

Display a **synthetic-data-only warning** as a permanent `st.warning(...)` banner at the top. This is non-negotiable since the app sends transcripts to Anthropic.

### Secrets bridge (gotcha — read this carefully)

Streamlit Cloud puts secrets in `st.secrets`; local dev reads `.env` via `load_dotenv()` inside `extract.py`. We need both to populate `os.environ["ANTHROPIC_API_KEY"]` so the Anthropic SDK finds it.

**Bug to avoid:** `if "ANTHROPIC_API_KEY" in st.secrets:` triggers Streamlit to parse `secrets.toml`, which doesn't exist locally and raises `StreamlitSecretNotFoundError`. The `in` operator alone triggers it. Wrap the whole check in `try/except`:

```python
try:
    if "ANTHROPIC_API_KEY" in st.secrets:
        os.environ.setdefault("ANTHROPIC_API_KEY", st.secrets["ANTHROPIC_API_KEY"])
except Exception:
    # No secrets.toml — fine, we'll rely on .env via load_dotenv() in extract.py
    pass
```

### Session state

```python
defaults = {
    "transcript": "",
    "extraction": None,
    "html_out": None,
    "last_extraction_ms": None,
    "last_cache_hit": None,
}
```

Always reset `extraction` and `html_out` to `None` when the transcript changes — otherwise stale renders persist.

### Sidebar

- Whisper model size selectbox (`tiny` / `base` / `small` / `medium`, default `small`).
- "Start over" button — wipes session_state and `st.rerun()`s.
- Cost notes: transcription free (local), extraction ~$0.04/patient, re-extraction cached free.

### Cached Whisper loader

```python
@st.cache_resource(show_spinner=False)
def _prime_whisper(model_size: str):
    from src.transcribe import _get_model
    return _get_model(model_size)
```

`@st.cache_resource` persists across Streamlit reruns within a session. Without it, you re-load the Whisper model on every interaction.

### Step 1: input — 4 tabs

```python
tab_upload, tab_record, tab_paste, tab_demo = st.tabs(
    ["Upload audio", "Record audio", "Paste text", "Demo (no API call)"]
)
```

- **Upload audio**: `st.file_uploader(type=["m4a","mp3","wav","ogg","mp4"])`, then save to temp file, transcribe.
- **Record audio**: `st.audio_input(...)` (built-in browser recorder), same path.
- **Paste text**: `st.text_area(...)`. When the text changes, write it to `st.session_state.transcript` and invalidate `extraction` + `html_out`.
- **Demo (no API call)**: shows hard-coded transcript in a disabled `st.text_area`, button "Run demo extraction" sets `transcript`, builds `HandoffExtraction` from `demo_data.build_demo_extraction()`, renders, fakes metadata (`last_extraction_ms=0`, `last_cache_hit=True`), then `st.rerun()`.

### Step 2: review transcript

Shown only if `st.session_state.transcript` is truthy. Editable `text_area` bound to session state. Caption nudges the user to fix Whisper errors (drug names, lab values, ambiguous numbers like "125 — sodium or time of day?") **before** extracting.

Two buttons:
1. **"Extract + Render (cached — free)"** or **"(fresh — ~$0.04/patient)"** — label changes based on `is_cached(transcript)`. Primary action.
2. **"Re-extract (force fresh API call)"** — bypasses cache. Useful when iterating on the prompt.

Both buttons call `extract_handoff_cached(transcript, force_fresh=...)`, then `render_sheet(extraction)`, then store everything in session state along with elapsed ms and cache-hit-before flag.

### Step 3: one-pager output

Shown only if both `extraction` and `html_out` are populated. Three metric tiles (`st.columns(3)` + `st.metric`):
- Patients extracted
- Latency (ms)
- Source ("cache hit" or "fresh extraction")

Then `st.components.v1.html(html_out, height=1100, scrolling=True)` for inline preview.

Two download buttons side by side: HTML one-pager, raw extraction JSON (`extraction.model_dump_json(indent=2)`).

### Step 4: edit cards

Per-patient expanders. For each `Patient`:

- `st.text_input` for `identifier`, `code_status`
- `st.text_area` for `one_liner`, plus three multi-line areas where the user edits `day_events`, `exam_findings`, `pending_results` as newline-separated lists
- `st.data_editor` (num_rows="dynamic") for tasks with two columns: `when` (SelectboxColumn over `TaskTiming` values) and `description` (TextColumn)
- `st.data_editor` for contingencies with `trigger` and `action` columns

After all expanders, "Apply edits + re-render" button rebuilds `HandoffExtraction` from the edited fields, calls `render_sheet`, and `st.rerun()`s. **No new API call** — this is the value of having the extraction as a pure data structure.

Some fields (active_meds, illness_severity, confidence_flags, completeness_gaps) are not exposed for editing — they pass through unchanged. Keep it simple; users who want to edit those can edit the JSON.

### The demo tab in detail

`src/demo_data.py`:
- Exports a `DEMO_TRANSCRIPT` string (full 3-patient verbal handoff — see `data/synthetic_handoffs/demo_3patient.txt` or hardcode).
- Exports `build_demo_extraction() -> HandoffExtraction` that returns a hand-built extraction matching the transcript. Build fresh on each call so callers can't mutate a shared object.

The demo tab loads these instantly. Downstream UI (steps 2-4) is **identical** to a real run — it reads from the same session_state, so the rendered one-pager, downloads, and edit cards all work the same way. Audience sees the full polished flow with zero latency, zero API cost.

---

## 14. Streamlit Cloud deployment

### What Streamlit Cloud expects

- Public GitHub repo
- `requirements.txt` at repo root (NOT just `pyproject.toml` — see gotcha below)
- `app.py` at repo root
- Secrets pasted into the Streamlit Cloud UI as TOML

### requirements.txt

Streamlit Cloud uses Poetry as a fallback installer when it sees a `pyproject.toml`. Our `pyproject.toml` uses setuptools, with the package name `sub-i-copilot` (hyphens) but code in `src/` — Poetry can't reconcile this and the build fails with `No file/folder found for package sub-i-copilot`.

Fix: ship a `requirements.txt`. Streamlit Cloud prefers it and skips the project-install dance. Both files coexist:
- `pyproject.toml` — local dev (`pip install -e .` makes `from src.extract import ...` work)
- `requirements.txt` — Streamlit Cloud deployment

```
anthropic>=0.40.0
pydantic>=2.0
python-dotenv>=1.0
faster-whisper>=1.0
streamlit>=1.30
```

### Secrets

In Streamlit Cloud → Advanced Settings → Secrets, paste:

```toml
ANTHROPIC_API_KEY = "sk-ant-..."
```

The secrets-bridge code in `app.py` (see §13) reads this and writes it to `os.environ` so the Anthropic SDK finds it.

### .gitignore (critical — don't leak secrets)

```
# Secrets — NEVER commit these
.env
.env.local
.streamlit/secrets.toml

# Local caches and generated outputs
.cache/
outputs/

# Python
__pycache__/
*.pyc
*.pyo
*.egg-info/
.pytest_cache/

# Virtual environments
.venv/
venv/
env/

# Editor / OS noise
.vscode/
.idea/
.DS_Store
Thumbs.db
```

### Deployment dance

1. `git init` → commit `.gitignore` first and alone (so subsequent `git add .` doesn't pull in `.env`).
2. Verify `.env` is not staged, then `git add . && git commit`.
3. Create **public** GitHub repo under personal account (NOT under any org). Push.
4. Streamlit Cloud → New app → connect repo → set secrets → deploy.
5. First build takes 3-5 min because `faster-whisper` pulls in `ctranslate2` + PyTorch.
6. Iterate: `git push` → Streamlit Cloud auto-redeploys in ~30s.

---

## 15. Known gotchas (real bugs we hit — preserve these notes)

1. **`StreamlitSecretNotFoundError` on local run.** Already covered in §13. Wrap `st.secrets` access in `try/except`.

2. **Streamlit Cloud "No file/folder found for package".** Already covered in §14. Ship `requirements.txt`.

3. **`from .schema import` fails with `attempted relative import in non-package`.** `src/` needs an `__init__.py` (can be empty) to be a package.

4. **Anthropic SDK doesn't find the API key.** `load_dotenv()` must run *before* `Anthropic()` is constructed. Call it at module top of `extract.py`.

5. **Cache returns stale extraction after prompt edit.** It won't — the cache key includes the prompt content, so changes auto-invalidate. If it appears stale, the prompt file wasn't actually edited.

6. **Whisper mangles drug names.** Solved by `HANDOFF_INITIAL_PROMPT`. Without it, "furosemide" → "for a samide."

7. **Numbers are ambiguous in Whisper output.** "125" could be a sodium or a time of day. Not solved at ASR level — the app caption tells the user to fix typos in the transcript review step before extracting.

8. **Card overflow.** Body font is 8pt and `day_events` is capped at 3 specifically to keep cards from overflowing. Don't loosen these without checking print output.

9. **"Missing X" noise in red.** Earlier `completeness_gaps` flagged every absent field. Tightened in the schema description AND the prompt to only flag clinically significant gaps. Both edits are necessary — Pydantic field descriptions get used by the model via tool-use.

10. **Pasted API key in chat.** If a user pastes their key, treat it as leaked. Walk through key rotation immediately. Never use the value.

---

## 16. Recommended build order

If you're starting from scratch:

1. **Schema** (`src/schema.py`) — get the data contract right first. Run `python -c "from src.schema import HandoffExtraction; print(HandoffExtraction.model_json_schema())"` to verify it produces clean JSON Schema for tool-use.
2. **Extraction prompt** (`prompts/extraction.md`).
3. **Extract module** (`src/extract.py`) — write it without caching first, get one successful run against a synthetic handoff, then add the disk cache.
4. **HTML template + render module** (`prompts/one_pager.html`, `src/render.py`) — keep it LLM-free. Verify it renders a 6-card grid correctly with `data/synthetic_handoffs/01_*.txt` through `06_*.txt`.
5. **Transcribe module** (`src/transcribe.py`) — wrap faster-whisper with the initial prompt trick.
6. **Pipeline** (`src/pipeline.py`) — thin glue.
7. **Streamlit app** (`app.py`) — Upload, Record, Paste tabs first; add Demo tab last.
8. **Demo data** (`src/demo_data.py`) — for offline showcasing.
9. **Deployment** — `requirements.txt`, `.gitignore`, push, deploy.

At each step, hold to the verbatim-first stance and the one-LLM-call constraint. The temptation to add a second LLM call ("generate watch-outs," "summarize," "rewrite to be more concise") will be strong. Resist it. Every additional LLM call is a new hallucination surface.

---

## 17. What this spec deliberately leaves out

- **Eval loop.** A precision/recall-per-field evaluation harness using an LLM judge is planned but not yet built. Out of scope here.
- **WeasyPrint / direct PDF export.** Was considered, deferred indefinitely. Browser print-to-PDF is good enough.
- **Multi-user auth.** Not in scope. One user, one app.
- **EHR / clinical-database integration.** Not in scope. Synthetic only.
- **Long-term storage of past handoffs.** Out of scope. Sheet is single-use, discarded after the shift.

If you find yourself wanting any of these, you're solving a different problem than this app solves.
