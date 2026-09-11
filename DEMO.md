# AIVOA Copilot — demo script

Ready-to-paste content for the AIVOA Copilot chat panel, ordered as a video
run-through. Each step says what to point out.

Start the app, open <http://localhost:5173/log>, and check the top-right badge
reads **Groq connected**. Run `python seed.py --reset` first — duplicate
detection has nothing to match against on an empty register.

---

## 1. The headline case — a complaint the AI fully understands

Paste into the copilot:

```
Apollo Pharmacy reported 12 discolored capsules in a sealed bottle of Amoxicillin Capsules 500 mg. Batch number AMX240602. Manufacturing date March 2026. Expiry date February 2028. They are requesting investigation and replacement. Please log this complaint
```

**Point out:**
- The form fills itself — you never type into it.
- `Amoxicillin Capsules` and `500 mg` are split into separate fields.
- `March 2026` stays verbatim. It is not converted to a date, because the
  customer never gave a day and inventing one would be fabrication.
- `Block A - Oral Solids` is **inferred** from the dosage form — capsules come
  from oral solids. Nothing in the message says this.
- The AI Copilot Risk Assessment block: severity **Major**, a suggested next
  action, and two sentences of reasoning about the probable mechanism.
- The pill flips **Pending Triage → Ready to Commit**.
- The green `log_complaint` chip in the chat, with the latency.

---

## 2. Editing by conversation — the second tool

With that complaint still on screen:

```
the affected quantity is actually 20 capsules
```

```
change the batch number to AMX240603
```

```
set severity to Critical
```

**Point out:**
- Changed fields flash green.
- A blue `edit_complaint` chip, and "N fields updated".
- Only the named field changes — nothing else is touched.
- The two tools have **opposite precedence rules**: `log_complaint` fills gaps
  and never overwrites what you typed; `edit_complaint` overwrites, because you
  explicitly asked. Type something into a field by hand, then ask the copilot to
  change it — it obeys.

A loose instruction, to show it resolves references against the record:

```
make it 25
```

---

## 3. Questions don't touch the form

```
What does Major severity mean in pharmaceutical complaint triage?
```

```
Why would discolouration be treated as more than a cosmetic defect?
```

**Point out:**
- No tool chip, no form change. The agent decided this was a question.
- That decision is why extraction is a *tool* and not an unconditional step.

---

## 4. Critical severity, and duplicate detection

```
City Hospital pharmacy reported visible floating particles in 3 vials of Ondansetron Injection USP 2 mg/mL, batch OND25B119, expiry May 2028. Withheld from use and available for return. Please log this complaint
```

**Point out:**
- Graded **Critical**, not Major — particulate in a parenteral is a different
  risk class from a chipped tablet.
- Flagged reportable, citing the FDA Field Alert Report route.
- **Duplicate detected: CC-2026-0004** — the seeded history contains the same
  product and batch. This is deterministic SQL scoring, not an LLM call, so the
  same input always gives the same answer.
- Because a complaint was already on screen, the form is **replaced, not
  merged**, and the reply says which draft was discarded.

---

## 5. An incomplete complaint — the completeness checker

Reset first, then:

```
A pharmacy called to say some of our cough syrup has gone cloudy with something settled at the bottom. Customers have returned two bottles. Please log it.
```

**Point out:**
- No batch number, so nothing can be traced — the record cannot leave Draft.
- The copilot asks for exactly what is missing, phrased so the customer can
  answer it.
- It does **not** invent a batch number. A fabricated batch in a complaint
  record is a data-integrity violation.

Then supply the missing detail conversationally:

```
they've come back with the details - batch PCM24H221, expiry October 2027, and it's Paracetamol Oral Suspension 250 mg/5 mL
```

---

## 6. Not a complaint — triage short-circuits

Reset, then:

```
Please find our purchase order VD-2026-11042 for Q4 replenishment. 800 packs of Metformin 500 mg, 1,500 bottles of Paracetamol suspension. Kindly confirm the despatch date and ensure the Certificate of Analysis accompanies each consignment.
```

**Point out:**
- The form stays **empty**. This is a purchase order, not a complaint.
- The node trace shows `triage → reject` — the expensive nodes never ran.

---

## 7. File uploads — PDF, email, image

Use the paperclip, or drag onto the chat panel. Files are in `backend/samples/`.

| File | Shows |
|---|---|
| `complaint_email_particulate.pdf` | PDF text extraction, Critical grading, duplicate hit |
| `complaint_email_api_oos.pdf` | An **API** complaint rather than a finished product — out of specification impurities |
| `complaint_plain.eml` | A real email with headers |
| `complaint_html_only.eml` | An HTML-only email, flattened to clean text |
| `complaint_with_attachment.eml` | Multipart — the attachment is listed by name |
| `complaint_form_photo.jpg` | **A photographed complaint form read by a vision model** |
| `not_a_complaint_purchase_order.pdf` | Triage rejection from a document |

**Point out on the image:** this is a vision model, not OCR. It handles a
photograph of the *defect itself* — discoloured capsules in a bottle — where
OCR would return nothing, because there is no text in that picture.

---

## 8. Saving the record

Press **Commit to QMS Ledger**, then open the record.

**Point out:**
- The complaint number, `CC-2026-00NN`.
- The **audit trail**: `CREATED` by the QA officer, `AI_ASSESSMENT` by
  `ai.copilot`, with the node path and both model names recorded.
- The attached assessment: severity, root causes, CAPA, duplicates — kept as
  history and never overwritten.

---

## 9. Graceful degradation (optional, and a strong point)

Stop the backend, blank `GROQ_API_KEY` in `backend/.env`, restart, and log a
complaint.

**Point out:**
- It still works. Every node falls back to a deterministic rule.
- The result is labelled **rule-based** in the chat and a banner appears — an
  operator is never led to believe a keyword match was an AI assessment.
- The node trace marks which steps used rules.

Losing a customer complaint because a model timed out would be the worst
failure mode this module has. So would an operator mistaking a keyword match
for reasoning. Both are handled.

---

## Extra prompts, if you need more material

Adverse event — the highest severity path:

```
Mercy General Hospital reported that a patient developed a severe skin rash within two hours of receiving Cefixime Tablets 200 mg, batch CFX25G401, expiry March 2028. The patient was admitted for observation. Please log this complaint urgently.
```

Cold chain excursion:

```
Iberia Pharma Logistics reported a temperature excursion on Insulin Glargine 100 IU/mL, batch ING25C042. Data logger recorded 11.4 degrees C for 6 hours 20 minutes during a customs hold against a 2-8 degrees storage requirement. One pallet of 300 pens quarantined on arrival. Please log this.
```

Labelling defect:

```
Accra Central Pharmacy reported that the overprinted batch number and expiry on one carton of Metformin Hydrochloride Tablets IP 500 mg, batch MTF25D088, are smudged and unreadable. The blister foil inside is legible. One carton affected, returned to us.
```

Suspected falsified product — triggers the most severe classification:

```
A wholesaler in Lagos reports receiving Azithromycin Tablets 500 mg in cartons where the hologram does not match our artwork and the batch number AZT25X999 does not appear in our records. Please log this immediately.
```
