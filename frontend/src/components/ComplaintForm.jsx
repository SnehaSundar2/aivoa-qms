/**
 * The "Log Customer Complaint" record.
 *
 * Deliberately read-mostly. The operator drives this through the copilot
 * chat, so every field opens with an "Awaiting AI extraction…" placeholder and
 * fills in as the agent works. They can still correct anything by hand — and
 * when they do, that field is marked as theirs and the agent stops touching it.
 */
import { useSelector } from 'react-redux'

import { selectMeta } from '../features/meta/metaSlice'
import { CheckField, SelectField, TextArea, TextField } from './Field'

const AWAIT_TEXT = 'Awaiting AI extraction...'
const AWAIT_CLASS = 'Awaiting AI classification...'

function ShieldIcon() {
  return (
    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" aria-hidden="true">
      <path
        d="M12 3l7 2.6v5c0 4.4-2.9 8.3-7 9.4-4.1-1.1-7-5-7-9.4v-5L12 3Z"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
      <path
        d="m9 12 2.2 2.2L15.5 10"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export default function ComplaintForm() {
  const meta = useSelector(selectMeta)
  const values = useSelector((state) => state.form.values)
  const hasAssessment = Boolean(values.severity || values.initial_risk_assessment)

  return (
    <div className="record">
      <div className="record-section">
        <div className="record-step">1. Origin &amp; Customer Details</div>
        <div className="field-row">
          <SelectField
            name="complaint_source"
            label="Complaint Source"
            options={meta.complaintSources}
            placeholder={AWAIT_CLASS}
          />
          <TextField
            name="customer_name"
            label="Customer Name"
            placeholder={AWAIT_TEXT}
          />
        </div>
      </div>

      <div className="record-section">
        <div className="record-step">2. Product &amp; Batch Identification</div>
        <div className="field-row">
          <TextField
            name="product_name"
            label="Product Name (API/FDF)"
            placeholder={AWAIT_TEXT}
          />
          <TextField
            name="product_strength"
            label="Product Strength"
            placeholder={AWAIT_TEXT}
          />
        </div>
        <div className="field-row">
          <TextField
            name="batch_number"
            label="Batch / Lot Number"
            placeholder={AWAIT_TEXT}
          />
          <TextField
            name="affected_quantity"
            label="Affected Quantity"
            placeholder={AWAIT_TEXT}
          />
        </div>
        <div className="field-row">
          {/* Free text, not a date picker: the customer writes "March 2026"
              and the record shows exactly that. */}
          <TextField
            name="manufacturing_date"
            label="Manufacturing Date"
            placeholder={AWAIT_TEXT}
          />
          <TextField
            name="expiry_date"
            label="Expiry Date"
            placeholder={AWAIT_TEXT}
          />
        </div>
      </div>

      <div className="record-section">
        <div className="record-step">3. Facility &amp; Material Impact</div>
        <div className="field-row">
          <SelectField
            name="originating_site_block"
            label="Originating Site Block"
            options={meta.siteBlocks}
            placeholder={AWAIT_CLASS}
          />
          <TextField
            name="impacted_npm"
            label="Impacted Non-Product Materials (NPM)"
            placeholder="e.g., Primary packaging..."
          />
        </div>
      </div>

      <div className="record-section">
        <div className="record-step">4. Defect Analysis</div>
        <TextField
          name="complaint_category"
          label="Complaint Category"
          placeholder={AWAIT_CLASS}
        />
        <TextArea
          name="complaint_description"
          label="Structured Defect Summary"
          rows={4}
          placeholder="AI will synthesize the complaint into a formal QMS description..."
        />
      </div>

      <div className={`risk-box${hasAssessment ? ' is-active' : ''}`}>
        <div className="risk-box-head">
          <ShieldIcon />
          AI Copilot Risk Assessment
        </div>
        <div className="field-row">
          <SelectField
            name="severity"
            label="Severity (Suggested)"
            options={meta.severities}
            placeholder={AWAIT_CLASS}
          />
          <TextField
            name="suggested_next_action"
            label="Suggested Next Action"
            placeholder={AWAIT_CLASS}
          />
        </div>
        <TextArea
          name="initial_risk_assessment"
          label="Initial Risk Assessment"
          rows={3}
          placeholder="AI will reason about the probable mechanism and what it requires..."
        />
        <div className="field-row">
          <CheckField
            name="regulatory_reportable"
            label="Potentially reportable to a health authority"
          />
          <CheckField name="investigation_required" label="Investigation required" />
        </div>
      </div>
    </div>
  )
}
