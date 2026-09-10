/** Complaint register with dashboard counters and filters. */
import { useEffect } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Link, useNavigate } from 'react-router-dom'

import { Empty, SeverityBadge, StatusBadge } from '../components/ui'
import { formatDate } from '../utils/format'
import {
  clearFilters,
  fetchComplaints,
  fetchStats,
  selectComplaints,
  selectFilters,
  selectListStatus,
  selectStats,
  setFilter,
} from '../features/complaints/complaintsSlice'
import { selectMeta } from '../features/meta/metaSlice'

function Stat({ label, value, foot, accent }) {
  return (
    <div className={`stat${accent ? ` accent-${accent}` : ''}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {foot && <div className="stat-foot">{foot}</div>}
    </div>
  )
}

export default function DashboardPage() {
  const dispatch = useDispatch()
  const navigate = useNavigate()

  const stats = useSelector(selectStats)
  const complaints = useSelector(selectComplaints)
  const filters = useSelector(selectFilters)
  const listStatus = useSelector(selectListStatus)
  const meta = useSelector(selectMeta)

  useEffect(() => {
    dispatch(fetchStats())
  }, [dispatch])

  // Re-fetch whenever a filter changes; the debounce on the search box is the
  // 250 ms below, which is enough for a register of this size.
  useEffect(() => {
    const timer = setTimeout(() => dispatch(fetchComplaints()), 250)
    return () => clearTimeout(timer)
  }, [dispatch, filters])

  const hasFilters = Object.values(filters).some(Boolean)

  return (
    <div className="content">
      <div className="grid stat-grid" style={{ marginBottom: 18 }}>
        <Stat
          label="Total complaints"
          value={stats?.total ?? '—'}
          foot="All time"
        />
        <Stat
          label="Open"
          value={stats?.open ?? '—'}
          foot="Not yet closed"
          accent="brand"
        />
        <Stat
          label="Critical"
          value={stats?.critical ?? '—'}
          foot="Recall / FAR candidates"
          accent="critical"
        />
        <Stat
          label="Overdue"
          value={stats?.overdue ?? '—'}
          foot="Past investigation due date"
          accent="major"
        />
        <Stat
          label="AI-assisted"
          value={stats?.ai_assisted ?? '—'}
          foot="Logged with the copilot"
          accent="ai"
        />
      </div>

      <div className="card">
        <div className="card-head">
          <div>
            <h2>Complaint Register</h2>
            <div className="sub">
              {listStatus === 'loading'
                ? 'Loading…'
                : `${complaints.length} record${complaints.length === 1 ? '' : 's'}`}
            </div>
          </div>
          <Link className="btn btn-primary btn-sm" to="/log">
            + Log complaint
          </Link>
        </div>

        <div className="card-body tight">
          <div className="toolbar">
            <input
              type="text"
              placeholder="Search product, batch, description…"
              value={filters.q}
              onChange={(event) =>
                dispatch(setFilter({ key: 'q', value: event.target.value }))
              }
            />
            <select
              value={filters.severity}
              onChange={(event) =>
                dispatch(setFilter({ key: 'severity', value: event.target.value }))
              }
            >
              <option value="">All severities</option>
              {meta.severities.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
            <select
              value={filters.status}
              onChange={(event) =>
                dispatch(setFilter({ key: 'status', value: event.target.value }))
              }
            >
              <option value="">All statuses</option>
              {meta.statuses.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
            <select
              value={filters.category}
              onChange={(event) =>
                dispatch(setFilter({ key: 'category', value: event.target.value }))
              }
            >
              <option value="">All categories</option>
              {meta.categories.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
            {hasFilters && (
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => dispatch(clearFilters())}
              >
                Clear
              </button>
            )}
          </div>
        </div>

        {complaints.length === 0 && listStatus !== 'loading' ? (
          <Empty icon="◫" title="No complaints match">
            {hasFilters
              ? 'Try clearing the filters.'
              : 'Log the first complaint to get started.'}
          </Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>Number</th>
                  <th>Product</th>
                  <th>Batch</th>
                  <th>Category</th>
                  <th>Severity</th>
                  <th>Status</th>
                  <th>Received</th>
                  <th>Due</th>
                </tr>
              </thead>
              <tbody>
                {complaints.map((complaint) => {
                  const overdue =
                    complaint.due_date &&
                    new Date(complaint.due_date) < new Date() &&
                    complaint.status !== 'Closed'

                  return (
                    <tr
                      key={complaint.id}
                      onClick={() => navigate(`/complaints/${complaint.id}`)}
                      style={{ cursor: 'pointer' }}
                    >
                      <td className="cell-mono cell-strong">
                        {complaint.complaint_number}
                        {complaint.ai_assisted && (
                          <span
                            className="badge badge-ai"
                            style={{ marginLeft: 6, padding: '0 5px' }}
                            title="Logged with AI assistance"
                          >
                            ✦
                          </span>
                        )}
                      </td>
                      <td className="cell-truncate">
                        {complaint.product_name ?? '—'}
                        <div className="small cell-muted">
                          {complaint.complainant_organisation ?? ''}
                        </div>
                      </td>
                      <td className="cell-mono">{complaint.batch_number ?? '—'}</td>
                      <td className="cell-truncate small">
                        {complaint.complaint_category ?? '—'}
                      </td>
                      <td>
                        <SeverityBadge
                          severity={complaint.severity}
                          score={complaint.risk_score}
                        />
                      </td>
                      <td>
                        <StatusBadge status={complaint.status} />
                      </td>
                      <td className="small nowrap">
                        {formatDate(complaint.date_received)}
                      </td>
                      <td className="small nowrap">
                        <span
                          style={{ color: overdue ? 'var(--critical)' : undefined }}
                        >
                          {formatDate(complaint.due_date)}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
