"""End-to-end smoke test against a running backend.

Run:  python smoke_test.py            (expects http://localhost:8000)
      python smoke_test.py --url http://localhost:8001

Checks the things that actually break: the database is the one you think it
is, the configured models exist, the log_complaint tool fires and fills the
form, extraction does not fabricate, and duplicate detection sees history.

Exits non-zero if anything fails, so it is usable in CI.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    icon = {PASS: "  [ok]  ", FAIL: "  [FAIL]", WARN: "  [warn]"}[status]
    print(f"{icon} {name}" + (f"  -  {detail}" if detail else ""))


def get(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers={"User-Agent": "qms-smoke-test"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def post(url: str, payload: dict, timeout: int = 180):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "qms-smoke-test"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    print(f"\nSmoke testing {base}\n" + "=" * 62)

    # --- 1. service is up -------------------------------------------------
    print("\nService")
    try:
        health = get(f"{base}/health", timeout=10)
    except (urllib.error.URLError, TimeoutError) as exc:
        record(FAIL, "backend reachable", str(exc))
        print("\nIs the backend running? Start it with:")
        print("  python -m uvicorn app.main:app --reload\n")
        return 1
    record(PASS, "backend reachable")

    # --- 2. database ------------------------------------------------------
    print("\nDatabase")
    dialect = health.get("database")
    if dialect in ("postgresql", "mysql"):
        record(PASS, f"using {dialect}")
    else:
        record(
            WARN,
            f"using {dialect}",
            "SQLite fallback - the brief asks for PostgreSQL/MySQL",
        )

    try:
        stats = get(f"{base}/api/complaints/stats")
        total = stats.get("total", 0)
        if total > 0:
            record(PASS, f"{total} complaints in the register")
        else:
            record(WARN, "register is empty", "run: python seed.py --reset")
    except Exception as exc:  # noqa: BLE001
        record(FAIL, "stats endpoint", str(exc))

    # --- 3. models --------------------------------------------------------
    print("\nAI models")
    ai = get(f"{base}/api/ai/health")
    if not ai.get("llm_configured"):
        record(WARN, "no GROQ_API_KEY", "everything will run on deterministic rules")
    elif ai.get("models_available") is False:
        record(
            FAIL,
            "configured model unavailable",
            ", ".join(ai.get("missing_models", [])),
        )
    else:
        record(
            PASS,
            "models available",
            f"{ai['extraction_model']} + {ai['reasoning_model']}",
        )

    # --- 4. the log_complaint tool ---------------------------------------
    print("\nlog_complaint tool")
    prompt = (
        "Apollo Pharmacy reported 12 discolored capsules in a sealed bottle of "
        "Amoxicillin Capsules 500 mg. Batch number AMX240602. Manufacturing date "
        "March 2026. Expiry date February 2028. Please log this complaint"
    )
    turn = post(f"{base}/api/ai/chat", {"message": prompt, "history": [], "form": {}})

    if turn.get("tool_called") == "log_complaint":
        record(PASS, "tool fired on a complaint", f"{turn['latency_ms']} ms")
    else:
        record(FAIL, "tool did not fire", f"tool_called={turn.get('tool_called')}")

    if turn.get("degraded"):
        record(WARN, "run was degraded", "rule-based fallback was used")

    form = turn.get("form_update", {})
    expected = {
        "complaint_source": "Pharmacy",
        "customer_name": "Apollo Pharmacy",
        "product_name": "Amoxicillin Capsules",
        "product_strength": "500 mg",
        "batch_number": "AMX240602",
        "manufacturing_date": "March 2026",
        "expiry_date": "February 2028",
        "originating_site_block": "Block A - Oral Solids",
    }
    for field, want in expected.items():
        got = form.get(field)
        if got == want:
            record(PASS, f"{field} = {got!r}")
        else:
            record(WARN, f"{field}", f"expected {want!r}, got {got!r}")

    for field in ("complaint_category", "severity", "suggested_next_action",
                  "initial_risk_assessment"):
        if form.get(field):
            record(PASS, f"{field} reasoned", str(form[field])[:58])
        else:
            record(FAIL, f"{field} missing")

    # --- 5. no fabrication ------------------------------------------------
    print("\nNo fabrication")
    bare = post(
        f"{base}/api/ai/chat",
        {
            "message": "A pharmacy says some capsules look discoloured. Log it.",
            "history": [],
            "form": {},
        },
    )
    bare_form = bare.get("form_update", {})
    if bare_form.get("batch_number"):
        record(
            FAIL,
            "invented a batch number",
            f"{bare_form['batch_number']!r} - the prompt gave none",
        )
    else:
        record(PASS, "no batch number invented")

    # --- 6. routing: a question must not touch the form -------------------
    print("\nRouting")
    question = post(
        f"{base}/api/ai/chat",
        {
            "message": "What does Major severity mean in complaint triage?",
            "history": [],
            "form": {},
        },
    )
    if question.get("tool_called") is None and not question.get("form_update"):
        record(PASS, "question answered without touching the form")
    else:
        record(FAIL, "question wrongly triggered the tool")

    # --- 7. duplicate detection ------------------------------------------
    print("\nDuplicate detection")
    dupe = post(
        f"{base}/api/ai/chat",
        {
            "message": (
                "City Hospital reported visible floating particles in 3 vials of "
                "Ondansetron Injection 2 mg/mL, batch OND25B119. Please log this."
            ),
            "history": [],
            "form": {},
        },
    )
    found = (dupe.get("copilot") or {}).get("duplicates") or []
    if found:
        record(PASS, "duplicate detected", ", ".join(d["complaint_number"] for d in found))
    else:
        record(WARN, "no duplicate found", "did you run seed.py? CC-2026-0004 is the match")

    sev = (dupe.get("form_update") or {}).get("severity")
    if sev == "Critical":
        record(PASS, "particulate in a parenteral graded Critical")
    else:
        record(WARN, "severity for parenteral particulate", f"got {sev!r}, expected Critical")

    # --- summary ----------------------------------------------------------
    failed = [r for r in results if r[0] == FAIL]
    warned = [r for r in results if r[0] == WARN]
    print("\n" + "=" * 62)
    print(
        f"{len(results) - len(failed) - len(warned)} passed, "
        f"{len(warned)} warnings, {len(failed)} failed"
    )
    if failed:
        print("\nFailures:")
        for _, name, detail in failed:
            print(f"  - {name}" + (f": {detail}" if detail else ""))
    print()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
