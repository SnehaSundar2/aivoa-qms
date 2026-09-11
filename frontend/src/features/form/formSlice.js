/**
 * The "Log Customer Complaint" form.
 *
 * The interesting part is provenance. For every field we track whether the
 * current value came from the AI or from the operator, because a QMS record
 * has to be attributable. That drives:
 *   - the "AI" badge next to auto-filled inputs,
 *   - the rule that a copilot re-run may fill blanks but must never overwrite
 *     something a human typed,
 *   - the count of AI-filled fields shown before saving.
 */
import { createAsyncThunk, createSelector, createSlice } from '@reduxjs/toolkit'

import { api, endpoints } from '../../api/client'
import { sendFile, sendMessage } from '../chat/chatSlice'
import { ingestFile, ingestText, reassess } from '../copilot/copilotSlice'

export const EMPTY_FORM = {
  // 1. Origin & customer details
  complaint_source: '',
  customer_name: '',
  complainant_name: '',
  complainant_email: '',
  complainant_phone: '',
  country: '',

  // 2. Product & batch identification
  product_name: '',
  product_strength: '',
  product_code: '',
  product_type: '',
  dosage_form: '',
  pack_size: '',
  batch_number: '',
  affected_quantity: '',
  quantity_supplied: '',
  // Free text, not dates: "March 2026" is preserved as written.
  manufacturing_date: '',
  expiry_date: '',

  // 3. Facility & material impact
  originating_site_block: '',
  impacted_npm: '',

  // 4. Defect analysis
  date_of_complaint: '',
  date_received: '',
  complaint_category: '',
  complaint_subcategory: '',
  complaint_description: '',
  sample_available: false,
  sample_quantity: '',

  // AI Copilot risk assessment
  suggested_next_action: '',
  initial_risk_assessment: '',

  severity: '',
  risk_score: null,
  status: 'Draft',
  assigned_to: '',
  department: '',
  investigation_required: true,
  due_date: '',
  regulatory_reportable: false,
  regulatory_rationale: '',

  source_type: '',
  source_reference: '',
  source_text: '',
  ai_assisted: false,
  ai_summary: '',
}

export const saveComplaint = createAsyncThunk(
  'form/save',
  async (_, { getState, rejectWithValue }) => {
    const { values } = getState().form
    // The conversational copilot stores its assessment in the chat slice; the
    // older intake panel used copilot.result. Prefer the chat, fall back to
    // the other, so the assessment is attached either way - losing it means a
    // complaint is committed with no record of how it was assessed.
    const copilotResult = getState().chat.copilot ?? getState().copilot.result

    // Empty strings must become null - the API expects dates and optional
    // fields to be absent, not "".
    const payload = Object.fromEntries(
      Object.entries(values).map(([key, value]) => [
        key,
        value === '' ? null : value,
      ]),
    )

    try {
      const complaint = await api.post(endpoints.complaints, payload)

      // Persist the copilot run against the saved record so the assessment is
      // part of the audit trail, not just something that flashed on screen.
      if (copilotResult) {
        try {
          await api.post(
            `${endpoints.complaints}/${complaint.id}/assessment`,
            copilotResult,
          )
        } catch {
          // The complaint is saved; failing to attach the assessment must not
          // present itself to the user as a failed save.
        }
      }
      return complaint
    } catch (error) {
      return rejectWithValue(error.message)
    }
  },
)

const initialState = {
  values: { ...EMPTY_FORM },
  /** Fields whose current value came from the agent. */
  aiFilled: [],
  /** Fields the operator has typed in since the last AI run. */
  userEdited: [],
  saveStatus: 'idle',
  saveError: null,
  savedComplaint: null,
}

