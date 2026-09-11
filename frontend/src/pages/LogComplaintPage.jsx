/**
 * The core screen: the complaint record on the left, the copilot conversation
 * on the right. The operator talks to the copilot; the record fills in.
 */
import { useEffect } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Link, useNavigate } from 'react-router-dom'

import ComplaintForm from '../components/ComplaintForm'
import CopilotChat from '../components/CopilotChat'
import { Alert } from '../components/ui'
import { resetChat } from '../features/chat/chatSlice'
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
import { humanise } from '../utils/format'

export default function LogComplaintPage() {
  const dispatch = useDispatch()
  const navigate = useNavigate()

  const missing = useSelector(selectMissingMandatory)
  const canSave = useSelector(selectCanSave)
  const saveStatus = useSelector(selectSaveStatus)
  const saveError = useSelector(selectSaveError)
  const saved = useSelector(selectSavedComplaint)
  const aiFilled = useSelector((state) => state.form.aiFilled.length)

  // Every visit starts clean. A complaint form that remembers the previous
  // customer's data is a data-integrity hazard.
  useEffect(() => {
    dispatch(resetForm())
    dispatch(resetChat())
  }, [dispatch])

  const startAnother = () => {
    dispatch(resetForm())
    dispatch(resetChat())
  }

  if (saveStatus === 'succeeded' && saved) {
    return (
      <div className="committed">
        <div className="committed-card">
          <div className="committed-tick">✓</div>
          <h1>Committed to QMS Ledger</h1>
          <p>
            Recorded as <strong className="mono">{saved.complaint_number}</strong>
            {saved.severity && (
              <>
                {' '}
                with severity <strong>{saved.severity}</strong>
              </>
            )}
            .
          </p>
          {aiFilled > 0 && (
            <p className="small muted">
              {aiFilled} field{aiFilled === 1 ? '' : 's'} were populated by the
              copilot, and the assessment is attached to the record.
            </p>
          )}
          <div className="row" style={{ justifyContent: 'center', marginTop: 18 }}>
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
              Register
            </Link>
          </div>
        </div>
      </div>
    )
  }

  const status = missing.length === 0 ? 'ready' : 'pending'

  return (
    <div className="workbench">
      <section className="workbench-form">
        <header className="record-head">
          <div>
            <h1>Log Customer Complaint</h1>
            <p>API &amp; FDF Quality Assurance Module</p>
          </div>
          <span className={`triage-pill is-${status}`}>
            {status === 'ready' ? (
              <>
                <span className="pill-dot" /> Ready to Commit
              </>
            ) : (
              'Pending Triage'
            )}
          </span>
        </header>

        {saveError && (
          <Alert
            tone="danger"
            title="Could not commit"
            onClose={() => dispatch(dismissSaveError())}
          >
            {saveError}
          </Alert>
        )}

        <ComplaintForm />

        <div className="record-actions">
          {missing.length > 0 && (
            <p className="record-missing">
              Awaiting: {missing.map((field) => humanise(field)).join(', ')}
            </p>
          )}
          <div className="row">
            <button className="btn btn-ghost" onClick={startAnother}>
              Reset
            </button>
            <button
              className="btn btn-commit"
              onClick={() => dispatch(saveComplaint())}
              disabled={!canSave}
            >
              {saveStatus === 'saving' ? 'Committing…' : 'Commit to QMS Ledger'}
            </button>
          </div>
        </div>
      </section>

      <CopilotChat />
    </div>
  )
}
