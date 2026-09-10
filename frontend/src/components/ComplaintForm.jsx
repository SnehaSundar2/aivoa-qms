/** The "Log Customer Complaint" record form. */
import { useSelector } from 'react-redux'

import { selectMeta } from '../features/meta/metaSlice'
import { CheckField, DateField, SelectField, TextArea, TextField } from './Field'

export default function ComplaintForm() {
  const meta = useSelector(selectMeta)
  const aiFilledCount = useSelector((state) => state.form.aiFilled.length)

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>Log Customer Complaint</h2>
          <div className="sub">
            Fields marked <span className="required-dot">*</span> are required
            before the complaint can leave Draft
          </div>
        </div>
        {aiFilledCount > 0 && (
          <span className="badge badge-ai">
            ✦ {aiFilledCount} field{aiFilledCount === 1 ? '' : 's'} AI-filled
          </span>
        )}
      </div>

      <div className="card-body">
        <div className="section-title">Complainant</div>
        <div className="field-row">
          <TextField name="complainant_name" label="Contact name" required />
          <TextField
            name="complainant_organisation"
            label="Organisation"
            required
          />
        </div>
        <div className="field-row-3">
          <TextField name="complainant_email" label="Email" type="email" />
          <TextField name="complainant_phone" label="Phone" />
          <TextField name="country" label="Country" />
        </div>

        <div className="section-title" style={{ marginTop: 20 }}>
          Product
        </div>
        <div className="field-row">
          <TextField name="product_name" label="Product name" required />
          <TextField name="product_code" label="Product / material code" />
        </div>
        <div className="field-row-3">
          <SelectField
            name="product_type"
            label="Product type"
            options={meta.productTypes}
          />
          <TextField name="dosage_form" label="Dosage form" />
          <TextField name="strength" label="Strength" />
        </div>
        <div className="field-row-3">
          <TextField name="batch_number" label="Batch / lot number" required />
          <DateField name="manufacturing_date" label="Manufacturing date" />
          <DateField name="expiry_date" label="Expiry date" />
        </div>
        <div className="field-row-3">
          <TextField name="pack_size" label="Pack size" />
          <TextField name="quantity_supplied" label="Quantity supplied" />
          <TextField name="quantity_complained" label="Quantity affected" />
        </div>

        <div className="section-title" style={{ marginTop: 20 }}>
          Complaint
        </div>
        <div className="field-row">
          <DateField
            name="date_of_complaint"
            label="Date of complaint"
            required
          />
          <DateField name="date_received" label="Date received" />
        </div>
        <div className="field-row">
          <SelectField
            name="complaint_category"
            label="Category"
            options={meta.categories}
            required
          />
          <TextField name="complaint_subcategory" label="Sub-category" />
        </div>
        <TextArea
          name="complaint_description"
          label="Description of the defect"
          rows={5}
          required
          hint="A factual account of what the customer observed. No root-cause speculation at intake."
        />
        <div className="field-row">
          <CheckField
            name="sample_available"
            label="Sample available for investigation"
          />
          <TextField name="sample_quantity" label="Sample quantity" />
        </div>

        <div className="section-title" style={{ marginTop: 20 }}>
          Triage &amp; workflow
        </div>
        <div className="field-row-3">
          <SelectField
            name="severity"
            label="Severity"
            options={meta.severities}
            hint="Confirm or override the AI classification"
          />
          <SelectField name="status" label="Status" options={meta.statuses} />
          <DateField name="due_date" label="Investigation due" />
        </div>
        <div className="field-row">
          <SelectField
            name="department"
            label="Owning department"
            options={meta.departments}
          />
          <TextField name="assigned_to" label="Assigned to" />
        </div>
        <div className="field-row">
          <CheckField
            name="investigation_required"
            label="Investigation required"
          />
          <CheckField
            name="regulatory_reportable"
            label="Potentially reportable to a health authority"
          />
        </div>
        <TextArea
          name="regulatory_rationale"
          label="Regulatory rationale"
          rows={3}
        />
      </div>
    </div>
  )
}
