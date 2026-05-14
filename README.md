# Handoff Copilot

*Repo name: `sub-i-copilot`. The product is **Handoff Copilot**.*

Personal handoff processing tool. Input: a voice memo of a verbal sign-out. Output: a printable one-page reference sheet plus a phone-friendly shift checklist.

See `sub_i_copilot_plan.md` for the original design rationale and scope.

## Status

End-to-end MVP working locally: audio → transcript → extraction → printable one-pager, served by a Streamlit webapp. Eval loop is the remaining phase.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
copy .env.example .env  # then open .env and paste your Anthropic API key
```

## Try it

Sanity-check the schema without making an API call:

```powershell
python evals/schema_sanity_check.py
```

Run a real extraction against the COPD example:

```powershell
python -m src.extract data/synthetic_handoffs/01_copd_lopez.txt
```

Render a one-pager from one or more transcripts (writes `outputs/one_pager.html`):

```powershell
python -m src.render data/synthetic_handoffs/01_copd_lopez.txt data/synthetic_handoffs/02_hf_patel.txt
start outputs\one_pager.html
```

Launch the local webapp (upload audio, record in browser, paste text, or run the demo, then view + download one-pager):

```powershell
streamlit run app.py
```

The app exposes four input tabs (Upload / Record / Paste / Demo) and three output views (Print sheet / Shift mode / Timeline). Demo loads a pre-computed extraction so the app can be showcased without burning an API call.

**LLM provider toggle.** The sidebar lets you switch between Claude Sonnet (paid, ~$0.04/patient) and Gemini 1.5 Flash (free via Google AI Studio). Cache is keyed by provider, so the two cache independently — switching back and forth costs nothing on a re-run. Set `ANTHROPIC_API_KEY` and/or `GEMINI_API_KEY` in `.env` depending on which you use. Synthetic data only either way.

## Deploy

See [`DEPLOY.md`](DEPLOY.md) for end-to-end Streamlit Cloud deployment. Synthetic data only.

## Rebuild from scratch

See [`BUILD_SPEC.md`](BUILD_SPEC.md) for a self-contained rebuild specification — schema, prompts, render template, deployment notes, and the gotchas we hit along the way. Aimed at handing the project to another LLM and getting back a working implementation.

## Build order

1. [x] Schema + extraction (text → `HandoffExtraction`)
2. [x] Gold watch-outs for all 10 synthetic handoffs (`data/gold_watchouts/gold_watchouts.md`)
3. [x] *(Collapsed)* Watch-outs now produced by extraction (`tasks` + `contingencies`), no separate LLM call
4. [x] *(Collapsed)* Time-bucketing handled inline by `Task.when` enum
5. [x] HTML rendering of the one-pager (browser → Save as PDF; WeasyPrint deferred)
6. [x] Whisper ASR wrapper (`src/transcribe.py`, local faster-whisper)
7. [ ] Eval loop: precision, recall, hallucination per patient
8. [x] Streamlit webapp (`app.py`) with Upload / Record / Paste / Demo input tabs
9. [x] Streamlit Cloud deployment (`requirements.txt`, secrets bridge — see `DEPLOY.md`)
10. [x] Shift mode + Timeline output tabs (per-patient checklist, cross-patient time view; shared checkbox state)
11. [x] Pluggable LLM provider — Claude (paid) or Gemini Flash (free via AI Studio); cache independently namespaced per provider

## Layout

```
app.py              Streamlit webapp: audio/text -> one-pager (+ Shift mode, Timeline)
requirements.txt    Dependency list for Streamlit Cloud deployment
pyproject.toml      Local dev install (pip install -e .)
src/
  schema.py         Pydantic models for the I-PASS-shaped extraction
  extract.py        Transcript -> HandoffExtraction via tool-use (with disk cache)
  transcribe.py     Audio -> text via local faster-whisper
  pipeline.py       Orchestrator: audio/text -> extraction -> HTML
  render.py         HandoffExtraction -> printable HTML one-pager
  demo_data.py      Hard-coded demo transcript + extraction for the Demo tab
prompts/
  extraction.md     System prompt for extraction
  one_pager.html    HTML/CSS template for the one-pager (2x3 card grid)
data/
  synthetic_handoffs/   Fictional handoffs only — no PHI ever
  gold_watchouts/       Hand-written gold standard
evals/
  schema_sanity_check.py
  extraction_notes.md   Running log of extraction observations for Phase 7
outputs/
  one_pager.html (regenerated on each render)
.cache/
  extractions/      Disk cache for extraction calls, keyed by prompt+schema+transcript
README.md
DEPLOY.md           Streamlit Cloud deployment walkthrough
BUILD_SPEC.md       Self-contained rebuild spec for handing to another LLM
```
