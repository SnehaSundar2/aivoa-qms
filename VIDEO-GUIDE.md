# Recording the two submission videos

Two videos, 5–10 minutes each.

1. **Working demonstration** — the AI tools and frontend features in action.
2. **Code walkthrough** — one request traced end to end through the codebase.

Everything below is ordered for recording. Line numbers are exact as of the
current commit.

---

## Before you press record

**1. Check your Groq quota.** The free tier is 200,000 tokens per day and a
full complaint costs 3–5k. Confirm you have headroom:

```bash
Set-Location D:\aivoa-qms\backend; .\.venv\Scripts\python.exe smoke_test.py
```

You want **21 passed, 0 warnings, 0 failed**. If it reports *quota exhausted*,
stop — you cannot record video 1 usefully until it resets.

**2. Reset the data** so the duplicate detection demo works:

```bash
Set-Location D:\aivoa-qms\backend; .\.venv\Scripts\python.exe seed.py --reset
```

**3. Start both servers** in separate terminals, and leave the backend terminal
visible on a second monitor if you have one — the node trace in its log is
good evidence during video 2.

**4. Do one full dry run.** Log a complaint, edit it, commit it. Then
`seed.py --reset` again. You want to know how the model phrases things before
the camera is on, because it will not phrase them identically twice.

**5. Close everything else.** Browser tabs, notifications, Slack.

**6. Have `DEMO.md` open** in a second window to paste from. Do not type the
complaints live — it wastes 30 seconds each and you will typo the batch number.

---

## Video 1 — Working demonstration (target 7–8 min)

### 0:00–0:30 · What this is

> "This is a Customer Complaint module for a pharmaceutical Quality Management
> System — the part of a QMS that handles complaints about products the company
> manufactured, covering both APIs and finished dosage forms.
>
> Under 21 CFR 211.198 every complaint has to be recorded and investigated. The
> bottleneck is intake: complaints arrive as unstructured emails and a QA
> officer retypes them into a long form. That's slow, and a critical defect has
> a three-working-day Field Alert Report clock running."

Show the dashboard. Point at the seeded register and the counters.

### 0:30–2:30 · The headline case

Open **Log complaint**. Pause on the empty form for two seconds.

> "Every field says *Awaiting AI extraction*. I never type into this form — I
> talk to the copilot on the right, and it fills the record."

Paste from `DEMO.md` §1 (Apollo Pharmacy / Amoxicillin). While it runs:

> "That's the `log_complaint` tool — the mandatory AI tool. It's a LangGraph
> agent: triage, extraction, completeness, duplicate detection, risk
> assessment, root cause and CAPA in parallel, then a summary."

When it lands, walk the form slowly and call out the **four things that aren't
just copying**:

1. **"Amoxicillin Capsules" and "500 mg" are separate fields.** The message
   said them as one phrase; the schema needs them split.
2. **"March 2026" stayed verbatim.** *"The customer never gave a day. Converting
   this to a date would mean inventing one, and a fabricated date in a complaint
   record is a data-integrity violation. So the column is free text."*
3. **`Block A - Oral Solids` is inferred.** *"Nothing in the message says this.
   The agent knows capsules come from oral solids."*
4. **The risk assessment block** — severity, next action, and two sentences of
   reasoning about the probable mechanism.

> "Severity Major, not Minor. Discolouration of a capsule isn't cosmetic — it's
> a recognised indicator of degradation or moisture ingress, which can affect
> potency. That distinction is in the risk prompt."

Point at the green `log_complaint` chip and the pill flipping to **Ready to
Commit**.

### 2:30–3:30 · The edit tool

Paste `DEMO.md` §2, one at a time:

```
the affected quantity is actually 20 capsules
```
```
set severity to Critical
```

> "That's the second tool, `edit_complaint`. Note the fields flash green, and
> only the field I named changed."

Then the one that proves it's reasoning:

```
make it 25
```

> "'It' only resolves against the record — the agent knows we were discussing
> affected quantity. That's not pattern matching."

**Say the design point out loud.** It's the strongest thing in the project:

> "These two tools have opposite precedence rules. `log_complaint` fills gaps
> and never overwrites what the operator typed — it's guessing and they're not.
> `edit_complaint` overwrites, because the operator explicitly asked. Getting
> that backwards either way is a real bug: one silently discards their
> corrections, the other makes the edit tool useless exactly when you want it."

### 3:30–4:00 · A question must not touch the form

```
What does Major severity mean in pharmaceutical complaint triage?
```

> "No tool chip, no form change. The agent decided this was a question, not a
> complaint. That decision is *why* extraction is a tool rather than an
> unconditional step — and it's reported back so the operator can see which
> happened."

### 4:00–5:00 · Critical severity and duplicate detection

Paste `DEMO.md` §4 (Ondansetron particulate).

