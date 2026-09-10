/**
 * Form controls bound to the Redux form slice.
 *
 * Every control knows whether its current value came from the agent, and shows
 * an "AI" tag with a one-click reject. That tag is the whole point: in a
 * regulated record the operator must be able to see, at a glance, which values
 * they are accepting responsibility for.
 */
import { useDispatch, useSelector } from 'react-redux'

import { rejectSuggestion, setField } from '../features/form/formSlice'

function AiTag({ field }) {
  const dispatch = useDispatch()
  return (
    <span className="ai-tag" title="Filled by the AI Copilot - click × to clear">
      AI
      <button
        onClick={() => dispatch(rejectSuggestion(field))}
        aria-label={`Clear the AI suggestion for ${field}`}
        type="button"
      >
        ×
      </button>
    </span>
  )
}

function useField(name) {
  const dispatch = useDispatch()
  const value = useSelector((state) => state.form.values[name])
  const isAi = useSelector((state) => state.form.aiFilled.includes(name))
  const onChange = (newValue) =>
    dispatch(setField({ field: name, value: newValue }))
  return { value, isAi, onChange }
}

function Wrapper({ name, label, required, hint, isAi, children }) {
  return (
    <div className={`field${isAi ? ' is-ai-filled' : ''}`}>
      <label className="field-label" htmlFor={name}>
        {label}
        {required && <span className="required-dot">*</span>}
        {isAi && <AiTag field={name} />}
      </label>
      {children}
      {hint && <div className="hint">{hint}</div>}
    </div>
  )
}

export function TextField({ name, label, required, hint, type = 'text', placeholder }) {
  const { value, isAi, onChange } = useField(name)
  return (
    <Wrapper name={name} label={label} required={required} hint={hint} isAi={isAi}>
      <input
        id={name}
        type={type}
        value={value ?? ''}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    </Wrapper>
  )
}

export function TextArea({ name, label, required, hint, rows = 4, placeholder }) {
  const { value, isAi, onChange } = useField(name)
  return (
    <Wrapper name={name} label={label} required={required} hint={hint} isAi={isAi}>
      <textarea
        id={name}
        rows={rows}
        value={value ?? ''}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    </Wrapper>
  )
}

export function SelectField({ name, label, options = [], required, hint, placeholder = 'Select…' }) {
  const { value, isAi, onChange } = useField(name)
  return (
    <Wrapper name={name} label={label} required={required} hint={hint} isAi={isAi}>
      <select
        id={name}
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{placeholder}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </Wrapper>
  )
}

export function DateField({ name, label, required, hint }) {
  const { value, isAi, onChange } = useField(name)
  return (
    <Wrapper name={name} label={label} required={required} hint={hint} isAi={isAi}>
      <input
        id={name}
        type="date"
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value)}
      />
    </Wrapper>
  )
}

export function CheckField({ name, label, hint }) {
  const { value, isAi, onChange } = useField(name)
  return (
    <div className="field">
      <label className="checkbox" htmlFor={name}>
        <input
          id={name}
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
        />
        {label}
        {isAi && <AiTag field={name} />}
      </label>
      {hint && <div className="hint">{hint}</div>}
    </div>
  )
}
