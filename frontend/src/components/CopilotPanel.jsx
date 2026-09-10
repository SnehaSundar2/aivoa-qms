/**
 * AI Copilot - Risk Assessment.
 *
 * Renders everything the agent produced, in the order a QA officer actually
 * needs it: severity first (it drives the timeline and the reporting
 * decision), then anything blocking the investigation, then the analysis.
 */
import { useDispatch, useSelector } from 'react-redux'

import {
  reassess,
  selectCopilot,
  selectIsRunning,
} from '../features/copilot/copilotSlice'
import { selectAiHealth } from '../features/meta/metaSlice'
import { Alert, Empty, Spinner, TraceStrip } from './ui'
import { humanise } from '../utils/format'

const LIKELIHOOD_TONE = { High: 'critical', Medium: 'major', Low: 'neutral' }
const CAPA_TONE = {
  Correction: 'critical',
  'Corrective Action': 'major',
  'Preventive Action': 'brand',
}

function RiskHero({ risk }) {
  const score = risk.risk_score ?? 0
  return (
    <div className="risk-hero">
      <div className="risk-hero-top">
        <div>
          <div className={`risk-severity sev-${risk.severity}`}>
            {risk.severity}
          </div>
          <div className="risk-caption">
            Preliminary classification · confirm before saving
          </div>
        </div>
        {risk.regulatory_reportable && (
          <span className="badge badge-critical">Reportable</span>
        )}
      </div>

      <div className="gauge">
        <div className="gauge-track">
          <div
            className={`gauge-fill sev-${risk.severity}`}
            style={{ width: `${Math.min(Math.max(score, 0), 100)}%` }}
          />
        </div>
        <span className="gauge-value">{score}/100</span>
      </div>

      {risk.confidence != null && (
        <div className="hint" style={{ marginTop: 6 }}>
          Model confidence {Math.round(risk.confidence * 100)}%
        </div>
      )}
    </div>
  )
}

