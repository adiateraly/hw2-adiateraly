"""
Sublab Hard -- stories in, CVs out, the best candidate by code.

Run:  python -m sublab_hard.cv_extract_and_rank
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from jsonschema import validate, ValidationError
from openai import OpenAI

# ---------------------------------------------------------------------------
# Paths / data
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
CANDIDATES_DIR = DATA_DIR / "candidates"

load_dotenv(REPO_ROOT / ".env")

MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6-luna")


def load_json(name: str) -> Any:
    with open(DATA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


RUBRIC = load_json("candidate_rubric.json")

STORY_FILES = sorted(CANDIDATES_DIR.glob("story-*.md"))

# ---------------------------------------------------------------------------
# CV schema -- the structured record extracted from each story
# ---------------------------------------------------------------------------

CV_SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_id": {"type": "string"},
        "full_name": {"type": ["string", "null"]},
        "degree": {"type": ["string", "null"]},
        "graduation_year": {"type": ["integer", "null"]},
        "gpa": {
            "type": "object",
            "properties": {
                "scale_used": {"type": ["string", "null"]},
                "original_value": {"type": ["number", "null"]},
                "gpa_4_scale": {"type": ["number", "null"]},
                "contradicted": {"type": "boolean"},
            },
            "required": ["scale_used", "original_value", "gpa_4_scale", "contradicted"],
            "additionalProperties": False,
        },
        "languages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "language": {"type": "string"},
                    "level": {"type": ["string", "null"]},
                },
                "required": ["language", "level"],
                "additionalProperties": False,
            },
        },
        "publications": {
            "type": "object",
            "properties": {
                "published_count": {"type": "integer"},
                "published": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "year": {"type": ["integer", "null"]},
                            "venue": {"type": ["string", "null"]},
                        },
                        "required": ["title", "year", "venue"],
                        "additionalProperties": False,
                    },
                },
                "not_counted": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": [
                                    "submitted",
                                    "under_review",
                                    "in_preparation",
                                    "in_press",
                                    "planned",
                                    "other_unpublished",
                                ],
                            },
                        },
                        "required": ["title", "status"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["published_count", "published", "not_counted"],
            "additionalProperties": False,
        },
        "experience": {
            "type": "object",
            "properties": {
                "periods": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "start": {"type": ["string", "null"]},
                            "end": {"type": ["string", "null"]},
                            "months": {"type": ["integer", "null"]},
                            "countable": {"type": "boolean"},
                        },
                        "required": ["description", "start", "end", "months", "countable"],
                        "additionalProperties": False,
                    },
                },
                "total_countable_months": {"type": ["integer", "null"]},
            },
            "required": ["periods", "total_countable_months"],
            "additionalProperties": False,
        },
        "ambiguities": {
            "type": "array",
            "items": {"type": "string"},
        },
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["field", "quote"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "candidate_id", "full_name", "degree", "graduation_year", "gpa",
        "languages", "publications", "experience", "ambiguities", "evidence",
    ],
    "additionalProperties": False,
}

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "academic": {"type": "integer", "minimum": 0, "maximum": 5},
        "research": {"type": "integer", "minimum": 0, "maximum": 5},
        "experience": {"type": "integer", "minimum": 0, "maximum": 5},
        "rationale": {
            "type": "object",
            "properties": {
                "academic": {"type": "string"},
                "research": {"type": "string"},
                "experience": {"type": "string"},
            },
            "required": ["academic", "research", "experience"],
            "additionalProperties": False,
        },
    },
    "required": ["academic", "research", "experience", "rationale"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# Extraction prompt
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM = f"""
You extract a structured CV record from one candidate's free-text scholarship
application story. Follow these rules exactly -- they override any
impression the story otherwise gives you:

1. A fact the story does not state is null. Never estimate or infer it, even
   if the degree or university makes a value plausible.
2. If a GPA is given on a scale other than 4.0, convert it to a 4.0 scale
   and record BOTH the original scale ("scale_used", e.g. "5.0") and the
   converted value in "gpa_4_scale". If no scale is stated, do not guess one.
3. A publication counts toward "published_count" and goes in "published"
   ONLY when the story says it is published or accepted. "Submitted",
   "under review", "in preparation", "planned" and "in press" are NOT
   published -- list those in "not_counted" with their actual status and do
   not count them.
4. Count experience in months, not jobs. Overlapping periods count once.
   A period with no start/end dates given is not countable: set
   "countable": false for it, and do not add its months into
   "total_countable_months" (its own "months" may still be null or an
   approximate figure the applicant stated, but it must not be counted).
5. If the story contradicts itself on any field (e.g. two different GPA
   figures, two different graduation years), do NOT resolve or average it:
   set that field to null, set "gpa.contradicted": true if it is the GPA,
   and add a plain description of the contradiction to "ambiguities".
6. Give at least one evidence quote (a short excerpt of the story, not a
   paraphrase) for every field you filled in, in the "evidence" array.
7. "candidate_id" must be exactly the id you are given in the user message.

Output only the JSON object, matching this schema exactly:
{json.dumps(CV_SCHEMA, indent=2)}
""".strip()


def extract_cv(candidate_id: str, story_text: str) -> tuple[dict | None, str, str | None]:
    resp = client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM},
            {
                "role": "user",
                "content": f"candidate_id: {candidate_id}\n\nSTORY:\n{story_text}",
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "cv_record", "schema": CV_SCHEMA, "strict": True},
        },
    )
    raw = resp.choices[0].message.content or ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, raw, f"json_error: {e}"
    try:
        validate(parsed, CV_SCHEMA)
    except ValidationError as e:
        return parsed, raw, f"schema_error: {e.message}"
    return parsed, raw, None


# ---------------------------------------------------------------------------
# Scoring prompt
# ---------------------------------------------------------------------------

SCORING_SYSTEM = f"""
You score ONE candidate's structured CV record against this rubric. Return a
0-5 integer score for each of the three criteria and nothing else you would
have to compute yourself -- do not compute a weighted total, do not rank,
do not decide a winner. That is done elsewhere.

