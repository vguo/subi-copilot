"""Render a HandoffExtraction into a printable HTML one-pager.

Layout: letter sheet, 2-column x 3-row grid of patient cards (6 max per sheet).
Each card shows identifier, severity, one-liner, day events, exam findings,
tasks (time-bucketed), contingencies, pending results, meds, and code status.

This module is deterministic. No LLM calls happen here directly — all clinical
content is lifted from the HandoffExtraction produced by src/extract.py.
Keeping render LLM-free is what makes the verbatim-first approach work:
nothing here can hallucinate items the speaker did not say.

Extraction calls are cached on disk under .cache/extractions/, so re-rendering
the same transcripts costs $0 in API spend.

Usage:
    python -m src.render data/synthetic_handoffs/01_copd_lopez.txt
    python -m src.render data/synthetic_handoffs/01_copd_lopez.txt \
        data/synthetic_handoffs/02_hf_patel.txt
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

from .extract import extract_handoff_cached
from .schema import HandoffExtraction, Patient, Task, TaskTiming

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "prompts" / "one_pager.html"
OUTPUTS_DIR = Path(__file__).resolve().parent.parent / "outputs"
CARDS_PER_SHEET = 6

# Display order for time buckets on the card. Earlier in shift = higher up.
TIMING_ORDER: dict[TaskTiming, int] = {
    TaskTiming.NOW: 0,
    TaskTiming.EVENING: 1,
    TaskTiming.OVERNIGHT: 2,
    TaskTiming.AM_LABS: 3,
    TaskTiming.PRE_ROUNDS: 4,
    TaskTiming.PRN: 5,
    TaskTiming.ANYTIME: 6,
}


def _esc(text: str | None) -> str:
    """Escape a string for safe HTML insertion. None becomes ''."""
    if text is None:
        return ""
    return html.escape(text)


def _sorted_tasks(tasks: list[Task]) -> list[Task]:
    """Sort tasks so timed items come first in shift order, anytime items last."""
    return sorted(tasks, key=lambda t: TIMING_ORDER.get(t.when, 99))


def render_card(p: Patient) -> str:
    """Render one patient as a card div."""
    severity = p.illness_severity.value

    # Day events: the "what happened today" context. Inline comma-list to save space.
    day_block = ""
    if p.day_events:
        items = "".join(f"<li>{_esc(e)}</li>" for e in p.day_events)
        day_block = (
            '<div class="section">'
            '<div class="section-label">Today</div>'
            f'<ul class="bullets">{items}</ul>'
            "</div>"
        )

    # Exam findings: relevant abnormal/notable findings. Compact comma-list.
    exam_block = ""
    if p.exam_findings:
        exam_str = "; ".join(_esc(f) for f in p.exam_findings)
        exam_block = (
            '<div class="section exam">'
            '<span class="section-label-inline">Exam:</span> '
            f"{exam_str}"
            "</div>"
        )

    # Tasks: time-bucketed checklist. The main content. Sorted by shift order.
    if p.tasks:
        task_items = []
        for t in _sorted_tasks(p.tasks):
            time_label = ""
            if t.when != TaskTiming.ANYTIME:
                time_label = f'<span class="when">{_esc(t.when.value)}</span>'
            task_items.append(f"<li>{time_label}{_esc(t.description)}</li>")
        tasks_block = (
            '<div class="section">'
            '<div class="section-label">Tasks</div>'
            f'<ul class="tasks">{"".join(task_items)}</ul>'
            "</div>"
        )
    else:
        tasks_block = ""

    # Contingencies: if X -> Y. Rendered with explicit trigger -> action.
    if p.contingencies:
        cont_items = "".join(
            f'<li><span class="trig">If</span> {_esc(c.trigger)}'
            f'<span class="arrow">→</span>{_esc(c.action)}</li>'
            for c in p.contingencies
        )
        cont_block = (
            '<div class="section">'
            '<div class="section-label">If/Then</div>'
            f'<ul class="conts">{cont_items}</ul>'
            "</div>"
        )
    else:
        cont_block = ""

    # Pending: small footer cue.
    pending_str = "; ".join(_esc(x) for x in p.pending_results) if p.pending_results else ""

    # Meds: compact, semicolon-separated, with notable_levels italicized in parens.
    if p.active_meds:
        med_strs = []
        for m in p.active_meds:
            parts = [_esc(m.name)]
            if m.dose:
                parts.append(_esc(m.dose))
            if m.route:
                parts.append(_esc(m.route))
            if m.frequency:
                parts.append(_esc(m.frequency))
            stem = " ".join(parts)
            if m.notable_levels:
                stem += f" <i>({_esc(m.notable_levels)})</i>"
            med_strs.append(stem)
        meds_str = "; ".join(med_strs)
    else:
        meds_str = ""

    # Completeness gaps: small red callout so missing info is visible.
    gaps_block = ""
    if p.completeness_gaps:
        gaps_block = (
            f'<div class="gaps">Missing: {_esc("; ".join(p.completeness_gaps))}</div>'
        )

    footer_parts = []
    if meds_str:
        footer_parts.append(f'<div><span class="label">Meds:</span> {meds_str}</div>')
    if pending_str:
        footer_parts.append(f'<div><span class="label">Pending:</span> {pending_str}</div>')
    footer_parts.append(
        f'<div><span class="label">Code:</span> {_esc(p.code_status)}</div>'
    )
    footer_html = '<div class="footer">' + "".join(footer_parts) + "</div>"

    return (
        f'<div class="card">'
        f'  <div class="card-header">'
        f'    <span class="ident">{_esc(p.identifier)}</span>'
        f'    <span class="severity {severity}">{severity}</span>'
        f"  </div>"
        f'  <div class="oneliner">{_esc(p.one_liner)}</div>'
        f"  {day_block}"
        f"  {exam_block}"
        f"  {tasks_block}"
        f"  {cont_block}"
        f"  {gaps_block}"
        f"  {footer_html}"
        f"</div>"
    )


def render_sheet(extraction: HandoffExtraction) -> str:
    """Render a full HandoffExtraction into a complete HTML sheet."""
    cards = [render_card(p) for p in extraction.patients]

    # Pad to CARDS_PER_SHEET with dashed-border placeholders so the grid
    # stays visually intact even when there are fewer than 6 patients.
    while len(cards) < CARDS_PER_SHEET:
        cards.append('<div class="card blank"></div>')

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.replace("{{CARDS}}", "\n".join(cards))


def _load_and_extract(paths: list[Path]) -> HandoffExtraction:
    """Read each handoff file, extract (cached), and merge patient lists."""
    all_patients: list[Patient] = []
    for path in paths:
        transcript = path.read_text(encoding="utf-8")
        extraction = extract_handoff_cached(transcript)
        all_patients.extend(extraction.patients)
    return HandoffExtraction(patients=all_patients)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m src.render <transcript.txt> [<transcript2.txt> ...]")
        sys.exit(1)

    paths = [Path(p) for p in sys.argv[1:]]
    for path in paths:
        if not path.exists():
            print(f"Error: file not found: {path}")
            sys.exit(1)

    extraction = _load_and_extract(paths)

    html_output = render_sheet(extraction)
    OUTPUTS_DIR.mkdir(exist_ok=True)
    out_path = OUTPUTS_DIR / "one_pager.html"
    out_path.write_text(html_output, encoding="utf-8")

    print(f"Rendered {len(extraction.patients)} patient(s) to {out_path}")
    print("Open in browser, then Ctrl+P -> Save as PDF for a printable one-pager.")


if __name__ == "__main__":
    main()
