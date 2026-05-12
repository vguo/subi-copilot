"""Hard-coded demo transcript + extraction.

Used by the "Demo" tab in app.py so the app can be showcased without burning
an API call or waiting on extraction. The extraction below was hand-built to
mirror what the real Claude extraction produces on the same transcript, so
the rendered one-pager looks indistinguishable from a live run.

If you change the schema (src/schema.py) in a way that breaks this file,
Pydantic will yell at import time — that's the intended forcing function.
"""

from __future__ import annotations

from .schema import (
    Contingency,
    HandoffExtraction,
    IllnessSeverity,
    Medication,
    Patient,
    Task,
    TaskTiming,
)


DEMO_TRANSCRIPT = """So here's our first patient: Aisha Morgan in Stepdown Unit bed 8 is a 45-year-old woman with alcohol use disorder, admitted for severe symptomatic hyponatremia after poor intake and heavy beer intake. Sodium was 116 on arrival, now 123 at 6 PM after a small amount of hypertonic saline and fluid restriction. Nephrology is following. BMPs are every four hours, next at 10 PM and 2 AM. Please make sure labs are drawn on time, fluid restriction is active, strict I/Os are followed, and seizure precautions are in place.

Overnight, watch for seizure, worsening confusion, severe headache, vomiting, or focal neuro deficits. If sodium rises by more than 8 in 24 hours, or hits 125 or higher before morning, call nephrology and the senior because she may need D5W or DDAVP. If she seizes, call rapid response, protect airway, give benzos per protocol, and notify the senior. She is full code.

Next, Malcolm Reed in 9 East Bed 3 is a 57-year-old man with poorly controlled diabetes and peripheral vascular disease, admitted for severe left leg cellulitis. CT today showed cellulitis without gas or abscess, and surgery thought nec fasc was unlikely but wants to be called if he worsens. He is on vancomycin and Zosyn, with mild AKI, creatinine 1.4 from baseline 1.0. Please make sure the vanc trough is drawn before the morning dose, follow up morning BMP, and keep the leg elevated.

Overnight, watch for fever, hypotension, rapidly spreading erythema beyond marked borders, pain out of proportion, bullae, necrosis, crepitus, numbness, or altered mental status. If any occur, evaluate urgently, repeat labs and lactate, call surgery and the senior, and consider escalation. He is full code.

Caroline Evans in 5 West Bed 11 is a 62-year-old woman with hepatitis C cirrhosis, prior varices, and insulin-dependent diabetes, admitted for coffee-ground emesis and melena. Hemoglobin was stable today around 7.5, and GI plans EGD tomorrow morning. She is on IV pantoprazole, octreotide drip, and ceftriaxone. Please confirm NPO after midnight, morning CBC/CMP/INR/type and screen, and make sure she still gets reduced-dose glargine tonight while NPO, with correction insulin only.

Overnight, watch for hematemesis, worsening melena, tachycardia, hypotension, dizziness, abdominal pain, or confusion. If heart rate stays over 110, systolic BP is under 90, or she has hematemesis, evaluate immediately, get stat CBC/coags, ensure two large-bore IVs, and call GI and the senior. Transfuse for hemoglobin under 7, or earlier if unstable. She is full code."""


