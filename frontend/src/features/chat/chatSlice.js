/**
 * The AIVOA Copilot conversation.
 *
 * Holds the message list and drives the two ways a turn can start: typing, or
 * dropping a file. Both hit the same backend turn handler, so the agent sees
 * one conversation regardless of how the content arrived.
 *
 * `form` travels with every turn. That is what lets the agent fill only the
 * gaps and never overwrite something the operator typed - the rule lives on
 * the backend, but it can only be honoured if the current form state is sent.
 */
import { createAsyncThunk, createSlice, nanoid } from '@reduxjs/toolkit'

import { api, endpoints } from '../../api/client'

export const fetchGreeting = createAsyncThunk(
  'chat/greeting',
  async (_, { rejectWithValue }) => {
    try {
      return await api.get(endpoints.chatGreeting)
    } catch (error) {
      return rejectWithValue(error.message)
    }
  },
)

/** Only the fields the agent can use; the rest is UI bookkeeping. */
function formPayload(state) {
  return Object.fromEntries(
    Object.entries(state.form.values).filter(
      ([, value]) => value !== '' && value !== null && value !== undefined,
    ),
  )
}

/** Trimmed history — the backend only reads the last few turns anyway. */
function historyPayload(state) {
  return state.chat.messages
    .filter((m) => m.role === 'user' || m.role === 'assistant')
    .slice(-8)
    .map(({ role, content }) => ({ role, content }))
}

export const sendMessage = createAsyncThunk(
  'chat/send',
  async (text, { getState, rejectWithValue }) => {
    try {
      return await api.post(endpoints.chat, {
        message: text,
        history: historyPayload(getState()),
        form: formPayload(getState()),
      })
    } catch (error) {
      return rejectWithValue(error.message)
    }
  },
)

export const sendFile = createAsyncThunk(
  'chat/sendFile',
  async (file, { getState, rejectWithValue }) => {
    try {
      return await api.upload(endpoints.chatUpload, file, {
        form: JSON.stringify(formPayload(getState())),
        history: JSON.stringify(historyPayload(getState())),
      })
    } catch (error) {
      return rejectWithValue(error.message)
    }
  },
)

const initialState = {
  messages: [],
  status: 'idle', // idle | thinking | failed
  error: null,
  /** Latest full assessment, for the parts of the UI outside the form. */
  copilot: null,
  formComplete: false,
  degraded: false,
}

function pushAssistant(state, action) {
  state.status = 'idle'
  state.messages.push({
    id: nanoid(),
    role: 'assistant',
    content: action.payload.reply,
    toolCalled: action.payload.tool_called,
    fieldsChanged: action.payload.fields_changed ?? [],
    degraded: action.payload.degraded,
    latencyMs: action.payload.latency_ms,
  })
  state.copilot = action.payload.copilot ?? state.copilot
  state.formComplete = action.payload.form_complete
  state.degraded = action.payload.degraded
}

function failTurn(state, action) {
  state.status = 'failed'
  state.error = action.payload ?? 'The copilot could not respond.'
  state.messages.push({
    id: nanoid(),
    role: 'assistant',
    content: `I couldn't process that. ${state.error}`,
    isError: true,
  })
}

const chatSlice = createSlice({
  name: 'chat',
  initialState,
  reducers: {
    /** Echo the operator's own message immediately, before the round trip. */
    addUserMessage(state, action) {
      state.messages.push({
        id: nanoid(),
        role: 'user',
        content: action.payload.text,
        attachment: action.payload.attachment ?? null,
      })
      state.error = null
    },
    resetChat: () => initialState,
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchGreeting.fulfilled, (state, action) => {
        // Only seed the greeting into an empty conversation.
        if (state.messages.length === 0) {
          state.messages.push({
            id: nanoid(),
            role: 'assistant',
            content: action.payload.reply,
            isGreeting: true,
          })
        }
      })
      .addCase(sendMessage.pending, (state) => {
        state.status = 'thinking'
        state.error = null
      })
      .addCase(sendFile.pending, (state) => {
        state.status = 'thinking'
        state.error = null
      })
      .addCase(sendMessage.fulfilled, pushAssistant)
      .addCase(sendFile.fulfilled, pushAssistant)
      .addCase(sendMessage.rejected, failTurn)
      .addCase(sendFile.rejected, failTurn)
  },
})

export const { addUserMessage, resetChat } = chatSlice.actions
export default chatSlice.reducer

export const selectMessages = (state) => state.chat.messages
export const selectChatStatus = (state) => state.chat.status
export const selectIsThinking = (state) => state.chat.status === 'thinking'
export const selectChatCopilot = (state) => state.chat.copilot
export const selectFormComplete = (state) => state.chat.formComplete
export const selectChatDegraded = (state) => state.chat.degraded
