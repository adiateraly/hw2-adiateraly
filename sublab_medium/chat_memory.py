"""
Sublab Medium -- memory you choose: the compress command.

Run:  python -m sublab_medium.chat_memory
      python -m sublab_medium.chat_memory --interactive
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import tiktoken
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
SCRIPT = load_json("chat_script.json")
MEMORY_SCHEMA = load_json("memory_state.schema.json")

COMPRESS_MARKER = "<compress>"

SYSTEM_PROMPT = f"""
You are a grant-office chat assistant helping an applicant by phone/chat.
Answer only from these records -- never invent a fact the applicant has not
given you and never invent a fact not present here:

APPLICANT RECORDS:
{json.dumps(RECORDS, ensure_ascii=False, indent=2)}

GRANT RULE:
{POLICY['rule_human']}
Grant amounts: band 1 = {POLICY['amount_tenge_by_band']['1']} {POLICY['currency']},
band 2 = {POLICY['amount_tenge_by_band']['2']} {POLICY['currency']}.
Required documents: {", ".join(POLICY['required_documents'])}.

Reply in plain, natural prose (not JSON) in the same language the applicant
is writing in. Be concise. If something was already established earlier in
the conversation, remember and reuse it rather than asking again.
""".strip()

COMPRESS_INSTRUCTIONS = f"""
Summarise the conversation so far into a single JSON object and nothing else,
matching exactly this schema:
{json.dumps(MEMORY_SCHEMA, indent=2)}

Rules:
- "facts" are things the APPLICANT stated, not things you inferred or computed.
- "decisions" are conclusions actually given to the applicant in this chat.
- "constraints" are conditions on how/when something can happen (a day, a
  deadline, a requirement the applicant set) -- do not drop these.