RUBRIC:
{json.dumps(RUBRIC["criteria"], indent=2)}

COUNTING RULES (already applied when the record was built -- use the record's
fields as given, do not re-derive them from a story you do not have):
{json.dumps(RUBRIC["counting_rules"], indent=2)}

Output only JSON matching this schema:
{json.dumps(SCORE_SCHEMA, indent=2)}
""".strip()


def score_candidate(cv: dict) -> tuple[dict | None, str, str | None]:
    resp = client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SCORING_SYSTEM},
            {"role": "user", "content": json.dumps(cv, ensure_ascii=False, indent=2)},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "scores", "schema": SCORE_SCHEMA, "strict": True},
        },
    )
    raw = resp.choices[0].message.content or ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, raw, f"json_error: {e}"
    try:
        validate(parsed, SCORE_SCHEMA)
    except ValidationError as e:
        return parsed, raw, f"schema_error: {e.message}"
    return parsed, raw, None


def weighted_total(scores: dict) -> float:
    weights = {c["id"]: c["weight"] for c in RUBRIC["criteria"]}
    total = (
        weights["academic"] * scores["academic"]
        + weights["research"] * scores["research"]
        + weights["experience"] * scores["experience"]
    )
    return round(total, 2)


# ---------------------------------------------------------------------------
# Prose comparison (separate call, for Part 2)
# ---------------------------------------------------------------------------

def prose_ranking(all_cvs: list[dict]) -> str:
    resp = client().chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are advising a scholarship committee. You are given "
                    "the structured CV records for all candidates and the "
                    "rubric. Write a short prose recommendation of who should "
                    "win the one funded place and why. This is a judgement "
                    "call in prose -- you are not asked to output JSON or "
                    "scores here."
                ),
            },
            {
                "role": "user",
                "content": "RUBRIC:\n"
                + json.dumps(RUBRIC, ensure_ascii=False, indent=2)
                + "\n\nCANDIDATES:\n"
                + json.dumps(all_cvs, ensure_ascii=False, indent=2),
            },
        ],
    )
    return resp.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Trap / null reporting
# ---------------------------------------------------------------------------

def trap_hits(cv: dict) -> list[str]:
    hits = []
    if cv["gpa"]["contradicted"]:
        hits.append("GPA contradiction -> null + ambiguity")
    if cv["gpa"]["scale_used"] not in (None, "4.0", "4"):
        hits.append(f"GPA converted from {cv['gpa']['scale_used']} scale")
    if cv["publications"]["not_counted"]:
        statuses = sorted({p["status"] for p in cv["publications"]["not_counted"]})
        hits.append(f"non-published outputs excluded: {statuses}")
    if any(not p["countable"] for p in cv["experience"]["periods"]):
        hits.append("experience period without dates excluded from total")
    if cv["ambiguities"]:
        hits.append(f"{len(cv['ambiguities'])} ambiguity note(s)")
    return hits


def null_fields(cv: dict) -> list[str]:
    nulls = []
    for f in ("full_name", "degree", "graduation_year"):
        if cv.get(f) is None:
            nulls.append(f)
    if cv["gpa"]["gpa_4_scale"] is None:
        nulls.append("gpa.gpa_4_scale")
    if cv["experience"]["total_countable_months"] is None:
        nulls.append("experience.total_countable_months")
    return nulls


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    cvs: dict[str, dict] = {}

    print("=== Part 1: extraction ===")
    for path in STORY_FILES:
        candidate_id = path.stem.upper().replace("STORY-", "C-")  # story-01 -> C-01
        story_text = path.read_text(encoding="utf-8")
        parsed, raw, error = extract_cv(candidate_id, story_text)
        parsed_ok = parsed is not None
        valid_ok = error is None
        print(f"\n{candidate_id} ({path.name}): parsed={parsed_ok} valid={valid_ok}")
        if error:
            print(f"  ! {error}")
        if parsed:
            print(f"  null fields: {null_fields(parsed)}")
            print(f"  traps hit:   {trap_hits(parsed)}")
            cvs[candidate_id] = parsed
            if candidate_id == "C-06":
                print("  full record (C-06, for SUBMISSION.md):")
                print(json.dumps(parsed, ensure_ascii=False, indent=2))

    print("\n=== Part 2: scoring + computed ranking ===")
    ranking = []
    for candidate_id, cv in cvs.items():
        scores, raw, error = score_candidate(cv)
        if scores is None or error:
            print(f"{candidate_id}: scoring FAILED ({error})")
            continue
        total = weighted_total(scores)
        ranking.append((candidate_id, total, scores))
        print(
            f"{candidate_id}: academic={scores['academic']} "
            f"research={scores['research']} experience={scores['experience']} "
            f"-> weighted_total={total}"
        )

    ranking.sort(key=lambda r: r[1], reverse=True)
    print("\n-- computed ranking (code-side) --")
    for i, (candidate_id, total, scores) in enumerate(ranking, 1):
        print(f"{i}. {candidate_id}  total={total}")
    if ranking:
        print(f"\nCOMPUTED WINNER: {ranking[0][0]} (total={ranking[0][1]})")

    print("\n=== prose recommendation (separate call) ===")
    prose = prose_ranking(list(cvs.values()))
    print(prose)


if __name__ == "__main__":
    main()