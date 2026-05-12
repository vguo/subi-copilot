"""Streamlit webapp for the sub-i handoff co-pilot.

Run locally:
    streamlit run app.py

Flow:
    1. Provide input (upload audio, record in browser, or paste text)
    2. Review/edit transcript
    3. Extract structured handoff data
    4. Preview the one-pager + edit individual fields + download

This file is presentation only. All business logic lives in src/pipeline.py
and the modules it orchestrates.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import streamlit as st

# Streamlit Cloud puts secrets in st.secrets; locally we read .env (via
# load_dotenv inside extract.py). Bridge cloud secrets into os.environ so
# the Anthropic SDK picks them up the same way locally and remotely.
# NOTE: accessing st.secrets parses a secrets.toml file. When that file
# doesn't exist (the normal local case), Streamlit raises
# StreamlitSecretNotFoundError on *any* access — including `in`. Wrap in
# try/except so the absence of secrets is silent locally.
try:
    if "ANTHROPIC_API_KEY" in st.secrets:
        os.environ.setdefault("ANTHROPIC_API_KEY", st.secrets["ANTHROPIC_API_KEY"])
except Exception:
    # No secrets.toml — fine, we'll rely on .env via load_dotenv() in extract.py
    pass

from src.extract import extract_handoff_cached, is_cached
from src.render import render_sheet
from src.schema import HandoffExtraction, Patient, Task, TaskTiming, Contingency
from src.transcribe import DEFAULT_MODEL_SIZE, transcribe

# --- Page setup ---

st.set_page_config(
    page_title="Sub-I Handoff Co-Pilot",
    page_icon=":clipboard:",
    layout="wide",
)
st.title("Sub-I Handoff Co-Pilot")
st.caption(
    "Voice memo or pasted transcript → structured one-pager. "
    "Designed for synthetic / training data only — see banner below."
)

# Hard-coded banner: this app sends transcript text to Anthropic. No PHI.
st.warning(
    "**Synthetic data only.** This tool sends transcripts to the Anthropic API. "
    "Do not upload audio or paste text containing real patient identifiers or PHI.",
    icon=":material/warning:",
)

# --- Session state init ---

def _init_state():
    """Set defaults so reading session_state.x is always safe."""
    defaults = {
        "transcript": "",
        "extraction": None,
        "html_out": None,
        "last_extraction_ms": None,
        "last_cache_hit": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _reset_state():
    """Wipe everything — used by the "Start over" sidebar button."""
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    _init_state()


_init_state()

# --- Sidebar: settings + controls ---

with st.sidebar:
    st.header("Settings")
    model_size = st.selectbox(
        "Whisper model size",
        options=["tiny", "base", "small", "medium"],
        index=2,
        help=(
            "Larger = more accurate, slower. 'small' is fine for clean voice memos. "
            "'medium' is worth it for messy real-shift audio at the cost of ~3x runtime."
        ),
    )
    st.markdown("---")
    st.header("Session")
    if st.button("Start over", use_container_width=True):
        _reset_state()
        st.rerun()
    st.markdown("---")
    st.markdown(
        "**Cost notes:**\n"
        "- Transcription: local, free.\n"
        "- Extraction: ~$0.04/patient via Claude API.\n"
        "- Re-extracting the same transcript: cached on disk, free."
    )

# --- Cached model loader ---

@st.cache_resource(show_spinner=False)
def _prime_whisper(model_size: str):
    """Cache the Whisper model across Streamlit reruns within a session."""
    from src.transcribe import _get_model
    return _get_model(model_size)


# --- Step 1: Input ---

st.subheader("1. Provide input")

tab_upload, tab_record, tab_paste = st.tabs(
    ["Upload audio", "Record audio", "Paste text"]
)

with tab_upload:
    uploaded = st.file_uploader(
        "Upload .m4a / .mp3 / .wav / .ogg / .mp4",
        type=["m4a", "mp3", "wav", "ogg", "mp4"],
        key="upload_audio",
    )
    if uploaded is not None and st.button("Transcribe upload", type="primary"):
        try:
            with st.spinner("Transcribing (first run downloads the Whisper model)..."):
                suffix = Path(uploaded.name).suffix or ".m4a"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(uploaded.read())
                    tmp_path = tmp.name
                _prime_whisper(model_size)
                st.session_state.transcript = transcribe(tmp_path, model_size=model_size)
                # Invalidate downstream state
                st.session_state.extraction = None
                st.session_state.html_out = None
            st.success("Transcription complete. Review below.")
        except Exception as e:  # noqa: BLE001
            st.error(f"Transcription failed: {type(e).__name__}: {e}")

with tab_record:
    recorded = st.audio_input("Record handoff directly in browser")
    if recorded is not None and st.button("Transcribe recording", type="primary"):
        try:
            with st.spinner("Transcribing..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                    tmp.write(recorded.read())
                    tmp_path = tmp.name
                _prime_whisper(model_size)
                st.session_state.transcript = transcribe(tmp_path, model_size=model_size)
                st.session_state.extraction = None
                st.session_state.html_out = None
            st.success("Transcription complete. Review below.")
        except Exception as e:  # noqa: BLE001
            st.error(f"Transcription failed: {type(e).__name__}: {e}")

with tab_paste:
    pasted = st.text_area(
        "Paste handoff transcript:",
        height=200,
        key="paste_box",
        placeholder="Maria Lopez is a 67-year-old woman...",
    )
    if pasted and pasted.strip() and pasted != st.session_state.transcript:
        st.session_state.transcript = pasted
        st.session_state.extraction = None
        st.session_state.html_out = None

# --- Step 2: Review transcript ---

if st.session_state.transcript:
    st.markdown("---")
    st.subheader("2. Review transcript")
    st.caption(
        "Fix typos in drug names, lab values, or numbers before extracting. "
        "Whisper often confuses numbers (125 could be a sodium or a time of day) "
        "and mangles drug names — corrections here are free; mis-extraction is not."
    )
    st.session_state.transcript = st.text_area(
        "Transcript",
        value=st.session_state.transcript,
        height=220,
        key="review_box",
        label_visibility="collapsed",
    )

    col_a, col_b = st.columns([1, 1])
    with col_a:
        cached_hint = "(cached — free)" if is_cached(st.session_state.transcript) else "(fresh — ~$0.04/patient)"
        extract_clicked = st.button(
            f"Extract + Render {cached_hint}",
            type="primary",
            use_container_width=True,
        )
    with col_b:
        force_fresh = st.button(
            "Re-extract (force fresh API call)",
            use_container_width=True,
            help="Bypass the cache. Useful if you just changed the prompt or want to retry.",
        )

    if extract_clicked or force_fresh:
        try:
            with st.spinner("Calling Claude for extraction..."):
                t_start = time.perf_counter()
                cache_hit_before = is_cached(st.session_state.transcript) and not force_fresh
                extraction = extract_handoff_cached(
                    st.session_state.transcript, force_fresh=force_fresh
                )
                elapsed_ms = int((time.perf_counter() - t_start) * 1000)
                st.session_state.extraction = extraction
                st.session_state.html_out = render_sheet(extraction)
                st.session_state.last_extraction_ms = elapsed_ms
                st.session_state.last_cache_hit = cache_hit_before
        except Exception as e:  # noqa: BLE001
            st.error(f"Extraction failed: {type(e).__name__}: {e}")
            st.exception(e)

# --- Step 3: Output + edit ---

if st.session_state.extraction is not None and st.session_state.html_out is not None:
    st.markdown("---")
    st.subheader("3. One-pager")

    # Metadata strip
    extraction: HandoffExtraction = st.session_state.extraction
    n_pat = len(extraction.patients)
    elapsed = st.session_state.last_extraction_ms or 0
    cache_lbl = "cache hit" if st.session_state.last_cache_hit else "fresh extraction"
    meta_cols = st.columns(3)
    meta_cols[0].metric("Patients extracted", n_pat)
    meta_cols[1].metric("Latency", f"{elapsed} ms")
    meta_cols[2].metric("Source", cache_lbl)

    # Render preview
    st.components.v1.html(st.session_state.html_out, height=1100, scrolling=True)

    # Downloads
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        st.download_button(
            "Download HTML one-pager",
            data=st.session_state.html_out,
            file_name="one_pager.html",
            mime="text/html",
            use_container_width=True,
        )
    with col_d2:
        st.download_button(
            "Download raw extraction JSON",
            data=extraction.model_dump_json(indent=2),
            file_name="extraction.json",
            mime="application/json",
            use_container_width=True,
        )

    # --- Edit-after-extraction ---
    # When the model gets a card wrong, you can fix it here without re-running
    # extraction. Each patient is an expander; common-mistake fields are editable.
    st.markdown("---")
    st.subheader("4. Edit individual cards (optional)")
    st.caption(
        "Use this when the model misattributed a fact, mistyped a drug, or you "
        "want to add something. Click 'Apply edits + re-render' to rebuild the "
        "one-pager. No new API call."
    )

    edited_patients: list[Patient] = []
    for i, p in enumerate(extraction.patients):
        with st.expander(f"{p.identifier} — edit"):
            new_identifier = st.text_input("Identifier", value=p.identifier, key=f"ident_{i}")
            new_one_liner = st.text_area("One-liner", value=p.one_liner, key=f"ol_{i}", height=70)
            new_code = st.text_input("Code status", value=p.code_status, key=f"code_{i}")

            new_day_events = st.text_area(
                "Day events (one per line, max 3)",
                value="\n".join(p.day_events),
                key=f"days_{i}",
                height=100,
            )
            new_exam = st.text_area(
                "Exam findings (one per line)",
                value="\n".join(p.exam_findings),
                key=f"exam_{i}",
                height=80,
            )
            new_pending = st.text_area(
                "Pending results (one per line)",
                value="\n".join(p.pending_results),
                key=f"pend_{i}",
                height=80,
            )

            st.markdown("**Tasks** (timing dropdown + description)")
            tasks_df = [
                {"when": t.when.value, "description": t.description} for t in p.tasks
            ]
            edited_tasks = st.data_editor(
                tasks_df,
                num_rows="dynamic",
                key=f"tasks_{i}",
                column_config={
                    "when": st.column_config.SelectboxColumn(
                        "when",
                        options=[v.value for v in TaskTiming],
                        required=True,
                    ),
                    "description": st.column_config.TextColumn(
                        "description", required=True
                    ),
                },
                use_container_width=True,
            )

            st.markdown("**Contingencies** (if/then)")
            cont_df = [
                {"trigger": c.trigger, "action": c.action} for c in p.contingencies
            ]
            edited_conts = st.data_editor(
                cont_df,
                num_rows="dynamic",
                key=f"conts_{i}",
                column_config={
                    "trigger": st.column_config.TextColumn("if (trigger)", required=True),
                    "action": st.column_config.TextColumn("then (action)", required=True),
                },
                use_container_width=True,
            )

            # Rebuild patient from edits. Meds + confidence_flags + completeness_gaps
            # are not exposed for editing — they pass through unchanged.
            edited_p = Patient(
                identifier=new_identifier,
                one_liner=new_one_liner,
                illness_severity=p.illness_severity,
                active_issues=p.active_issues,
                day_events=[s for s in new_day_events.split("\n") if s.strip()],
                exam_findings=[s for s in new_exam.split("\n") if s.strip()],
                active_meds=p.active_meds,
                pending_results=[s for s in new_pending.split("\n") if s.strip()],
                tasks=[
                    Task(
                        description=row["description"],
                        when=TaskTiming(row["when"]),
                    )
                    for row in edited_tasks
                    if row.get("description")
                ],
                contingencies=[
                    Contingency(trigger=row["trigger"], action=row["action"])
                    for row in edited_conts
                    if row.get("trigger") and row.get("action")
                ],
                code_status=new_code,
                family_situation=p.family_situation,
                confidence_flags=p.confidence_flags,
                completeness_gaps=p.completeness_gaps,
            )
            edited_patients.append(edited_p)

    if st.button("Apply edits + re-render", type="primary"):
        new_extraction = HandoffExtraction(patients=edited_patients)
        st.session_state.extraction = new_extraction
        st.session_state.html_out = render_sheet(new_extraction)
        st.rerun()

    with st.expander("Show raw extraction JSON"):
        st.json(extraction.model_dump(mode="json"))