- "open_questions" are things the applicant asked that were not yet answered.
- Nothing may be invented. A fact never stated is not a fact.
- applicant_id is null if it was never established.
""".strip()

# ---------------------------------------------------------------------------
# Token accounting
# ---------------------------------------------------------------------------

try:
    _ENC = tiktoken.encoding_for_model("gpt-4")
except Exception:
    _ENC = tiktoken.get_encoding("cl100k_base")


def estimate_tokens(messages: list[dict]) -> int:
    """Fallback token estimate, used only if the API response has no usage."""
    return sum(len(_ENC.encode(m["content"])) for m in messages) + 4 * len(messages)


# ---------------------------------------------------------------------------
# Model call
# ---------------------------------------------------------------------------

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def call_model(
    messages: list[dict], json_schema: dict | None = None, schema_name: str = "reply"
) -> tuple[str, dict]:
    """
    Returns (reply_text, usage_dict) where usage_dict has
    prompt_tokens / completion_tokens / total_tokens, and a "source" flag
    saying whether the counts came from the API ("api") or a local
    estimate ("estimate").
    """
    kwargs: dict = {"model": MODEL, "messages": messages}
    if json_schema is not None:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "schema": json_schema, "strict": True},
        }
    resp = client().chat.completions.create(**kwargs)
    text = resp.choices[0].message.content or ""
    if getattr(resp, "usage", None) is not None:
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "total_tokens": resp.usage.total_tokens,
            "source": "api",
        }
    else:
        pt = estimate_tokens(messages)
        usage = {
            "prompt_tokens": pt,
            "completion_tokens": len(_ENC.encode(text)),
            "total_tokens": pt + len(_ENC.encode(text)),
            "source": "estimate",
        }
    return text, usage


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class ChatSession:
    def __init__(self, allow_compress: bool):
        self.allow_compress = allow_compress
        self.full_history: list[dict] = []          # every real turn, for logging
        self.active_history: list[dict] = []         # what actually gets (re)sent
        self.state: dict | None = None
        self.call_log: list[dict] = []
        self.last_usage: dict | None = None

    def _messages_for_call(self) -> list[dict]:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        if self.state is not None:
            msgs.append(
                {
                    "role": "system",
                    "content": "Conversation so far, compressed to structured state:\n"
                    + json.dumps(self.state, ensure_ascii=False),
                }
            )
        msgs.extend(self.active_history)
        return msgs

    def send(self, user_text: str, label: str = "chat") -> str:
        self.full_history.append({"role": "user", "content": user_text})
        self.active_history.append({"role": "user", "content": user_text})
        messages = self._messages_for_call()
        reply, usage = call_model(messages)
        self.active_history.append({"role": "assistant", "content": reply})
        self.full_history.append({"role": "assistant", "content": reply})
        self.last_usage = usage
        self.call_log.append(
            {
                "label": label,
                "sent_messages": len(messages),
                "prompt_tokens": usage["prompt_tokens"],
                "completion_tokens": usage["completion_tokens"],
                "source": usage["source"],
            }
        )
        return reply

    def compress(self) -> tuple[bool, str]:
        """
        Attempts to compress active_history into self.state.
        Returns (success, message).
        """
        if not self.allow_compress:
            return False, "compression disabled for this session"

        messages = self._messages_for_call() + [
            {"role": "user", "content": COMPRESS_INSTRUCTIONS}
        ]
        raw, usage = call_model(
            messages, json_schema=MEMORY_SCHEMA, schema_name="memory_state"
        )
        self.last_usage = usage
        self.call_log.append(
            {
                "label": "compress",
                "sent_messages": len(messages),
                "prompt_tokens": usage["prompt_tokens"],
                "completion_tokens": usage["completion_tokens"],
                "source": usage["source"],
            }
        )

        try:
            parsed = json.loads(raw)
            validate(parsed, MEMORY_SCHEMA)
        except (json.JSONDecodeError, ValidationError) as e:
            # Do NOT touch state or active_history -- keep the conversation.
            return False, f"compression rejected ({e.__class__.__name__}: {e}); history kept"

        self.state = parsed
        self.active_history = []  # from here on, only the state + new turns are sent
        return True, "compressed"


# ---------------------------------------------------------------------------
# Scripted run
# ---------------------------------------------------------------------------

def run_script(use_compression: bool) -> ChatSession:
    session = ChatSession(allow_compress=use_compression)
    for turn in SCRIPT["conversation"]:
        if turn == COMPRESS_MARKER:
            if use_compression:
                ok, msg = session.compress()
                print(f"[compress] {msg}")
            # if not using compression, this slot is simply skipped -- it was
            # never something the applicant said.
            continue
        session.send(turn, label="script")
    return session


def run_probes(session: ChatSession) -> list[dict]:
    results = []
    for probe in SCRIPT["probes"]:
        reply = session.send(probe["question"], label=f"probe:{probe['id']}")
        lowered = reply.lower()
        retrieved = any(s.lower() in lowered for s in probe["expect_contains"])
        results.append(
            {
                "id": probe["id"],
                "tests": probe["tests"],
                "retrieved": retrieved,
                "reply": reply,
            }
        )
    return results


def print_call_log(label: str, session: ChatSession) -> None:
    print(f"\n=== token log: {label} ===")
    header = f"{'#':3} {'label':14} {'sent_msgs':9} {'prompt_tok':10} {'compl_tok':9} {'source':8}"
    print(header)
    print("-" * len(header))
    peak = 0
    for i, c in enumerate(session.call_log, 1):
        peak = max(peak, c["prompt_tokens"])
        print(
            f"{i:3} {c['label']:14} {c['sent_messages']:9} "
            f"{c['prompt_tokens']:10} {c['completion_tokens']:9} {c['source']:8}"
        )
    print(f"peak prompt_tokens for this run: {peak}")


def print_probe_results(label: str, results: list[dict]) -> None:
    print(f"\n=== probes: {label} ===")
    for r in results:
        status = "RETRIEVED" if r["retrieved"] else "LOST"
        print(f"{r['id']:5} [{status:9}] ({r['tests']})")
        print(f"      reply: {r['reply']}")


def run_and_report() -> None:
    print("##### RUN 1: uncompressed #####")
    session_full = run_script(use_compression=False)
    probes_full = run_probes(session_full)
    print_call_log("uncompressed", session_full)
    print_probe_results("uncompressed", probes_full)

    print("\n##### RUN 2: compressed #####")
    session_compressed = run_script(use_compression=True)
    probes_compressed = run_probes(session_compressed)
    print_call_log("compressed", session_compressed)
    print_probe_results("compressed", probes_compressed)

    print("\n=== final compressed state object ===")
    print(json.dumps(session_compressed.state, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Interactive mode
# ---------------------------------------------------------------------------

def run_interactive() -> None:
    print("Interactive chat. Commands: 'compress', 'tokens', 'state', 'quit'.")
    session = ChatSession(allow_compress=True)
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text.lower() in {"quit", "exit"}:
            break
        if text.lower() == "compress":
            ok, msg = session.compress()
            print(f"[compress] {msg}")
            continue
        if text.lower() == "tokens":
            if session.last_usage is None:
                print("(no calls yet)")
            else:
                u = session.last_usage
                print(
                    f"last call: prompt={u['prompt_tokens']} "
                    f"completion={u['completion_tokens']} "
                    f"total={u['total_tokens']} ({u['source']})"
                )
            continue
        if text.lower() == "state":
            print(json.dumps(session.state, ensure_ascii=False, indent=2))
            continue
        reply = session.send(text)
        print(f"bot> {reply}")
        u = session.last_usage
        print(f"     [prompt_tokens={u['prompt_tokens']} source={u['source']}]")


# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args()
    if args.interactive:
        run_interactive()
    else:
        run_and_report()


if __name__ == "__main__":
    main()