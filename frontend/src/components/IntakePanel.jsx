/**
 * Complaint intake: drop a document, or paste the text.
 *
 * Either way the result is one call into the agent, and the response flows
 * straight into the form slice via the copilot thunks.
 */
import { useRef, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'

import {
  dismissError,
  ingestFile,
  ingestText,
  selectCopilot,
} from '../features/copilot/copilotSlice'
import { Alert, Spinner } from './ui'
import { formatBytes } from '../utils/format'

const ACCEPT = '.pdf,.eml,.txt,.md,.png,.jpg,.jpeg,.webp'

const SAMPLE_TEXT = `From: pharmacy@lakesidemedical.example
Subject: URGENT - Particles found in Ondansetron vials, batch OND25B119

Our oncology nursing staff identified small floating particles in four vials
of Ondansetron Injection USP 2 mg/mL, batch OND25B119, expiry 05/2028, during
pre-administration inspection this morning.

No product from this carton has been administered. All 25 vials have been
quarantined in our pharmacy and the four affected vials are available for
return. We received 200 vials of this batch on 12 August 2026.

Thomas Bergstrom, PharmD
Director of Pharmacy, Lakeside Regional Medical Center`

export default function IntakePanel() {
  const dispatch = useDispatch()
  const { status, error, activeOperation } = useSelector(selectCopilot)
  const isRunning = status === 'loading'

  const [text, setText] = useState('')
  const [file, setFile] = useState(null)
  const [isOver, setIsOver] = useState(false)
  const inputRef = useRef(null)

  const handleFiles = (fileList) => {
    const picked = fileList?.[0]
    if (picked) setFile(picked)
  }

  const onDrop = (event) => {
    event.preventDefault()
    setIsOver(false)
    handleFiles(event.dataTransfer.files)
  }

  const runFile = () => {
    if (file) dispatch(ingestFile({ file }))
  }

  const runText = () => {
    if (text.trim().length >= 10) {
      dispatch(ingestText({ text, sourceType: 'Email' }))
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h2>Complaint Intake</h2>
          <div className="sub">
            Upload the customer's document, or paste the complaint text
          </div>
        </div>
      </div>

      <div className="card-body">
        {error && (
          <Alert
            tone="danger"
            title="Intake failed"
            onClose={() => dispatch(dismissError())}
          >
            {error}
          </Alert>
        )}

        <div
          className={`dropzone${isOver ? ' is-over' : ''}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={(event) => {
            event.preventDefault()
            setIsOver(true)
          }}
          onDragLeave={() => setIsOver(false)}
          onDrop={onDrop}
          role="button"
          tabIndex={0}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') inputRef.current?.click()
          }}
        >
          <div className="dropzone-icon">⇪</div>
          <strong>Drop a complaint document here</strong>
          <span>PDF, email (.eml), text or image · up to 15 MB</span>
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            hidden
            onChange={(event) => handleFiles(event.target.files)}
          />
        </div>

        {file && (
          <div style={{ marginTop: 12 }}>
            <div className="file-chip">
              <span>▤</span>
              <span className="name">{file.name}</span>
              <span className="size">{formatBytes(file.size)}</span>
              <button
                className="btn btn-sm btn-ghost"
                onClick={() => setFile(null)}
                disabled={isRunning}
              >
                ×
              </button>
            </div>
            <button
              className="btn btn-ai btn-block"
              onClick={runFile}
              disabled={isRunning}
            >
              {isRunning && activeOperation === 'file' ? (
                <>
                  <Spinner /> Reading and assessing…
                </>
              ) : (
                <>✦ Analyse with AI Copilot</>
              )}
            </button>
          </div>
        )}

        <div className="divider-or">or paste text</div>

        <textarea
          rows={7}
          value={text}
          placeholder="Paste the complaint email, phone-call note or portal submission here…"
          onChange={(event) => setText(event.target.value)}
        />

        <div className="row" style={{ marginTop: 10 }}>
          <button
            className="btn btn-ai"
            onClick={runText}
            disabled={isRunning || text.trim().length < 10}
          >
            {isRunning && activeOperation === 'text' ? (
              <>
                <Spinner /> Assessing…
              </>
            ) : (
              <>✦ Analyse with AI Copilot</>
            )}
          </button>
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => setText(SAMPLE_TEXT)}
            disabled={isRunning}
            title="Fill the box with a realistic complaint email"
          >
            Use sample
          </button>
          {text && (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setText('')}
              disabled={isRunning}
            >
              Clear
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
