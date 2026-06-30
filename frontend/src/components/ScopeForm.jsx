import { useEffect, useState } from 'react'
import { SCOPE_TYPES } from '../api/scopes'

const EMPTY = {
  target: '',
  scope_type: 'ROOT_DOMAIN',
  priority: 50,
  is_active: true,
  notes: '',
}

// Create / edit form for a scope. `initial` (when editing) prefills fields.
export default function ScopeForm({ initial, onSubmit, onCancel, submitting }) {
  const [values, setValues] = useState(EMPTY)
  const [error, setError] = useState(null)

  useEffect(() => {
    setValues(initial ? { ...EMPTY, ...initial } : EMPTY)
    setError(null)
  }, [initial])

  const isEditing = Boolean(initial)

  function update(field, value) {
    setValues((prev) => ({ ...prev, [field]: value }))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    if (!isEditing && !values.target.trim()) {
      setError('Target is required.')
      return
    }
    const priorityNum = Number(values.priority)
    if (Number.isNaN(priorityNum)) {
      setError('Priority must be a number.')
      return
    }

    // On edit the backend does not accept changing target, so omit it.
    const payload = {
      scope_type: values.scope_type,
      priority: priorityNum,
      is_active: Boolean(values.is_active),
      notes: values.notes.trim() || null,
    }
    if (!isEditing) {
      payload.target = values.target.trim()
    }

    try {
      await onSubmit(payload)
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <form className="entity-form" onSubmit={handleSubmit}>
      <h2>{isEditing ? 'Edit scope' : 'Add scope'}</h2>

      {!isEditing && (
        <label>
          Target *
          <input
            type="text"
            value={values.target}
            onChange={(e) => update('target', e.target.value)}
            placeholder="example.com"
            autoFocus
          />
        </label>
      )}

      <label>
        Scope type
        <select
          value={values.scope_type}
          onChange={(e) => update('scope_type', e.target.value)}
        >
          {SCOPE_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>

      <label>
        Priority (0–100)
        <input
          type="number"
          min={0}
          max={100}
          value={values.priority}
          onChange={(e) => update('priority', e.target.value)}
        />
      </label>

      <label className="checkbox-row">
        <input
          type="checkbox"
          checked={Boolean(values.is_active)}
          onChange={(e) => update('is_active', e.target.checked)}
        />
        Active
      </label>

      <label>
        Notes
        <textarea
          rows={2}
          value={values.notes ?? ''}
          onChange={(e) => update('notes', e.target.value)}
          placeholder="Optional notes about this scope"
        />
      </label>

      {error && <p className="form-error">{error}</p>}

      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={submitting}>
          {submitting ? 'Saving…' : isEditing ? 'Save changes' : 'Add scope'}
        </button>
        <button type="button" className="btn" onClick={onCancel} disabled={submitting}>
          Cancel
        </button>
      </div>
    </form>
  )
}
