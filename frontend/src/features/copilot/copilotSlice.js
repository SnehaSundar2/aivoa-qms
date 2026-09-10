/**
 * AI Copilot state.
 *
 * Holds the result of the last agent run plus the intake status. The result is
 * kept separate from the form slice on purpose: the form holds what the record
 * *is*, this slice holds what the AI *suggested*. Keeping them apart is what
 * lets the UI show "this field was AI-filled" and lets the operator reject a
 * suggestion without losing it.
 */
import { createAsyncThunk, createSlice } from '@reduxjs/toolkit'

import { api, endpoints } from '../../api/client'

export const ingestText = createAsyncThunk(
  'copilot/ingestText',
  async ({ text, sourceType = 'Manual Entry' }, { rejectWithValue }) => {
    try {
      return await api.post(endpoints.intakeText, {
        text,
        source_type: sourceType,
      })
    } catch (error) {
      return rejectWithValue(error.message)
    }
  },
)

export const ingestFile = createAsyncThunk(
  'copilot/ingestFile',
  async ({ file }, { rejectWithValue }) => {
    try {
      return await api.upload(endpoints.intakeFile, file)
    } catch (error) {
      return rejectWithValue(error.message)
    }
  },
)

export const reassess = createAsyncThunk(
  'copilot/reassess',
  async (_, { getState, rejectWithValue }) => {
    try {
      return await api.post(endpoints.reassess, {
        complaint: getState().form.values,
      })
    } catch (error) {
      return rejectWithValue(error.message)
    }
  },
)

const initialState = {
  result: null,
  status: 'idle', // idle | loading | succeeded | failed
  error: null,
  /** Which thunk is running, so the UI can label the spinner accurately. */
  activeOperation: null,
  /** Node names as they were reported by the last run, for the trace strip. */
  lastTrace: [],
}

function pending(operation) {
  return (state) => {
    state.status = 'loading'
    state.error = null
    state.activeOperation = operation
  }
}

function fulfilled(state, action) {
  state.status = 'succeeded'
  state.result = action.payload
  state.lastTrace = action.payload?.trace ?? []
  state.activeOperation = null
}

function rejected(state, action) {
  state.status = 'failed'
  state.error = action.payload ?? 'The copilot run failed.'
  state.activeOperation = null
}

const copilotSlice = createSlice({
  name: 'copilot',
  initialState,
  reducers: {
    clearCopilot: () => initialState,
    dismissError(state) {
      state.error = null
      if (state.status === 'failed') state.status = 'idle'
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(ingestText.pending, pending('text'))
      .addCase(ingestFile.pending, pending('file'))
      .addCase(reassess.pending, pending('reassess'))
      .addCase(ingestText.fulfilled, fulfilled)
      .addCase(ingestFile.fulfilled, fulfilled)
      .addCase(reassess.fulfilled, fulfilled)
      .addCase(ingestText.rejected, rejected)
      .addCase(ingestFile.rejected, rejected)
      .addCase(reassess.rejected, rejected)
  },
})

export const { clearCopilot, dismissError } = copilotSlice.actions
export default copilotSlice.reducer

// --- selectors ---
export const selectCopilot = (state) => state.copilot
export const selectResult = (state) => state.copilot.result
export const selectIsRunning = (state) => state.copilot.status === 'loading'
export const selectRisk = (state) => state.copilot.result?.risk ?? null
export const selectDuplicates = (state) => state.copilot.result?.duplicates ?? []
export const selectCompleteness = (state) =>
  state.copilot.result?.completeness ?? null
export const selectIsDegraded = (state) =>
  Boolean(state.copilot.result?.degraded)
