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
  const justChanged = useSelector((state) =>
    state.form.recentlyChanged.includes(name),
  )
  const onChange = (newValue) =>
    dispatch(setField({ field: name, value: newValue }))
  return { value, isAi, justChanged, onChange }
}

function Wrapper({ name, label, required, hint, isAi, justChanged, children }) {
  return (
    <div
      className={`field${isAi ? ' is-ai-filled' : ''}${
        justChanged ? ' just-changed' : ''
      }`}
    >
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
  const { value, isAi, justChanged, onChange } = useField(name)
  return (
    <Wrapper
      name={name}
      label={label}
      required={required}
      hint={hint}
      isAi={isAi}
      justChanged={justChanged}
    >
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
  const { value, isAi, justChanged, onChange } = useField(name)
  return (
    <Wrapper
      name={name}
      label={label}
      required={required}
      hint={hint}
      isAi={isAi}
      justChanged={justChanged}
    >
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

export function SelectField({
  name,
  label,
  options = [],
  required,
  hint,
  placeholder = 'Select…',
}) {
  const { value, isAi, justChanged, onChange } = useField(name)

  // A value outside the option list would render as a blank select while
  // still counting as populated - the operator sees an empty field and
  // commits something they never read. Surface it instead of hiding it.
  const isUnknown = Boolean(value) && options.length > 0 && !options.includes(value)

  return (
    <Wrapper
      name={name}
      label={label}
      required={required}
      hint={isUnknown ? `"${value}" is not a recognised option - please correct it` : hint}
      isAi={isAi}
      justChanged={justChanged}
    >
      <select
        id={name}
        className={isUnknown ? 'is-unknown-value' : undefined}
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{placeholder}</option>
        {isUnknown && <option value={value}>{value} (unrecognised)</option>}
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
  const { value, isAi, justChanged, onChange } = useField(name)
  return (
    <Wrapper
      name={name}
      label={label}
      required={required}
      hint={hint}
      isAi={isAi}
      justChanged={justChanged}
    >
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
  const { value, isAi, justChanged, onChange } = useField(name)
  return (
    <div className={`field${justChanged ? ' just-changed' : ''}`}>
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
