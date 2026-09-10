# AI-Powered Customer Complaint Management System

A Customer Complaint module for a pharmaceutical Quality Management System, covering
both **API** (Active Pharmaceutical Ingredient) and **FDF** (Finished Dosage Form)
manufacturing.

An incoming complaint — an email, a PDF, a scanned form, a phone note — is read by a
**LangGraph** agent running on **Groq**, which extracts the structured record, triages
it against ICH Q9 risk-management principles, checks it for completeness, looks for
duplicates in the complaint history, proposes probable root causes and CAPA, and
writes a summary. The result populates the *Log Customer Complaint* form and the
*AI Copilot · Risk Assessment* panel, where a QA officer confirms or overrides
everything before it is saved.

---

## Table of contents

- [Why a complaint module needs this](#why-a-complaint-module-needs-this)
- [Architecture](#architecture)
- [The agent graph](#the-agent-graph)
- [Quick start](#quick-start)
- [Demo script](#demo-script)
- [API reference](#api-reference)
- [Design decisions](#design-decisions)
- [Testing](#testing)
- [Project layout](#project-layout)
- [Known limitations](#known-limitations)

---

## Why a complaint module needs this

Under **21 CFR 211.198** and **EU GMP Chapter 8**, a manufacturer must record and
investigate every complaint about a product's identity, quality, durability,
reliability, safety, effectiveness or performance. The record must be attributable and
retained, and the investigation must run to a defined timeline. **ICH Q10** adds that
complaints feed the corrective and preventive action (CAPA) system.

The bottleneck in practice is intake. Complaints arrive as unstructured prose from
customers who do not know the QMS field names, and a QA officer retypes them into a
long form. Two things go wrong:

1. **Slow triage.** A critical defect — particulate in an injectable, a wrong active
   ingredient — has a 3-working-day FDA Field Alert Report clock that starts at
   awareness. Time in an intake queue is time off that clock.
2. **Incomplete records.** The batch number is missing, so nothing can be traced, and
   the customer has to be chased days later.

This system attacks both: the agent drafts the structured record in seconds and
assigns a preliminary severity, and a completeness checker generates the exact
questions to put back to the customer while they are still on the phone.

**It does not make decisions.** Every AI value is labelled in the UI, every one can be
rejected with one click, and the workflow status and assignment are never auto-filled.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  React 19 + Redux Toolkit  (Vite, Inter)                         │
│                                                                  │
│   IntakePanel ──▶ copilotSlice ──▶ formSlice ──▶ ComplaintForm   │
│        │              │                              ▲           │
│        │              └──────────▶ CopilotPanel      │           │
│        │                     (risk, RCA, CAPA)  provenance:      │
│        │                                        which fields     │
│        │                                        the AI filled    │
└────────┼─────────────────────────────────────────────────────────┘
         │  POST /api/ai/intake/{text,file}
┌────────▼─────────────────────────────────────────────────────────┐
│  FastAPI                                                         │
│    routers/ai.py ──▶ services/copilot.py ──▶ agent/graph.py      │
│                            │                       │             │
│                            │  coercion layer       │  LangGraph  │
│                            │  (dates, enums)       ▼             │
│                            │                   Groq LLM          │
│                            │                gemma2-9b-it +       │
│                            │           llama-3.3-70b-versatile   │
│                            ▼                                     │
│                    services/duplicates.py (deterministic SQL)    │
│    routers/complaints.py ──▶ SQLAlchemy ──▶ PostgreSQL           │
└──────────────────────────────────────────────────────────────────┘
```

| Layer | Choice | Notes |
|---|---|---|
| Frontend | React 19, Redux Toolkit, React Router | Inter via Google Fonts |
| Backend | FastAPI, Pydantic v2, SQLAlchemy 2.0 | |
| Agent | LangGraph | 9 nodes, conditional routing, parallel branch |
| LLM | Groq `gemma2-9b-it` + `llama-3.3-70b-versatile` | routed per node |
| Database | PostgreSQL (MySQL supported) | SQLite auto-fallback for zero-setup demo |

---

## The agent graph

```
                        ┌──────────┐
                        │  triage  │   is this a complaint at all?
                        └────┬─────┘
                  not a complaint │ complaint
                   ┌─────────────┴──────────────┐
                   ▼                            ▼
              ┌────────┐                  ┌─────────┐
              │ reject │                  │ extract │   unstructured → fields
              └───┬────┘                  └────┬────┘
                  │                            ▼
                  │                  ┌────────────────────┐
                  │                  │ check_completeness │  what is missing?
                  │                  └─────────┬──────────┘
                  │                            ▼
                  │                  ┌───────────────────┐
                  │                  │ detect_duplicates │  seen this before?
                  │                  └─────────┬─────────┘
                  │                            ▼
                  │                     ┌─────────────┐
                  │                     │ assess_risk │  ICH Q9 triage
                  │                     └──────┬──────┘
                  │              ┌─────────────┴─────────────┐  parallel
                  │              ▼                           ▼
                  │   ┌────────────────────┐         ┌────────────────┐
                  │   │ analyse_root_cause │         │ recommend_capa │
                  │   └─────────┬──────────┘         └───────┬────────┘
                  │             └─────────────┬──────────────┘  join
                  │                           ▼
                  │                    ┌───────────────┐
                  │                    │ write_summary │
                  │                    └───────┬───────┘
                  └───────────────┬────────────┘
                                  ▼
                                 END
```

**Why a graph and not one large prompt.**

- **Separation of concerns.** Extraction must be literal and conservative; risk
  assessment must reason and infer. A single prompt asking for both produces a model
  that invents fields to justify its risk score.
- **Model routing.** `gemma2-9b-it` is fast and cheap, and handles triage, extraction,
  question phrasing and the summary. `llama-3.3-70b-versatile` handles the three
  judgement calls: severity, root cause, CAPA.
- **Independent failure.** If CAPA generation times out, the operator still gets the
  extracted record and the risk assessment.
- **Auditability.** Each node's contribution is recorded separately, and the executed
  node path is returned to the UI and stored with the assessment.

**Bonus features from the brief, and where they live:**

| Feature | Implementation |
|---|---|
| Complaint Completeness Checker | `check_completeness` — deterministic field check, LLM phrases the customer questions |
| Root Cause Recommendation | `analyse_root_cause` — 3–5 hypotheses in Ishikawa buckets, each with a first investigation step |
| Duplicate Complaint Detection | `detect_duplicates` — weighted feature scoring in SQL, no LLM |
| CAPA Recommendation | `recommend_capa` — typed Correction / Corrective / Preventive with owner and target |
| Complaint Summary | `write_summary` — QP-facing paragraph |
| AI Risk Classification | `assess_risk` — Critical/Major/Minor + 0–100 score + reportability |
| *(extra)* Non-complaint triage | `triage` — short-circuits purchase orders and enquiries |
| *(extra)* Re-assess after edits | `POST /api/ai/reassess` — operator values are locked, agent fills only gaps |

---

## Quick start

**Prerequisites:** Python 3.11+, Node 20+, and optionally Docker for PostgreSQL.

### 1. Database

```bash
docker compose up -d
```

Skip this if you like — the backend falls back to a local SQLite file and says so
loudly in the log.

### 2. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # add your GROQ_API_KEY
python seed.py                   # 6 historical complaints, needed for duplicate detection
python make_sample_pdfs.py       # turn the sample emails into PDFs

uvicorn app.main:app --reload
```

API on `http://localhost:8000`, interactive docs at `http://localhost:8000/docs`.

Get a Groq key at <https://console.groq.com/keys>. **Without a key the app still runs**
— every LLM node falls back to deterministic rules, and the UI labels the result as
rule-based rather than passing it off as an AI assessment.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

App on `http://localhost:5173`.

---

## Demo script

Sample source documents are in `backend/samples/`, as both `.txt` and `.pdf`.

1. **Critical defect, with a duplicate.** Upload `complaint_email_particulate.pdf`.
   → Classified **Critical (88–95)**, flagged reportable under 21 CFR 314.81(b)(1)(ii),
   and the duplicate detector matches **CC-2026-0004** — same product and batch, seeded
   in the complaint history. 16 form fields populate.

2. **API out-of-specification.** Upload `complaint_email_api_oos.pdf`.
   → **Major**, category *Analytical / Out of Specification*, root causes covering
   method, transport degradation and process variability.

3. **Incomplete complaint.** Upload `complaint_email_incomplete.pdf`.
   → Low completeness score, no batch number, and specific clarifying questions to put
   back to the customer.

4. **Not a complaint.** Upload `not_a_complaint_purchase_order.pdf`.
   → `triage` short-circuits to `reject`. The form stays empty and the expensive nodes
   never run — visible in the node trace at the bottom of the copilot panel.

5. **Human override.** Change a field the AI filled — its purple "AI" tag disappears.
   Press **Re-assess**: the agent re-runs but is forbidden from overwriting anything
   you typed.

6. **Save.** Fill the remaining mandatory fields and save. Open the record: the
   assessment is attached, and the audit trail shows `CREATED` and `AI_ASSESSMENT`.

---

## API reference

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/ai/intake/text` | Run the agent over pasted text |
| `POST` | `/api/ai/intake/file` | Run the agent over a PDF / EML / image / text upload |
| `POST` | `/api/ai/reassess` | Re-run against the edited form, preserving operator values |
| `GET` | `/api/ai/health` | Whether Groq is configured, and which models |
| `GET` | `/api/ai/graph` | The compiled graph as Mermaid |
| `GET` | `/api/complaints` | List, with `q` / `status` / `severity` / `category` filters |
| `POST` | `/api/complaints` | Create a complaint |
| `GET` | `/api/complaints/{id}` | One complaint |
| `PATCH` | `/api/complaints/{id}` | Update, writing an audit entry |
| `POST` | `/api/complaints/{id}/assessment` | Attach a copilot run to the record |
| `GET` | `/api/complaints/{id}/assessments` | Assessment history, newest first |
| `GET` | `/api/complaints/{id}/audit` | Audit trail |
| `GET` | `/api/complaints/stats` | Dashboard counters |
| `GET` | `/api/complaints/metadata` | Controlled vocabularies for the form dropdowns |

---

## Design decisions

**The model never has the last word.** Every AI-filled field is tinted and tagged in
the form, with a one-click reject. Workflow status, assignee and owning department are
on a never-prefill list — those are human decisions. The count of AI-filled fields is
shown before saving.

**A blank field beats a plausible wrong one.** `services/copilot.py` coerces model
output before it reaches the form: dates are parsed against ten formats and rejected if
implausible; categories are snapped to the exact enum or dropped. An operator fills in
a blank; they may never notice a confidently wrong batch number.

**Duplicate detection is deterministic, not an LLM call.** A QMS must give the same
answer for the same input every time. Candidates are scored on batch match, product
match, category match, description similarity and recency, and a human confirms.

**Degradation is visible, never silent.** Every node catches `LLMUnavailable` and falls
back to a rule. The run is then flagged `degraded`, the panel shows a warning banner,
and the node trace marks which steps used rules. Losing a complaint because a model
timed out would be the worst possible failure mode for this module — but so would an
operator mistaking a keyword match for an AI assessment.

**Under-triage is the dangerous error.** When the rules find no decisive keyword they
default to **Major**, not Minor, and the risk prompt tells the model to err toward the
higher severity when genuinely uncertain.

**One schema, three uses.** The Pydantic models in `app/schemas.py` validate the API,
generate the JSON Schema handed to the LLM, and define the shape the Redux store
mirrors. They cannot drift apart.

**Prompts are pinned to the domain.** A generic "extract fields from this text" prompt
produces unusable output for a regulated process — it guesses batch numbers and invents
categories that do not exist in the master data. Each prompt in `app/agent/prompts.py`
carries a role, a controlled vocabulary and an explicit no-fabrication rule.

---

## Testing

```bash
cd backend && pytest -q      # 65 tests
```

Covers the JSON extraction and schema-repair loop against a stub Groq client (the paths
that cannot be exercised in CI against the real API), date and enum coercion, graph
wiring and routing, the operator-override merge rule, and the severity heuristics.

```bash
cd frontend && npm run lint && npm run build
```

---

## Project layout

```
backend/
  app/
    agent/
      graph.py         LangGraph wiring: nodes, conditional edges, parallel branch
      nodes.py         One function per node; each falls back rather than raising
      prompts.py       Domain-grounded system prompts
      heuristics.py    Deterministic fallbacks used when Groq is unavailable
      llm.py           Groq client, strict JSON output, one repair round-trip
      state.py         Shared state with reducers for the parallel branch
    core/
      config.py        Environment-driven settings
      database.py      Engine with the SQLite fallback
      enums.py         Controlled vocabularies
    routers/
      ai.py            Intake and re-assess endpoints
      complaints.py    CRUD, stats, assessments, audit
    services/
      copilot.py       Graph invocation + coercion into form fields
      documents.py     PDF / EML / image / text extraction
      duplicates.py    Weighted duplicate scoring
    models.py          ORM: Complaint, RiskAssessment, AuditEntry
    schemas.py         Pydantic contracts
  samples/             Realistic complaint documents for the demo
  seed.py              Six historical complaints
  tests/               65 tests

frontend/src/
  api/client.js        Fetch wrapper with uniform FastAPI error handling
  app/store.js         Redux store
  features/
    copilot/           Agent result and intake status
    form/              Form values + which fields the AI filled
    complaints/        Register, stats, detail
    meta/              Controlled vocabularies, AI health
  components/
    IntakePanel.jsx    Drop zone and paste box
    ComplaintForm.jsx  The Log Customer Complaint record
    CopilotPanel.jsx   Risk assessment, duplicates, RCA, CAPA, trace
    Field.jsx          Inputs with AI provenance tags
  pages/
    DashboardPage.jsx  Complaint register
    LogComplaintPage.jsx
    ComplaintDetailPage.jsx
```

---

## Known limitations

- **Not validated for GxP use.** No electronic signatures (21 CFR Part 11), no user
  authentication, no role-based access control, and the audit trail is minimal. A real
  deployment needs all four, plus Alembic migrations under change control instead of
  `create_all`.
- **OCR is optional and basic.** Scanned PDFs have no text layer and are rejected with
  a message telling the operator what to do instead. Image intake needs `pytesseract`
  plus the Tesseract binary; without them, images are refused rather than silently
  producing nothing. The brief states production-grade OCR is not required.
- **Duplicate detection is linear.** It narrows in SQL then scores in Python, which is
  fine for a demo-sized register. At scale this belongs in a Postgres trigram index or
  a pgvector similarity search.
- **Complaint numbering is not concurrency-safe.** It counts existing rows for the
  year; two simultaneous saves could race. A production system would use a database
  sequence.
- **The SQLite fallback is a convenience, not a supported configuration.** It exists so
  the project runs immediately after cloning. Set `ALLOW_SQLITE_FALLBACK=false` to make
  an unreachable database a hard failure.
- **Hard delete exists for demo convenience.** A real QMS cancels a complaint with a
  reason and retains it for the statutory period.
