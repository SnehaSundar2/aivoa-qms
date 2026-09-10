import { configureStore } from '@reduxjs/toolkit'

import complaintsReducer from '../features/complaints/complaintsSlice'
import copilotReducer from '../features/copilot/copilotSlice'
import formReducer from '../features/form/formSlice'
import metaReducer from '../features/meta/metaSlice'

export const store = configureStore({
  reducer: {
    complaints: complaintsReducer,
    copilot: copilotReducer,
    form: formReducer,
    meta: metaReducer,
  },
})