/** Apply an agent prefill without clobbering anything the operator owns. */
function applyPrefill(state, prefill) {
  if (!prefill) return
  const filled = []

  Object.entries(prefill).forEach(([field, value]) => {
    if (!(field in state.values)) return
    if (value === null || value === undefined || value === '') return
    // The operator's own input always wins.
    if (state.userEdited.includes(field)) return

    state.values[field] = value
    filled.push(field)
  })

  state.aiFilled = [...new Set([...state.aiFilled, ...filled])]
}

const formSlice = createSlice({
  name: 'form',
  initialState,
  reducers: {
    setField(state, action) {
      const { field, value } = action.payload
      if (!(field in state.values)) return

      state.values[field] = value
      if (!state.userEdited.includes(field)) state.userEdited.push(field)
      // Once a human touches it, it is no longer an AI value.
      state.aiFilled = state.aiFilled.filter((f) => f !== field)
    },

    /** Explicitly reject one AI suggestion and blank the field. */
    rejectSuggestion(state, action) {
      const field = action.payload
      if (!(field in state.values)) return
      state.values[field] = typeof state.values[field] === 'boolean' ? false : ''
      state.aiFilled = state.aiFilled.filter((f) => f !== field)
      if (!state.userEdited.includes(field)) state.userEdited.push(field)
    },

    resetForm: () => ({ ...initialState, values: { ...EMPTY_FORM } }),
    dismissSaveError(state) {
      state.saveError = null
      if (state.saveStatus === 'failed') state.saveStatus = 'idle'
    },
  },

  extraReducers: (builder) => {
    const prefillFromCopilot = (state, action) => {
      // A rejected source is not a complaint - do not populate the form with it.
      if (action.payload?.is_complaint === false) return
      applyPrefill(state, action.payload?.form_prefill)
    }

    // A chat turn carries form_update; the older intake thunks carry
    // form_prefill. Both mean the same thing to this slice.
    const prefillFromChat = (state, action) => {
      applyPrefill(state, action.payload?.form_update)
    }

    builder
      .addCase(sendMessage.fulfilled, prefillFromChat)
      .addCase(sendFile.fulfilled, prefillFromChat)
      .addCase(ingestText.fulfilled, prefillFromCopilot)
      .addCase(ingestFile.fulfilled, prefillFromCopilot)
      .addCase(reassess.fulfilled, prefillFromCopilot)

      .addCase(saveComplaint.pending, (state) => {
        state.saveStatus = 'saving'
        state.saveError = null
      })
      .addCase(saveComplaint.fulfilled, (state, action) => {
        state.saveStatus = 'succeeded'
        state.savedComplaint = action.payload
      })
      .addCase(saveComplaint.rejected, (state, action) => {
        state.saveStatus = 'failed'
        state.saveError = action.payload ?? 'Could not save the complaint.'
      })
  },
})

export const { setField, rejectSuggestion, resetForm, dismissSaveError } =
  formSlice.actions
export default formSlice.reducer

// --- selectors ---
export const selectValues = (state) => state.form.values
export const selectAiFilled = (state) => state.form.aiFilled
export const selectIsAiFilled = (field) => (state) =>
  state.form.aiFilled.includes(field)
export const selectSaveStatus = (state) => state.form.saveStatus
export const selectSaveError = (state) => state.form.saveError
export const selectSavedComplaint = (state) => state.form.savedComplaint

/** Mandatory fields, mirroring MANDATORY_FIELDS on the backend. */
export const MANDATORY = [
  'complaint_source',
  'customer_name',
  'product_name',
  'batch_number',
  'complaint_category',
  'complaint_description',
]

// Memoised: a plain `.filter()` selector returns a new array on every call,
// which makes useSelector re-render the component on every unrelated dispatch.
export const selectMissingMandatory = createSelector(
  [selectValues],
  (values) =>
    MANDATORY.filter((field) => {
      const value = values[field]
      return value === '' || value === null || value === undefined
    }),
)

export const selectCanSave = createSelector(
  [selectMissingMandatory, selectSaveStatus],
  (missing, saveStatus) => missing.length === 0 && saveStatus !== 'saving',
)