> "Critical, not Major. Particulate in an injectable is a different risk class
> from a chipped tablet — potential Class I recall, Field Alert Report inside
> three working days."

Point at the duplicate:

> "And it matched CC-2026-0004 in the existing register — same product, same
> batch. That's deterministic SQL scoring, not an LLM call, because a QMS has
> to give the same answer for the same input every time."

Point at the replacement notice:

> "It also replaced the form rather than merging, and told me which draft it
> discarded. Merging two complaints would produce a record describing neither."

### 5:00–6:00 · Uploads — PDF, email, image

Reset. Drag `backend/samples/complaint_email_particulate.pdf` onto the chat.

Then `complaint_html_only.eml`:

> "A real email — and an HTML-only one, which is what most corporate mail
> clients send. It's flattened to clean text before extraction."

Then `complaint_form_photo.jpg`:

> "And an image. This is a vision model, not OCR — which matters, because the
> most likely complaint image is a photograph of the *defect itself*.
> Discoloured capsules in a bottle contain no text at all, so OCR returns
> nothing for exactly the case that matters most."

### 6:00–6:45 · Not a complaint

Reset, paste `DEMO.md` §6 (the purchase order).

> "The form stays empty. Triage short-circuited straight to reject and the
> expensive nodes never ran."

### 6:45–7:30 · Commit and the audit trail

Press **Commit to QMS Ledger**, open the record.

> "Complaint number, and the audit trail: CREATED by the QA officer,
> AI_ASSESSMENT by ai.copilot, with the node path and both model names
> recorded. The assessment is attached as history and never overwritten — you
> can see how this complaint was assessed six months from now."

### 7:30–8:00 · Close on the honest bit

> "One thing I'd point out. The brief specifies `gemma2-9b-it` — Groq has
> decommissioned it, and `llama-3.3-70b-versatile` isn't available either. I
> found that from the API error, mapped onto the closest currently-served
> models, and added a startup check so a dead model fails loudly instead of
> silently falling back to rules — which is what it had been doing while the
> health endpoint still said everything was fine."

---

## Video 2 — Code walkthrough (target 8–9 min)

Trace **one** request. Do not tour the repo. Have these files open as tabs in
this order, and move top to bottom.

### 0:00–0:30 · State the path

Draw or say it:

> "I'm following one message: chat panel → Redux thunk → FastAPI endpoint →
> the tool → LangGraph → the coercion layer → back into the Redux form."

### 0:30–1:30 · Frontend input

**`frontend/src/components/CopilotChat.jsx:196`**

> "`submit` does two things: echoes the operator's message immediately so the
> UI doesn't feel dead, then dispatches the thunk."

**`frontend/src/features/chat/chatSlice.js:44`**

Show `sendMessage`, then scroll up to **line 28**, `formPayload`:

> "Every turn sends the *current form state* alongside the message. That's what
> lets the agent fill only the gaps and never overwrite what the operator
> typed. The rule lives on the backend, but it can only be honoured if the form
> travels with the request."

**`frontend/src/api/client.js:35`** — brief:

> "One fetch wrapper so error handling is uniform. FastAPI returns `detail` as
> either a string or a Pydantic validation array; flattening it here is how you
> avoid rendering `[object Object]` in a toast."

### 1:30–2:30 · The endpoint

**`backend/app/routers/ai.py:190`**

> "`POST /api/ai/chat`. Thin — validate and delegate."

Scroll to **line 201**, `chat_upload`:

> "The upload path extracts text from the PDF, email or image first, then joins
> the same turn handler. Note `is_upload=True` — a file drop is never an
> instruction to amend the record, however the document happens to be worded.
> I found that one the hard way: two of my sample emails contain the word
> 'correct', and were being routed to the edit tool."

### 2:30–3:30 · Routing

**`backend/app/services/chat.py:348`** — `handle_turn`.

Walk the three branches at **365**, **373**, **387**:

> "Edit first — with a populated form, 'the quantity is actually 20' is an
> amendment. Then a cheap keyword gate: a plain question never reaches the
> graph. Everything else goes to the agent, where triage makes the real
> decision.
>
> I had an LLM router here originally. I removed it — it duplicated the graph's
> own triage call for no added accuracy, and on a 200k-token daily budget every
> avoided call matters."

### 3:30–4:30 · The tool

**`backend/app/agent/tools.py:31`** — `LOG_COMPLAINT_TOOL`.

> "The tool definition. The description is what the model uses to decide
> whether to call it, and the parameters *are* the Pydantic schema — so the
> arguments are validated before anything reaches the form."

**Line 47**, `run_log_complaint` — point at the `existing` hint:

> "The operator's values are passed in and the prompt is told to treat them as
> correct."

**Line 98** — `EDIT_COMPLAINT_TOOL`, briefly, then back.

### 4:30–5:30 · The LLM layer

**`backend/app/agent/llm.py:227`** — `structured_call`.

