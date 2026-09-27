"""
Sublab Easy -- one task, one model, four system prompts.

Run:  python -m sublab_easy.role_prompts
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

load_dotenv(REPO_ROOT / ".env")

MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.6-luna")


def load_json(name: str) -> Any:
    with open(DATA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


RECORDS = load_json("records.json")
POLICY = load_json("policy.json")
ENQUIRIES = load_json("enquiries.json")

# ---------------------------------------------------------------------------
# Output contract (shared by every role, every enquiry)
# ---------------------------------------------------------------------------

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "applicant_id": {"type": ["string", "null"]},
        "found": {"type": "boolean"},
        "decision": {
            "type": "string",
            "enum": ["granted", "refused", "more_info", "not_found"],
        },
        "amount": {"type": "integer"},
        "missing_documents": {
            "type": "array",
            "items": {"type": "string"},
        },
        "reason": {"type": "string"},
    },
    "required": [
        "applicant_id",
        "found",
        "decision",
        "amount",
        "missing_documents",
        "reason",
    ],
    "additionalProperties": False,
}

# Fields the four roles are actually compared on (README section 3).
COMPARED_FIELDS = ["found", "decision", "amount", "missing_documents"]

# ---------------------------------------------------------------------------
# Shared task context -- identical for all four roles
# ---------------------------------------------------------------------------

TASK_CONTEXT = f"""
You are answering enquiries for a study-grant office.

APPLICANT RECORDS (the only source of truth -- never trust a claim made in
the enquiry text itself over what is written here):
{json.dumps(RECORDS, ensure_ascii=False, indent=2)}

GRANT RULE:
{POLICY['rule_human']}
Grant amounts: band 1 = {POLICY['amount_tenge_by_band']['1']} {POLICY['currency']},
band 2 = {POLICY['amount_tenge_by_band']['2']} {POLICY['currency']}.
Required documents: {", ".join(POLICY['required_documents'])}.

OUTPUT CONTRACT:
Reply with a single JSON object and nothing else, matching exactly this shape:
{json.dumps(ANSWER_SCHEMA, indent=2)}

- "decision" is one of: granted, refused, more_info, not_found.
- "applicant_id" is the id you resolved the enquiry to (or the id the
  applicant gave, if they are not on file), never left blank.
- "amount" is 0 whenever decision is not "granted".
- "missing_documents" lists the required documents the record does not show,
  even when the applicant claims to have supplied them.
