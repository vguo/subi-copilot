# sub-i-copilot

Personal handoff processing tool. Input: a voice memo of a verbal sign-out. Output: a printable one-page reference sheet.

See `sub_i_copilot_plan.md` for design rationale and scope.

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

Launch the local webapp (upload audio, record in browser, or paste text, view + download one-pager):

```powershell
streamlit run app.py
```

## Deploy

See [`DEPLOY.md`](DEPLOY.md) for end-to-end Streamlit Cloud deployment. Synthetic data only.

## Build order

1. [x] Schema + extraction (text → `HandoffExtraction`)
2. [x] Gold watch-outs for all 10 synthetic handoffs (`data/gold_watchouts/gold_watchouts.md`)
3. [x] *(Collapsed)* Watch-outs now produced by extraction (`tasks` + `contingencies`), no separate LLM call
4. [x] *(Collapsed)* Time-bucketing handled inline by `Task.when` enum
5. [x] HTML rendering of the one-pager (browser → Save as PDF; WeasyPrint deferred)
6. [x] Whisper ASR wrapper (`src/transcribe.py`, local faster-whisper)
7. [ ] Eval loop: precision, recall, hallucination per patient
8. [x] Streamlit webapp (`app.py`) — local for now, deploy "eventually"

## Layout

```
app.py              Streamlit webapp: audio/text -> one-pager
src/
  schema.py         Pydantic models for the I-PASS-shaped extraction
  extract.py        Transcript -> HandoffExtraction via tool-use (with disk cache)
  transcribe.py     Audio -> text via local faster-whisper
  pipeline.py       Orchestrator: audio/text -> extraction -> HTML
  render.py         HandoffExtraction -> printable HTML one-pager
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
```
