"""Schema sanity check.

Validates the Pydantic schema against a hand-built extraction of the COPD
handoff. This runs without an API key — its job is to catch schema bugs
before we burn API tokens, and to serve as a worked example of what the
extraction LLM should produce.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make `src` importable when running this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.schema import HandoffExtraction  # noqa: E402

# What we expect the model to produce for 01_copd_lopez.txt.
# Hand-built so we can validate the schema before any API call.
HAND_EXTRACTION = {
    "patients": [
        {
            "identifier": "Maria Lopez, 7 East Bed 12",
            "one_liner": "67yo F with COPD (home 2L), admitted for COPD exacerbation likely from viral URI.",
            "illness_severity": "stable",
            "active_issues": [
                "COPD exacerbation, improving",
                "Viral URI as likely trigger",
            ],
            "active_meds": [
                {
                    "name": "duonebs",
                    "dose": None,
                    "route": "inhaled",
                    "frequency": "q6h (spaced from q4h today)",
                    "indication": "COPD exacerbation",
                    "notable_levels": None,
                },
                {
                    "name": "prednisone",
                    "dose": None,
                    "route": "PO",
                    "frequency": None,
                    "indication": "COPD exacerbation",
                    "notable_levels": "day 3 of 5",
                },
                {
                    "name": "azithromycin",
                    "dose": None,
                    "route": None,
                    "frequency": None,
                    "indication": "COPD exacerbation",
                    "notable_levels": None,
                },
            ],
            "pending_results": [],
            "contingencies": [
                {
                    "trigger": "increased work of breathing, rising O2 needs, or altered mental status",
                    "action": "evaluate at bedside; consider VBG, CXR, and escalating nebs",
                },
            ],
            "code_status": "full code",
            "family_situation": None,
            "confidence_flags": [
                {
                    "field": "illness_severity",
                    "reason": "Speaker did not use I-PASS severity terms; inferred 'stable' from clinical improvement and anticipated discharge.",
                },
                {
                    "field": "active_meds[1].dose",
                    "reason": "Prednisone dose not stated.",
                },
            ],
            "completeness_gaps": [
                "No specific medication doses for inhaled or oral therapy",
                "No pending labs/imaging mentioned by name",
            ],
        }
    ]
}


def main() -> None:
    extraction = HandoffExtraction.model_validate(HAND_EXTRACTION)
    print("Schema validation passed.")
    print(f"  Patients extracted: {len(extraction.patients)}")
    for p in extraction.patients:
        print(f"  - {p.identifier}: severity={p.illness_severity.value}, "
              f"meds={len(p.active_meds)}, contingencies={len(p.contingencies)}, "
              f"gaps={len(p.completeness_gaps)}")
    print("\nRound-trip JSON:")
    print(json.dumps(extraction.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
