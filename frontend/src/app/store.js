import { configureStore } from '@reduxjs/toolkit'

import chatReducer from '../features/chat/chatSlice'
import complaintsReducer from '../features/complaints/complaintsSlice'
import copilotReducer from '../features/copilot/copilotSlice'
import formReducer from '../features/form/formSlice'
import metaReducer from '../features/meta/metaSlice'

export const store = configureStore({
  reducer: {
    chat: chatReducer,
    complaints: complaintsReducer,
    copilot: copilotReducer,
    form: formReducer,
    meta: metaReducer,
  },
})
