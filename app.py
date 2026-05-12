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

import hashlib
import os
import tempfile
import time
from collections import defaultdict
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

from src.demo_data import DEMO_TRANSCRIPT, build_demo_extraction
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


# --- View helpers for Shift mode + Timeline tabs ---
# These render Streamlit-native interactive views (with checkable tasks)
# alongside the existing print-sheet HTML preview. Keeping them here (vs in
# render.py) is deliberate: render.py is the deterministic HTML pipeline,
# while these helpers are tightly coupled to st.session_state for checkbox
# persistence and have no print-target equivalent.

# Display labels + ordering for the time buckets. Mirrors render.TIMING_ORDER
# but with longer human-readable labels for screen views (the printed card
# uses compact pills like "22:00").
_TIMING_DISPLAY: list[tuple[TaskTiming, str]] = [
    (TaskTiming.NOW, "Now / start of shift"),
    (TaskTiming.EVENING, "22:00 — pre-bed pass"),
    (TaskTiming.OVERNIGHT, "00:00 — midnight checks"),
    (TaskTiming.AM_LABS, "04:00 — AM labs"),
    (TaskTiming.PRE_ROUNDS, "Pre-rounds (~05:00–06:00)"),
    (TaskTiming.PRN, "PRN (event-triggered)"),
    (TaskTiming.ANYTIME, "Anytime / standing"),
]
_TIMING_ORDER_IDX = {t: i for i, (t, _) in enumerate(_TIMING_DISPLAY)}

_SEVERITY_ICON = {"stable": "🟢", "watcher": "🟡", "unstable": "🔴"}


def _extraction_fingerprint(extraction: HandoffExtraction) -> str:
    """Short hash of the extraction — namespaces checkbox session-state keys.

    When the extraction changes (re-extract, apply edits, load demo), the
    fingerprint changes, so old checkbox state is naturally abandoned rather
    than mis-mapping onto a different task list. No manual cleanup needed.
    """
    return hashlib.sha256(
        extraction.model_dump_json().encode("utf-8")
    ).hexdigest()[:8]


def _short_id(identifier: str) -> str:
    """Pull a short patient label for cross-patient Timeline display.

    'Aisha Morgan — Stepdown Bed 8' -> 'Aisha Morgan'.
    Used as the [bracketed] prefix on Timeline checkboxes so the receiver
    knows which patient each task belongs to at a glance.
    """
    for sep in ["—", " - ", ","]:
        if sep in identifier:
            return identifier.split(sep)[0].strip()
    return identifier


def _task_key(fp: str, patient_idx: int, task_idx: int) -> str:
    """Stable session-state key for a task's checkbox.

    The fingerprint prefix means re-extraction invalidates old state; the
    (patient_idx, task_idx) suffix means Shift mode and Timeline view share
    the same key for the same task and thus the same checkbox state.
    """
    return f"chk_{fp}_{patient_idx}_{task_idx}"


def _render_shift_mode_tab(extraction: HandoffExtraction) -> None:
    """Per-patient checklist view. Designed to be readable one-handed."""
    fp = _extraction_fingerprint(extraction)
    n = len(extraction.patients)

    # Bound-check the patient index — re-extraction can change patient count.
    if "shift_idx" not in st.session_state or st.session_state.shift_idx >= n:
        st.session_state.shift_idx = 0

    # Navigation row: prev / picker / next
    nav_cols = st.columns([1, 4, 1])
    with nav_cols[0]:
        if st.button(
            "← Prev",
            use_container_width=True,
            disabled=st.session_state.shift_idx == 0,
            key="shift_prev",
        ):
            st.session_state.shift_idx -= 1
            st.rerun()
    with nav_cols[1]:
        picked = st.selectbox(
            "Patient",
            range(n),
            index=st.session_state.shift_idx,
            format_func=lambda i: f"{i+1}/{n} — {extraction.patients[i].identifier}",
            key="shift_picker",
            label_visibility="collapsed",
        )
        if picked != st.session_state.shift_idx:
            st.session_state.shift_idx = picked
            st.rerun()
    with nav_cols[2]:
        if st.button(
            "Next →",
            use_container_width=True,
            disabled=st.session_state.shift_idx == n - 1,
            key="shift_next",
        ):
            st.session_state.shift_idx += 1
            st.rerun()

    pi = st.session_state.shift_idx
    p = extraction.patients[pi]

    # Patient header
    st.markdown(f"## {p.identifier}")
    icon = _SEVERITY_ICON.get(p.illness_severity.value, "")
    st.markdown(
        f"{icon} **{p.illness_severity.value.upper()}** · Code: **{p.code_status}**"
    )
    st.markdown(f"*{p.one_liner}*")

    # Today
    if p.day_events:
        st.markdown("### Today")
        for e in p.day_events:
            st.markdown(f"- {e}")

    # Exam
    if p.exam_findings:
        st.markdown("### Exam")
        st.markdown("; ".join(p.exam_findings))

    # Tasks — checkable. Sort by shift order so 22:00 appears before 04:00 etc.
    if p.tasks:
        st.markdown("### Tasks")
        sorted_tasks = sorted(
            enumerate(p.tasks),
            key=lambda x: _TIMING_ORDER_IDX.get(x[1].when, 99),
        )
        for ti, t in sorted_tasks:
            key = _task_key(fp, pi, ti)
            when_str = f"`{t.when.value}` " if t.when != TaskTiming.ANYTIME else ""
            st.checkbox(f"{when_str}{t.description}", key=key)

    # Contingencies — prominent, since these are the watch-outs
    if p.contingencies:
        st.markdown("### ⚠️ If / Then")
        for c in p.contingencies:
            st.markdown(f"- **If** {c.trigger}  \n  → {c.action}")

    # Footer info in an expander to keep the main view scannable
    with st.expander("Meds · Pending · Gaps"):
        if p.active_meds:
            st.markdown("**Active meds**")
            for m in p.active_meds:
                parts = [m.name]
                if m.dose: parts.append(m.dose)
                if m.route: parts.append(m.route)
                if m.frequency: parts.append(m.frequency)
                stem = " ".join(parts)
                if m.notable_levels:
                    stem += f" _({m.notable_levels})_"
                st.markdown(f"- {stem}")
        if p.pending_results:
            st.markdown("**Pending**")
            for r in p.pending_results:
                st.markdown(f"- {r}")
        if p.completeness_gaps:
            gaps_str = "; ".join(p.completeness_gaps)
            st.markdown(f"**Missing:** :red[{gaps_str}]")