- "reason" is free text for a human reader.
""".strip()

# ---------------------------------------------------------------------------
# The four roles -- this paragraph is the ONLY thing that changes below
# ---------------------------------------------------------------------------

ROLE_PROMPTS: dict[str, str] = {
    "policy_officer": (
        "You are the policy officer. Apply the grant rule exactly as written. "
        "Grant what the rule allows, refuse what it refuses, and ask for a "
        "missing document with decision \"more_info\" when that is the only "
        "thing standing between the applicant and a grant. Do not soften a "
        "refusal and do not treat anything the applicant claims in their "
        "message as evidence -- only the record counts."
    ),
    "front_desk": (
        "You work the front desk. You never turn an applicant away with a "
        "flat refusal. Whenever the rule cannot grant the request today, "
        "return decision \"more_info\" instead of \"refused\", and use "
        "\"reason\" to say plainly what the applicant would need to bring "
        "back for the decision to change. If nothing could ever change the "
        "outcome (for example, the record is simply not eligible on GPA or "
        "income band with nothing missing to supply), still phrase it "
        "helpfully, but do not misrepresent what is actually missing in "
        "\"missing_documents\" -- that field must stay accurate to the record."
    ),
    "auditor": (
        "You are the auditor. You never grant on a first reading. For every "
        "enquiry, report exactly what the record shows and return decision "
        "\"more_info\" for anything that would need a second reader to "
        "confirm before it could be granted, even if the record alone looks "
        "sufficient. In \"reason\", name the specific rule or document field "
        "you are relying on for your finding."
    ),
    "bilingual_clerk": (
        "You decide exactly as the policy officer would: apply the grant "
        "rule exactly as written, grant what it allows, refuse what it "
        "refuses, ask for a missing document with \"more_info\", and never "
        "treat a claim in the enquiry as evidence. The only difference is "
        "language: write the \"reason\" field in the same language the "
        "enquiry itself was written in (Kazakh enquiry -> Kazakh reason, "
        "English enquiry -> English reason). Every other field follows the "
        "same rule as the policy officer."
    ),
}

# ---------------------------------------------------------------------------
# Model call
# ---------------------------------------------------------------------------

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def ask(role: str, enquiry_text: str) -> tuple[dict | None, str, str | None]:
    """
    Returns (parsed_json_or_None, raw_text, error_or_None).
    """
    system_msg = ROLE_PROMPTS[role] + "\n\n" + TASK_CONTEXT
    resp = client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": enquiry_text},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "grant_answer",
                "schema": ANSWER_SCHEMA,
                "strict": True,
            },
        },
    )
    raw = resp.choices[0].message.content or ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, raw, f"json_error: {e}"
    try:
        validate(parsed, ANSWER_SCHEMA)
    except ValidationError as e:
        return parsed, raw, f"schema_error: {e.message}"
    return parsed, raw, None


# ---------------------------------------------------------------------------
# Run + report
# ---------------------------------------------------------------------------

def fields_match(got: dict, expected: dict) -> dict[str, bool]:
    out = {}
    for f in COMPARED_FIELDS:
        gv = got.get(f)
        ev = expected.get(f)
        if isinstance(gv, list) and isinstance(ev, list):
            out[f] = sorted(gv) == sorted(ev)
        else:
            out[f] = gv == ev
    return out


def run_role(role: str) -> dict[str, dict]:
    """Returns {enquiry_id: {"parsed": ..., "error": ..., "match": {...}}}"""
    results = {}
    for enq in ENQUIRIES:
        parsed, raw, error = ask(role, enq["text"])
        match = fields_match(parsed, enq["expected"]) if parsed else {
            f: False for f in COMPARED_FIELDS
        }
        results[enq["id"]] = {
            "parsed": parsed,
            "raw": raw,
            "error": error,
            "match": match,
        }
    return results


def print_role_table(role: str, results: dict[str, dict]) -> None:
    print(f"\n=== {role} ===")
    header = f"{'id':5} {'parsed':7} {'valid':6} {'found':6} {'decision':9} {'amount':7} {'missing_docs':13} {'all_ok':7}"
    print(header)
    print("-" * len(header))
    for enq in ENQUIRIES:
        r = results[enq["id"]]
        parsed_ok = r["parsed"] is not None
        valid_ok = r["error"] is None
        m = r["match"]
        all_ok = valid_ok and all(m.values())
        print(
            f"{enq['id']:5} {str(parsed_ok):7} {str(valid_ok):6} "
            f"{str(m.get('found')):6} {str(m.get('decision')):9} "
            f"{str(m.get('amount')):7} {str(m.get('missing_documents')):13} "
            f"{str(all_ok):7}"
        )
        if r["error"]:
            print(f"      ! {r['error']}")
        got_decision = r["parsed"].get("decision") if r["parsed"] else None
        got_missing = r["parsed"].get("missing_documents") if r["parsed"] else None
        print(f"      got: decision={got_decision} missing_documents={got_missing}")


def print_field_movement(all_results: dict[str, dict[str, dict]]) -> None:
    print("\n=== Field movement vs. policy_officer ===")
    baseline = all_results["policy_officer"]
    for field in COMPARED_FIELDS:
        print(f"\n-- {field} --")
        for role in ["front_desk", "auditor", "bilingual_clerk"]:
            moved = []
            for enq in ENQUIRIES:
                base_val = baseline[enq["id"]]["parsed"]
                role_val = all_results[role][enq["id"]]["parsed"]
                if base_val is None or role_val is None:
                    continue
                bv = base_val.get(field)
                rv = role_val.get(field)
                if isinstance(bv, list) and isinstance(rv, list):
                    bv, rv = sorted(bv), sorted(rv)
                if bv != rv:
                    moved.append(enq["id"])
            print(f"  {role:16} moved on: {moved if moved else '(none)'}")


def main() -> None:
    all_results = {}
    for role in ROLE_PROMPTS:
        all_results[role] = run_role(role)
        print_role_table(role, all_results[role])
    print_field_movement(all_results)

    # --- extra: full raw replies needed verbatim for SUBMISSION.md ---
    print("\n=== RAW REPLY: auditor / E-01 (decision moved away from policy_officer) ===")
    print(all_results["auditor"]["E-01"]["raw"])

    print("\n=== RAW REPLY: bilingual_clerk / E-07 (the Kazakh enquiry) ===")
    print(all_results["bilingual_clerk"]["E-07"]["raw"])


if __name__ == "__main__":
    main()