export default function CopilotPanel() {
  const dispatch = useDispatch()
  const { result, error } = useSelector(selectCopilot)
  const isRunning = useSelector(selectIsRunning)
  const aiHealth = useSelector(selectAiHealth)

  const header = (
    <div className="copilot-head">
      <div className="copilot-spark">✦</div>
      <div style={{ flex: 1 }}>
        <h2>AI Copilot · Risk Assessment</h2>
        <div className="sub" style={{ fontSize: 11.5, color: 'var(--text-3)' }}>
          {aiHealth?.llm_configured
            ? `${aiHealth.extraction_model} + ${aiHealth.reasoning_model}`
            : 'Rule-based fallback — no Groq key configured'}
        </div>
      </div>
      {result && (
        <button
          className="btn btn-sm"
          onClick={() => dispatch(reassess())}
          disabled={isRunning}
          title="Re-run the agent against the form as it stands now"
        >
          {isRunning ? <Spinner /> : '↻'} Re-assess
        </button>
      )}
    </div>
  )

  if (isRunning && !result) {
    return (
      <div className="card copilot">
        {header}
        <div className="card-body">
          <div className="row" style={{ marginBottom: 14 }}>
            <Spinner />
            <span className="small muted">
              Running the complaint agent…
            </span>
          </div>
          {['70%', '92%', '55%', '80%'].map((width, index) => (
            <div
              key={index}
              className="skeleton"
              style={{ height: 13, width, marginBottom: 9 }}
            />
          ))}
        </div>
      </div>
    )
  }

  if (!result) {
    return (
      <div className="card copilot">
        {header}
        <Empty icon="✦" title="No assessment yet">
          {error
            ? error
            : 'Upload a complaint document or paste the text to run the agent.'}
        </Empty>
      </div>
    )
  }

  if (result.is_complaint === false) {
    return (
      <div className="card copilot">
        {header}
        <div className="card-body">
          <Alert tone="warn" title="This does not look like a complaint">
            {result.rejection_reason ??
              'The agent did not find an alleged product deficiency in this document.'}
          </Alert>
          <p className="small muted mb-0">
            The form has been left empty. If this really is a complaint, enter it
            manually and use <strong>Re-assess</strong>.
          </p>
          <div style={{ marginTop: 12 }}>
            <TraceStrip trace={result.trace} />
          </div>
        </div>
      </div>
    )
  }

  const { risk, completeness, duplicates, root_causes: rootCauses, capa } = result

  return (
    <div className="card copilot">
      {header}

      {result.degraded && (
        <div style={{ padding: '12px 16px 0' }}>
          <Alert tone="warn" title="Rule-based result">
            The language model was unavailable, so this assessment came from
            deterministic rules. Treat it as a starting point only.
          </Alert>
        </div>
      )}

      <RiskHero risk={risk} />

      {/* --- duplicates: the first thing that changes what you do next --- */}
      {duplicates.length > 0 && (
        <div className="copilot-section">
          <div className="section-title">Possible duplicates</div>
          {duplicates.map((dup) => (
            <div className="dup-item" key={dup.complaint_id}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div className="dup-num">{dup.complaint_number}</div>
                <div className="dup-reason">{dup.reason}</div>
              </div>
              <span className="badge badge-major">
                {Math.round(dup.similarity * 100)}%
              </span>
            </div>
          ))}
        </div>
      )}

      {/* --- completeness --- */}
      {completeness && (
        <div className="copilot-section">
          <div className="section-title">Completeness</div>
          <div className="row" style={{ marginBottom: 9 }}>
            <div className="gauge-track" style={{ maxWidth: 130 }}>
              <div
                className={`gauge-fill sev-${
                  completeness.is_complete ? 'Minor' : 'Major'
                }`}
                style={{ width: `${completeness.score}%` }}
              />
            </div>
            <span className="small">
              <strong>{completeness.score}%</strong> complete
            </span>
            {completeness.is_complete ? (
              <span className="badge badge-minor">Ready</span>
            ) : (
              <span className="badge badge-major">
                {completeness.missing_mandatory.length} missing
              </span>
            )}
          </div>

          {completeness.missing_mandatory.length > 0 && (
            <div className="row wrap" style={{ marginBottom: 10, gap: 5 }}>
              {completeness.missing_mandatory.map((field) => (
                <span className="badge badge-neutral" key={field}>
                  {humanise(field)}
                </span>
              ))}
            </div>
          )}

          {completeness.clarifying_questions?.length > 0 && (
            <>
              <div className="small muted" style={{ marginBottom: 5 }}>
                Ask the customer:
              </div>
              <ol className="question-list">
                {completeness.clarifying_questions.map((question, index) => (
                  <li key={index}>{question}</li>
                ))}
              </ol>
            </>
          )}
        </div>
      )}

      {/* --- risk rationale --- */}
      <div className="copilot-section">
        <div className="section-title">Assessment</div>
        <dl className="kv">
          {risk.patient_safety_impact && (
            <>
              <dt>Patient safety</dt>
              <dd>{risk.patient_safety_impact}</dd>
            </>
          )}
          {risk.gxp_impact && (
            <>
              <dt>GxP impact</dt>
              <dd>{risk.gxp_impact}</dd>
            </>
          )}
          <dt>Reportable</dt>
          <dd>
            {risk.regulatory_reportable ? 'Yes — assess now' : 'Not indicated'}
            {risk.regulatory_rationale && (
              <div className="small muted" style={{ marginTop: 3 }}>
                {risk.regulatory_rationale}
              </div>
            )}
          </dd>
          {risk.recommended_due_days != null && (
            <>
              <dt>Target closure</dt>
              <dd>{risk.recommended_due_days} days</dd>
            </>
          )}
        </dl>
        {risk.rationale && (
          <p className="small" style={{ marginTop: 10, marginBottom: 0 }}>
            {risk.rationale}
          </p>
        )}
      </div>

      {/* --- root causes --- */}
      {rootCauses.length > 0 && (
        <div className="copilot-section">
          <div className="section-title">Probable root causes</div>
          {rootCauses.map((rc, index) => (
            <div className="rc-item" key={index}>
              <div className="rc-head">
                <div className="rc-cause">{rc.cause}</div>
              </div>
              <div className="rc-meta">
                <span
                  className={`badge badge-${
                    LIKELIHOOD_TONE[rc.likelihood] ?? 'neutral'
                  }`}
                >
                  {rc.likelihood}
                </span>
                <span className="badge badge-neutral">{rc.category}</span>
              </div>
              {rc.investigation_step && (
                <div className="rc-step">{rc.investigation_step}</div>
              )}
            </div>
          ))}
          <div className="hint" style={{ marginTop: 8 }}>
            Hypotheses for investigation — not conclusions.
          </div>
        </div>
      )}

      {/* --- CAPA --- */}
      {capa.length > 0 && (
        <div className="copilot-section">
          <div className="section-title">Recommended CAPA</div>
          {capa.map((action, index) => (
            <div className="capa-item" key={index}>
              <div className="capa-action">{action.action}</div>
              <div className="capa-meta">
                <span
                  className={`badge badge-${CAPA_TONE[action.type] ?? 'neutral'}`}
                >
                  {action.type}
                </span>
                {action.owner_function && (
                  <span className="badge badge-neutral">
                    {action.owner_function}
                  </span>
                )}
                {action.target_days != null && (
                  <span className="small muted">{action.target_days} days</span>
                )}
              </div>
            </div>
          ))}
          <div className="hint" style={{ marginTop: 8 }}>
            Proposals for QA review — not approved CAPA.
          </div>
        </div>
      )}

      {/* --- summary --- */}
      {result.summary && (
        <div className="copilot-section">
          <div className="section-title">Summary</div>
          <p className="small mb-0">{result.summary}</p>
        </div>
      )}

      {/* --- provenance --- */}
      <div className="copilot-section">
        <div className="section-title">Agent run</div>
        <TraceStrip trace={result.trace} />
        <div className="hint" style={{ marginTop: 8 }}>
          {result.latency_ms} ms
          {result.models_used?.length > 0 && ` · ${result.models_used.join(', ')}`}
          {result.source_reference && ` · ${result.source_reference}`}
        </div>
      </div>

      {result.source_text && (
        <div className="copilot-section">
          <div className="section-title">Source text</div>
          <div className="source-preview">{result.source_text}</div>
        </div>
      )}
    </div>
  )
}