def _render_timeline_tab(extraction: HandoffExtraction) -> None:
    """Cross-patient checklist grouped by time bucket.

    Matches how overnight cross-cover actually thinks: 'at 04:00 I need to
    draw labs for A and B, check IV for C' — not 'let me re-read patient A's
    card every time.' Uses the same task keys as Shift mode, so checking a
    task here also checks it there.
    """
    fp = _extraction_fingerprint(extraction)

    # Group: TaskTiming -> list of (patient_idx, task_idx, patient, task)
    buckets: dict[TaskTiming, list[tuple[int, int, Patient, Task]]] = defaultdict(list)
    for pi, p in enumerate(extraction.patients):
        for ti, t in enumerate(p.tasks):
            buckets[t.when].append((pi, ti, p, t))

    if not buckets:
        st.info("No tasks extracted. Edit the cards in step 4 or re-extract.")
        return

    st.caption(
        "Checkboxes are shared with Shift mode — checking here also checks there."
    )

    for timing, label in _TIMING_DISPLAY:
        if timing not in buckets:
            continue
        st.markdown(f"### {label}")
        for pi, ti, p, t in buckets[timing]:
            key = _task_key(fp, pi, ti)
            short = _short_id(p.identifier)
            st.checkbox(f"**[{short}]** {t.description}", key=key)


# --- Step 1: Input ---

st.subheader("1. Provide input")

tab_upload, tab_record, tab_paste, tab_demo = st.tabs(
    ["Upload audio", "Record audio", "Paste text", "Demo (no API call)"]
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

with tab_demo:
    # Showcases the app end-to-end with zero API cost and zero latency.
    # The transcript + extraction are hard-coded in src/demo_data.py and
    # rendered through the same render_sheet() path the live app uses, so
    # the downstream UI (steps 2-4) is identical to a real run.
    st.markdown(
        "Use this tab to demo the app without calling the LLM. The transcript "
        "below is a 3-patient handoff; clicking the button loads a pre-computed "
        "extraction and renders the one-pager instantly."
    )
    st.text_area(
        "Demo transcript (read-only)",
        value=DEMO_TRANSCRIPT,
        height=260,
        key="demo_transcript_view",
        disabled=True,
    )
    if st.button("Run demo extraction (instant, no API call)", type="primary", key="demo_btn"):
        st.session_state.transcript = DEMO_TRANSCRIPT
        demo_extraction = build_demo_extraction()
        st.session_state.extraction = demo_extraction
        st.session_state.html_out = render_sheet(demo_extraction)
        # Fake metadata so the metric strip in Step 3 still renders coherently.
        # 0 ms + "cache hit" honestly describes what just happened: no API call,
        # instant. Switching to a real run later will overwrite these.
        st.session_state.last_extraction_ms = 0
        st.session_state.last_cache_hit = True
        st.rerun()

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
    st.subheader("3. View handoff")

    # Metadata strip
    extraction: HandoffExtraction = st.session_state.extraction
    n_pat = len(extraction.patients)
    elapsed = st.session_state.last_extraction_ms or 0
    cache_lbl = "cache hit" if st.session_state.last_cache_hit else "fresh extraction"
    meta_cols = st.columns(3)
    meta_cols[0].metric("Patients extracted", n_pat)
    meta_cols[1].metric("Latency", f"{elapsed} ms")
    meta_cols[2].metric("Source", cache_lbl)

    # Three views on the same extraction:
    #   - Print sheet: 6-card HTML grid, printable, the original output
    #   - Shift mode: per-patient mobile-friendly checklist
    #   - Timeline: cross-patient time-bucketed checklist
    # Shift mode + Timeline share checkbox state via _task_key(), so a check
    # in one view is reflected in the other.
    view_tabs = st.tabs(["Print sheet", "Shift mode", "Timeline"])

    with view_tabs[0]:
        st.components.v1.html(st.session_state.html_out, height=1100, scrolling=True)
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

    with view_tabs[1]:
        _render_shift_mode_tab(extraction)

    with view_tabs[2]:
        _render_timeline_tab(extraction)

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
