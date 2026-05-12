"""Pydantic schema for structured handoff extraction.

Mirrors the schema in sub_i_copilot_plan.md. The `confidence_flags` and
`completeness_gaps` arrays are load-bearing: they encode uncertainty
directly into the data model rather than letting the model confabulate.
"""

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
            "Relevant abnormal or notable exam findings mentioned by the speaker "
            "('bibasilar crackles', 'LE edema', 'erythema improving compared with marked "
            "borders'). Only findings the speaker explicitly described. Do not infer "
            "findings from diagnosis. Do NOT repeat anything already in `one_liner` or "
            "`day_events` — if 'breathing improving' is in the one-liner, do not also "
            "list it here."
        ),
    )
    active_meds: list[Medication] = Field(default_factory=list)
    pending_results: list[str] = Field(default_factory=list, description="Labs, imaging, consult recs awaited.")
    tasks: list[Task] = Field(
        default_factory=list,
        description=(
            "Standing actions for the overnight receiver. Capture monitoring directives "
            "('watch O2 sat, goal 88-92%'), explicit orders ('NPO after midnight'), things "
            "to avoid ('do not restart anticoagulation', 'avoid benzos'), results to chase "
            "('verify morning BMP'), or active care ('continue leg elevation'). "
            "Each task gets a `when` bucket — use it whenever the handoff suggests a time. "
            "Do NOT duplicate contingencies — those are conditional 'if X then Y' items "
            "and live in their own field."
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
