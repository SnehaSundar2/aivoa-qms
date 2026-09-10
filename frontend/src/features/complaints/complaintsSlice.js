/** Complaint register: list, filters, dashboard stats and the detail view. */
import { createAsyncThunk, createSlice } from '@reduxjs/toolkit'

import { api, endpoints } from '../../api/client'

export const fetchComplaints = createAsyncThunk(
  'complaints/fetchAll',
  async (_, { getState, rejectWithValue }) => {
    const { q, status, severity, category } = getState().complaints.filters
    const params = new URLSearchParams()
    if (q) params.set('q', q)
    if (status) params.set('status', status)
    if (severity) params.set('severity', severity)
    if (category) params.set('category', category)

    try {
      const query = params.toString()
      return await api.get(`${endpoints.complaints}${query ? `?${query}` : ''}`)
    } catch (error) {
      return rejectWithValue(error.message)
    }
  },
)

export const fetchStats = createAsyncThunk(
  'complaints/fetchStats',
  async (_, { rejectWithValue }) => {
    try {
      return await api.get(endpoints.stats)
    } catch (error) {
      return rejectWithValue(error.message)
    }
  },
)

export const fetchComplaint = createAsyncThunk(
  'complaints/fetchOne',
  async (id, { rejectWithValue }) => {
    try {
      const [complaint, assessments, audit] = await Promise.all([
        api.get(`${endpoints.complaints}/${id}`),
        api.get(`${endpoints.complaints}/${id}/assessments`),
        api.get(`${endpoints.complaints}/${id}/audit`),
      ])
      return { complaint, assessments, audit }
    } catch (error) {
      return rejectWithValue(error.message)
    }
  },
)

export const updateComplaint = createAsyncThunk(
  'complaints/update',
  async ({ id, changes }, { rejectWithValue }) => {
    try {
      return await api.patch(`${endpoints.complaints}/${id}`, changes)
    } catch (error) {
      return rejectWithValue(error.message)
    }
  },
)

const initialState = {
  items: [],
  total: 0,
  stats: null,
  current: null,
  assessments: [],
  audit: [],
  filters: { q: '', status: '', severity: '', category: '' },
  listStatus: 'idle',
  detailStatus: 'idle',
  error: null,
}

const complaintsSlice = createSlice({
  name: 'complaints',
  initialState,
  reducers: {
    setFilter(state, action) {
      const { key, value } = action.payload
      state.filters[key] = value
    },
    clearFilters(state) {
      state.filters = { q: '', status: '', severity: '', category: '' }
    },
    clearCurrent(state) {
      state.current = null
      state.assessments = []
      state.audit = []
      state.detailStatus = 'idle'
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchComplaints.pending, (state) => {
        state.listStatus = 'loading'
      })
      .addCase(fetchComplaints.fulfilled, (state, action) => {
        state.listStatus = 'succeeded'
        state.items = action.payload.items
        state.total = action.payload.total
      })
      .addCase(fetchComplaints.rejected, (state, action) => {
        state.listStatus = 'failed'
        state.error = action.payload
      })

      .addCase(fetchStats.fulfilled, (state, action) => {
        state.stats = action.payload
      })

      .addCase(fetchComplaint.pending, (state) => {
        state.detailStatus = 'loading'
      })
      .addCase(fetchComplaint.fulfilled, (state, action) => {
        state.detailStatus = 'succeeded'
        state.current = action.payload.complaint
        state.assessments = action.payload.assessments
        state.audit = action.payload.audit
      })
      .addCase(fetchComplaint.rejected, (state, action) => {
        state.detailStatus = 'failed'
        state.error = action.payload
      })

      .addCase(updateComplaint.fulfilled, (state, action) => {
        state.current = action.payload
        const index = state.items.findIndex((c) => c.id === action.payload.id)
        if (index !== -1) state.items[index] = action.payload
      })
  },
})

export const { setFilter, clearFilters, clearCurrent } = complaintsSlice.actions
export default complaintsSlice.reducer

export const selectComplaints = (state) => state.complaints.items
export const selectStats = (state) => state.complaints.stats
export const selectFilters = (state) => state.complaints.filters
export const selectCurrent = (state) => state.complaints.current
export const selectAssessments = (state) => state.complaints.assessments
export const selectAudit = (state) => state.complaints.audit
export const selectListStatus = (state) => state.complaints.listStatus
