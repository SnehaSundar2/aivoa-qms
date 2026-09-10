/** A saved complaint: the record, its AI assessment history, and the audit trail. */
import { useEffect } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Link, useParams } from 'react-router-dom'

import { Alert, Empty, SeverityBadge, StatusBadge } from '../components/ui'
import { formatDate, formatDateTime } from '../utils/format'
import {
  clearCurrent,
  fetchComplaint,
  selectAssessments,
  selectAudit,
  selectCurrent,
  updateComplaint,
} from '../features/complaints/complaintsSlice'
import { selectMeta } from '../features/meta/metaSlice'

function Row({ label, children }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children ?? '—'}</dd>
    </>
  )
}

export default function ComplaintDetailPage() {
  const { id } = useParams()
  const dispatch = useDispatch()

  const complaint = useSelector(selectCurrent)
  const assessments = useSelector(selectAssessments)
  const audit = useSelector(selectAudit)
  const status = useSelector((state) => state.complaints.detailStatus)
  const meta = useSelector(selectMeta)

  useEffect(() => {
    dispatch(fetchComplaint(id))
    return () => dispatch(clearCurrent())
  }, [dispatch, id])

  if (status === 'loading' || !complaint) {
    return (
      <div className="content content-narrow">
        {status === 'failed' ? (
          <Alert tone="danger" title="Could not load this complaint">
            <Link to="/">Back to the register</Link>
          </Alert>
        ) : (
          <div className="card">
            <div className="card-body">
              {[1, 2, 3, 4, 5].map((n) => (
                <div
                  key={n}
                  className="skeleton"
                  style={{ height: 15, width: `${90 - n * 8}%`, marginBottom: 10 }}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    )
  }

  const latest = assessments[0]

  return (
    <div className="content content-narrow">
      <div className="row" style={{ marginBottom: 14 }}>
        <Link to="/" className="btn btn-ghost btn-sm">
          ← Register
        </Link>
        <div className="spacer" />
        <select
          value={complaint.status ?? ''}
          onChange={(event) =>
            dispatch(
              updateComplaint({
                id: complaint.id,
                changes: { status: event.target.value },
              }),
            )
          }
          style={{ width: 'auto' }}
          title="Change the workflow status"
        >
          {meta.statuses.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </div>

      <div className="split">
        <div className="stack">
          <div className="card">
            <div className="card-head">
              <div>
                <h2 className="mono">{complaint.complaint_number}</h2>
                <div className="sub">
                  {complaint.product_name ?? 'Unspecified product'}
                  {complaint.batch_number && ` · batch ${complaint.batch_number}`}
                </div>
              </div>
              <div className="row">
                <SeverityBadge
                  severity={complaint.severity}
                  score={complaint.risk_score}
                />
                <StatusBadge status={complaint.status} />
              </div>
            </div>

            <div className="card-body">
              {complaint.ai_summary && (
                <Alert tone="ai" title="AI summary">
                  {complaint.ai_summary}
                </Alert>
              )}

              <div className="section-title">Complaint</div>
              <p className="small">{complaint.complaint_description ?? '—'}</p>

              <div className="section-title" style={{ marginTop: 18 }}>
                Record
              </div>
              <dl className="kv">
                <Row label="Complainant">
                  {complaint.complainant_name}
                  {complaint.complainant_organisation &&
                    ` · ${complaint.complainant_organisation}`}
                </Row>
                <Row label="Contact">
                  {complaint.complainant_email ?? complaint.complainant_phone}
                </Row>
                <Row label="Country">{complaint.country}</Row>
                <Row label="Product type">{complaint.product_type}</Row>
                <Row label="Dosage form">
                  {[complaint.dosage_form, complaint.strength]
                    .filter(Boolean)
                    .join(' · ') || null}
                </Row>
                <Row label="Pack size">{complaint.pack_size}</Row>
                <Row label="Quantity affected">
                  {complaint.quantity_complained}
                </Row>
                <Row label="Expiry">{formatDate(complaint.expiry_date)}</Row>
                <Row label="Category">{complaint.complaint_category}</Row>
                <Row label="Sub-category">{complaint.complaint_subcategory}</Row>
                <Row label="Sample available">
                  {complaint.sample_available ? 'Yes' : 'No'}
                  {complaint.sample_quantity && ` · ${complaint.sample_quantity}`}
                </Row>
                <Row label="Date of complaint">
                  {formatDate(complaint.date_of_complaint)}
                </Row>
                <Row label="Received">{formatDate(complaint.date_received)}</Row>
                <Row label="Investigation due">
                  {formatDate(complaint.due_date)}
                </Row>
                <Row label="Owner">
                  {[complaint.assigned_to, complaint.department]
                    .filter(Boolean)
                    .join(' · ') || null}
                </Row>
                <Row label="Reportable">
                  {complaint.regulatory_reportable ? 'Yes' : 'Not indicated'}
                  {complaint.regulatory_rationale && (
                    <div className="small muted" style={{ marginTop: 3 }}>
                      {complaint.regulatory_rationale}
                    </div>
                  )}
                </Row>
                <Row label="Source">
                  {complaint.source_type}
                  {complaint.source_reference && ` · ${complaint.source_reference}`}
                </Row>
              </dl>
            </div>
          </div>

          {complaint.source_text && (
            <div className="card">
              <div className="card-head">
                <h2>Original source</h2>
              </div>
              <div className="card-body">
                <div className="source-preview">{complaint.source_text}</div>
              </div>
            </div>
          )}

          <div className="card">
            <div className="card-head">
              <h2>Audit trail</h2>
              <span className="sub">{audit.length} entries</span>
            </div>
            <div className="card-body">
              {audit.length === 0 ? (
                <Empty icon="◷" title="No audit entries" />
              ) : (
                <div className="timeline">
                  {audit.map((entry) => (
                    <div
                      key={entry.id}
                      className={`timeline-item${
                        entry.actor === 'ai.copilot' ? ' is-ai' : ''
                      }`}
                    >
                      <div className="timeline-action">{entry.action}</div>
                      <div className="timeline-meta">
                        {entry.actor} · {formatDateTime(entry.created_at)}
                      </div>
                      {entry.detail && (
                        <div className="timeline-detail">{entry.detail}</div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* --- AI assessment history --- */}
        <div className="card copilot">
          <div className="copilot-head">
            <div className="copilot-spark">✦</div>
            <div style={{ flex: 1 }}>
              <h2>AI Copilot history</h2>
              <div style={{ fontSize: 11.5, color: 'var(--text-3)' }}>
                {assessments.length} run{assessments.length === 1 ? '' : 's'}{' '}
                recorded
              </div>
            </div>
          </div>

          {!latest ? (
            <Empty icon="✦" title="No AI assessment">
              This complaint was logged without the copilot.
            </Empty>
          ) : (
            <>
              <div className="risk-hero">
                <div className="risk-hero-top">
                  <div>
                    <div className={`risk-severity sev-${latest.severity}`}>
                      {latest.severity}
                    </div>
                    <div className="risk-caption">
                      {formatDateTime(latest.created_at)}
                    </div>
                  </div>
                  {latest.regulatory_reportable && (
                    <span className="badge badge-critical">Reportable</span>
                  )}
                </div>
                <div className="gauge">
                  <div className="gauge-track">
                    <div
                      className={`gauge-fill sev-${latest.severity}`}
                      style={{ width: `${latest.risk_score ?? 0}%` }}
                    />
                  </div>
                  <span className="gauge-value">{latest.risk_score}/100</span>
                </div>
              </div>

              {latest.rationale && (
                <div className="copilot-section">
                  <div className="section-title">Rationale</div>
                  <p className="small mb-0">{latest.rationale}</p>
                </div>
              )}

              {latest.root_causes?.length > 0 && (
                <div className="copilot-section">
                  <div className="section-title">Probable root causes</div>
                  {latest.root_causes.map((rc, index) => (
                    <div className="rc-item" key={index}>
                      <div className="rc-cause">{rc.cause}</div>
                      <div className="rc-meta">
                        <span className="badge badge-neutral">{rc.category}</span>
                        <span className="badge badge-neutral">
                          {rc.likelihood}
                        </span>
                      </div>
                      {rc.investigation_step && (
                        <div className="rc-step">{rc.investigation_step}</div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {latest.capa?.length > 0 && (
                <div className="copilot-section">
                  <div className="section-title">Recommended CAPA</div>
                  {latest.capa.map((action, index) => (
                    <div className="capa-item" key={index}>
                      <div className="capa-action">{action.action}</div>
                      <div className="capa-meta">
                        <span className="badge badge-neutral">{action.type}</span>
                        {action.owner_function && (
                          <span className="badge badge-neutral">
                            {action.owner_function}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <div className="copilot-section">
                <div className="section-title">Provenance</div>
                <div className="hint">
                  {latest.model_used ?? 'unknown model'} · {latest.latency_ms} ms
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
