/**
 * The core screen: intake on the left feeding the complaint form, AI Copilot
 * assessment on the right. This is the end-to-end workflow the assignment
 * describes - source document in, populated record and risk assessment out.
 */
import { useEffect } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Link, useNavigate } from 'react-router-dom'

import ComplaintForm from '../components/ComplaintForm'
import CopilotPanel from '../components/CopilotPanel'
import IntakePanel from '../components/IntakePanel'
import { Alert } from '../components/ui'
import { humanise } from '../utils/format'
import { clearCopilot } from '../features/copilot/copilotSlice'
import {
  dismissSaveError,
  resetForm,
  saveComplaint,
  selectCanSave,
  selectMissingMandatory,
  selectSaveError,
  selectSaveStatus,
  selectSavedComplaint,
} from '../features/form/formSlice'

export default function LogComplaintPage() {
  const dispatch = useDispatch()
  const navigate = useNavigate()

  const missing = useSelector(selectMissingMandatory)
  const canSave = useSelector(selectCanSave)
  const saveStatus = useSelector(selectSaveStatus)
  const saveError = useSelector(selectSaveError)
  const saved = useSelector(selectSavedComplaint)
  const aiFilled = useSelector((state) => state.form.aiFilled.length)

  // Start every visit with a clean record - a complaint form that remembers
  // the previous customer's data is a data-integrity hazard.
  useEffect(() => {
    dispatch(resetForm())
    dispatch(clearCopilot())
  }, [dispatch])

  const startAnother = () => {
    dispatch(resetForm())
    dispatch(clearCopilot())
  }

  if (saveStatus === 'succeeded' && saved) {
    return (
      <div className="content content-narrow">
        <div className="card" style={{ maxWidth: 620, margin: '40px auto' }}>
          <div className="card-body" style={{ textAlign: 'center', padding: 34 }}>
            <div style={{ fontSize: 34, marginBottom: 10 }}>✓</div>
            <h1 style={{ marginBottom: 6 }}>Complaint logged</h1>
            <p className="muted">
              Recorded as{' '}
              <strong className="mono">{saved.complaint_number}</strong> with
              severity <strong>{saved.severity ?? 'unclassified'}</strong>.
            </p>
            {aiFilled > 0 && (
              <p className="small muted">
                {aiFilled} field{aiFilled === 1 ? '' : 's'} were AI-assisted and
                the assessment is attached to the record.
              </p>
            )}
            <div
              className="row"
              style={{ justifyContent: 'center', marginTop: 18 }}
            >
              <button
                className="btn btn-primary"
                onClick={() => navigate(`/complaints/${saved.id}`)}
              >
                Open the record
              </button>
              <button className="btn" onClick={startAnother}>
                Log another
              </button>
              <Link className="btn btn-ghost" to="/">
                Dashboard
              </Link>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="content content-narrow">
      {saveError && (
        <Alert
          tone="danger"
          title="Could not save"
          onClose={() => dispatch(dismissSaveError())}
        >
          {saveError}
        </Alert>
      )}

      <div className="split">
        <div className="stack">
          <IntakePanel />
          <ComplaintForm />

          <div className="card">
            <div className="card-body tight">
              <div className="row wrap">
                <div style={{ flex: 1, minWidth: 200 }}>
                  {missing.length > 0 ? (
                    <span className="small muted">
                      Still required:{' '}
                      {missing.map((field) => humanise(field)).join(', ')}
                    </span>
                  ) : (
                    <span className="small" style={{ color: 'var(--minor)' }}>
                      ✓ All mandatory fields are present
                    </span>
                  )}
                </div>
                <button className="btn btn-ghost" onClick={startAnother}>
                  Reset
                </button>
                <button
                  className="btn btn-primary"
                  onClick={() => dispatch(saveComplaint())}
                  disabled={!canSave}
                >
                  {saveStatus === 'saving' ? 'Saving…' : 'Save complaint'}
                </button>
              </div>
            </div>
          </div>
        </div>

        <CopilotPanel />
      </div>
    </div>
  )
}
