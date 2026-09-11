/** Controlled vocabularies and AI health, both fetched once at app start. */
import { createAsyncThunk, createSlice } from '@reduxjs/toolkit'

import { api, endpoints } from '../../api/client'

export const fetchMetadata = createAsyncThunk(
  'meta/fetchMetadata',
  async (_, { rejectWithValue }) => {
    try {
      return await api.get(endpoints.metadata)
    } catch (error) {
      return rejectWithValue(error.message)
    }
  },
)

export const fetchAiHealth = createAsyncThunk(
  'meta/fetchAiHealth',
  async (_, { rejectWithValue }) => {
    try {
      return await api.get(endpoints.aiHealth)
    } catch (error) {
      return rejectWithValue(error.message)
    }
  },
)

const metaSlice = createSlice({
  name: 'meta',
  initialState: {
    categories: [],
    severities: [],
    statuses: [],
    productTypes: [],
    sourceTypes: [],
    departments: [],
    siteBlocks: [],
    complaintSources: [],
    ai: null,
    // True when the backend could not be reached at all - the whole app is
    // useless in that state, so it gets a prominent banner.
    offline: false,
  },
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchMetadata.fulfilled, (state, action) => {
        state.categories = action.payload.categories
        state.severities = action.payload.severities
        state.statuses = action.payload.statuses
        state.productTypes = action.payload.product_types
        state.sourceTypes = action.payload.source_types
        state.departments = action.payload.departments
        state.siteBlocks = action.payload.site_blocks ?? []
        state.complaintSources = action.payload.complaint_sources ?? []
        state.offline = false
      })
      .addCase(fetchMetadata.rejected, (state) => {
        state.offline = true
      })
      .addCase(fetchAiHealth.fulfilled, (state, action) => {
        state.ai = action.payload
      })
  },
})

export default metaSlice.reducer

export const selectMeta = (state) => state.meta
export const selectAiHealth = (state) => state.meta.ai
export const selectOffline = (state) => state.meta.offline