Point at **line 257**:

> "`compact_schema` instead of `model_json_schema`. Pydantic's JSON Schema is
> correct but verbose — every `Optional[str]` becomes an `anyOf` block with a
> title and a default. For the 27-field complaint schema that was 2,050 tokens
> on *every* extraction call. The field spec carries the same information for
> about 770."

Scroll to **line 82**, `_is_transient`:

> "Failure classification. Groq's JSON mode intermittently rejects its own
> output with a 400 — about one call in three. I was treating any exception as
> 'the LLM is unavailable', so a third of runs silently fell back to rules
> while the health endpoint still said everything was green. Transient failures
> now retry; a decommissioned model or a bad key still fails on the first
> attempt, because retrying those only adds latency."

### 5:30–7:00 · The LangGraph workflow

**`backend/app/agent/graph.py:79`** — `build_graph`. Show the ASCII diagram in
the module docstring above it first.

Then walk the wiring:

- **line 93** — the conditional edge: *"triage routes non-complaints straight to reject, so the expensive nodes never run."*
- **lines 104–105** — *"risk fans out to root cause and CAPA. Genuinely parallel — they're independent but both need the severity."*
- **line 108** — *"and they join at the summary."*

**`backend/app/agent/state.py`** — the reducers:

> "`trace` and `degraded` carry reducers because both parallel branches write
> to them in the same superstep. Without that, LangGraph raises a concurrent
> update error — that was a real bug I hit."

**`backend/app/agent/nodes.py:105`** (`extract_node`) and **:205** (`risk_node`):

> "Every node follows the same contract: try the LLM, fall back to a rule on
> `LLMUnavailable`, return only the keys it owns. Nodes never raise — losing a
> customer complaint because a model timed out would be the worst failure mode
> this module has."

**`backend/app/agent/nodes.py:187`** — `duplicate_node`:

> "Duplicate detection is deliberately *not* an LLM call. Weighted feature
> scoring in SQL, so the same input always gives the same answer."

**Why a graph at all** — say this explicitly:

> "Extraction must be literal and conservative; risk assessment must reason and
> infer. Those are opposite instructions. One prompt asking for both gives you
> a model that invents fields to justify its risk score."

### 7:00–8:00 · Coercion — the safety layer

**`backend/app/services/copilot.py:121`** — `_build_prefill`.

This is the part most candidates won't have. Spend time on it.

> "This sits between the model and the form. Dates are parsed against ten
> formats and dropped if implausible. Anything backed by a dropdown is snapped
> to its controlled vocabulary or dropped entirely.
>
> That last one came from a real bug. The model returned
> `complaint_source: 'Apollo Pharmacy'` — the customer, not the channel. It
> isn't a valid dropdown option, so the select rendered *blank* while the value
> still counted as populated. The operator would have seen an empty field and
> committed a value they never read.
>
> The principle is: a blank field an operator fills in beats a plausible wrong
> one they don't notice."

### 8:00–8:45 · Back into the form

**`frontend/src/features/form/formSlice.js:210`** — `prefillFromChat`, then
**line 141** — `applyPrefill`:

> "Here's the precedence rule in code. `overwrite` is an explicit flag, not an
> inference. A log fills gaps; an edit overwrites. And `replace_form` clears
> the draft first when the incoming source is a *different* complaint."

**`frontend/src/components/Field.jsx:29`** — `useField`:

> "Every field knows whether its value came from the agent. That drives the AI
> badge, the one-click reject, and the rule that a re-run can't overwrite
> something a human typed. In a regulated record, an operator has to be able to
> see which values they're taking responsibility for."

### 8:45–9:00 · Close

> "Workflow status and assignment are on a never-prefill list — those are human
> decisions. The agent proposes; the QA officer disposes."

---

## Delivery notes

**Say the trade-offs out loud.** Every "I chose X because Y, and the cost is Z"
is worth more than another feature. The strongest three:

- Duplicate detection is deterministic, not an LLM call — reproducibility.
- The coercion layer drops values rather than guessing — a blank beats a wrong.
- `complaint_category` is free text to match the reference UI, which means it's
  **not** safe to trend on. Severity and product type stay controlled. Name
  this one unprompted; admitting a known limitation reads as judgement.

**Mention what you'd do next, briefly:** Part 11 electronic signatures, RBAC,
Alembic migrations instead of `create_all`, and duplicate detection moving to a
Postgres trigram index or pgvector at scale. All four are in the README's
limitations section.

**Don't hide a degraded run.** If the quota runs out mid-recording, say so:
*"That's the fallback — the model is unavailable so it's running deterministic
rules, and notice the UI labels it rule-based rather than passing it off as an
AI assessment."* That's a feature, and handling it calmly on camera looks
better than a retake.

**Keep the mouse still** when you're talking about code. Highlight the lines
you're discussing rather than scrolling.