def build_demo_extraction() -> HandoffExtraction:
    """Return the canonical demo extraction (3 patients).

    Built fresh each call so callers can't accidentally mutate a shared
    object across reruns.
    """
    morgan = Patient(
        identifier="Aisha Morgan — Stepdown Bed 8",
        one_liner=(
            "45F with AUD, admitted for severe symptomatic hyponatremia after "
            "poor intake and heavy beer use; sodium correcting 116 → 123 on "
            "hypertonic saline and fluid restriction, nephrology following."
        ),
        illness_severity=IllnessSeverity.WATCHER,
        active_issues=[
            "Severe symptomatic hyponatremia (Na 116 → 123)",
            "Alcohol use disorder",
        ],
        day_events=[
            "Received small amount of hypertonic saline",
            "Fluid restriction started, strict I/Os in place",
            "Nephrology consulted, following",
        ],
        exam_findings=[],
        active_meds=[
            Medication(
                name="Hypertonic saline",
                dose="small amount",
                route="IV",
                indication="symptomatic hyponatremia",
                notable_levels="Na 116 → 123 after partial correction",
            ),
        ],
        pending_results=[
            "BMP q4h — next 22:00 and 02:00",
        ],
        tasks=[
            Task(description="Draw BMP", when=TaskTiming.EVENING),
            Task(description="Draw BMP", when=TaskTiming.OVERNIGHT),
            Task(description="Maintain fluid restriction", when=TaskTiming.ANYTIME),
            Task(description="Strict I/Os", when=TaskTiming.ANYTIME),
            Task(description="Seizure precautions in place", when=TaskTiming.ANYTIME),
        ],
        contingencies=[
            Contingency(
                trigger="Sodium rises >8 in 24h, or ≥125 before morning",
                action="Call nephrology and senior — may need D5W or DDAVP",
            ),
            Contingency(
                trigger="Seizure",
                action="Call rapid response, protect airway, benzos per protocol, notify senior",
            ),
            Contingency(
                trigger="Worsening confusion, severe headache, vomiting, or focal neuro deficits",
                action="Evaluate urgently and notify senior",
            ),
        ],
        code_status="Full code",
        family_situation=None,
        confidence_flags=[],
        completeness_gaps=[],
    )

    reed = Patient(
        identifier="Malcolm Reed — 9 East Bed 3",
        one_liner=(
            "57M with poorly controlled DM and PVD, admitted for severe left "
            "leg cellulitis on vancomycin and Zosyn; mild AKI (Cr 1.4 from "
            "baseline 1.0), surgery saw and thinks nec fasc unlikely."
        ),
        illness_severity=IllnessSeverity.WATCHER,
        active_issues=[
            "Severe left leg cellulitis",
            "Mild AKI (Cr 1.4 from baseline 1.0)",
            "Poorly controlled diabetes",
            "Peripheral vascular disease",
        ],
        day_events=[
            "CT: cellulitis without gas or abscess",
            "Surgery evaluated — nec fasc unlikely, wants call if worsens",
        ],
        exam_findings=[],
        active_meds=[
            Medication(
                name="Vancomycin",
                route="IV",
                indication="cellulitis",
                notable_levels="Trough due before morning dose",
            ),
            Medication(
                name="Piperacillin-tazobactam (Zosyn)",
                route="IV",
                indication="cellulitis",
            ),
        ],
        pending_results=[
            "Vancomycin trough (pre-morning-dose)",
            "Morning BMP",
        ],
        tasks=[
            Task(description="Draw vanc trough before morning dose", when=TaskTiming.PRE_ROUNDS),
            Task(description="Morning BMP", when=TaskTiming.AM_LABS),
            Task(description="Keep left leg elevated", when=TaskTiming.ANYTIME),
        ],
        contingencies=[
            Contingency(
                trigger=(
                    "Fever, hypotension, rapidly spreading erythema beyond marked "
                    "borders, pain out of proportion, bullae, necrosis, crepitus, "
                    "numbness, or AMS"
                ),
                action=(
                    "Evaluate urgently, repeat labs and lactate, call surgery and "
                    "senior, consider escalation"
                ),
            ),
        ],
        code_status="Full code",
        family_situation=None,
        confidence_flags=[],
        completeness_gaps=[],
    )

    evans = Patient(
        identifier="Caroline Evans — 5 West Bed 11",
        one_liner=(
            "62F with HCV cirrhosis, prior varices, and IDDM, admitted for "
            "coffee-ground emesis and melena; Hgb stable ~7.5 today, EGD planned "
            "tomorrow AM, on IV PPI, octreotide, and ceftriaxone."
        ),
        illness_severity=IllnessSeverity.WATCHER,
        active_issues=[
            "Upper GI bleed (coffee-ground emesis, melena)",
            "HCV cirrhosis with prior varices",
            "Insulin-dependent diabetes",
        ],
        day_events=[
            "Hgb stable around 7.5",
            "GI plans EGD tomorrow morning",
        ],
        exam_findings=[],
        active_meds=[
            Medication(
                name="Pantoprazole",
                route="IV",
                indication="UGIB",
            ),
            Medication(
                name="Octreotide",
                route="IV drip",
                indication="variceal bleed prophylaxis/treatment",
            ),
            Medication(
                name="Ceftriaxone",
                route="IV",
                indication="SBP prophylaxis in cirrhotic GIB",
            ),
            Medication(
                name="Glargine",
                route="subQ",
                indication="IDDM — reduced dose while NPO",
                notable_levels="Reduced dose tonight; correction insulin only",
            ),
        ],
        pending_results=[
            "Morning CBC, CMP, INR, type and screen",
        ],
        tasks=[
            Task(description="Confirm NPO after midnight", when=TaskTiming.EVENING),
            Task(
                description="Reduced-dose glargine tonight + correction insulin only",
                when=TaskTiming.EVENING,
            ),
            Task(
                description="Morning CBC, CMP, INR, type and screen",
                when=TaskTiming.AM_LABS,
            ),
        ],
        contingencies=[
            Contingency(
                trigger="HR >110, SBP <90, or hematemesis",
                action=(
                    "Evaluate immediately, stat CBC/coags, ensure two large-bore IVs, "
                    "call GI and senior"
                ),
            ),
            Contingency(
                trigger="Hemoglobin <7 (or earlier if unstable)",
                action="Transfuse PRBCs",
            ),
            Contingency(
                trigger="Worsening melena, tachycardia, hypotension, dizziness, abdominal pain, or confusion",
                action="Evaluate at bedside and escalate to senior",
            ),
        ],
        code_status="Full code",
        family_situation=None,
        confidence_flags=[],
        completeness_gaps=[],
    )

    return HandoffExtraction(patients=[morgan, reed, evans])
