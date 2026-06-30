import { useEffect, useState } from 'react'

const EMPTY = {
  name: '',
  platform: '',
  description: '',
  created_by: '',
  status: 'active',
}

// Create / edit form for a program. `initial` (when editing) prefills fields.
// `grid` lays the short fields out in two columns (used on the wide create page).
export default function ProgramForm({ initial, onSubmit, onCancel, submitting, grid }) {
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
    if (!values.name.trim()) {
      setError('Name is required.')
      return
    }
    // Send only meaningful fields; collapse empty strings to null/omit.
    const payload = {
      name: values.name.trim(),
      platform: values.platform.trim() || null,
      description: values.description.trim() || null,
      created_by: values.created_by.trim() || null,
      status: values.status || 'active',
    }
    try {
      await onSubmit(payload)
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <form className={`program-form${grid ? ' form-grid' : ''}`} onSubmit={handleSubmit}>
      {!grid && <h2>{isEditing ? 'Edit program' : 'New program'}</h2>}

      <label className={grid ? 'span-2' : undefined}>
        Name *
        <input
          type="text"
          value={values.name}
          onChange={(e) => update('name', e.target.value)}
          placeholder="Acme Bug Bounty"
          autoFocus
        />
      </label>

      <label>
        Platform
        <input
          type="text"
          value={values.platform ?? ''}
          onChange={(e) => update('platform', e.target.value)}
          placeholder="hackerone / bugcrowd / private"
        />
      </label>

      <label>
        Status
        <select
          value={values.status ?? 'active'}
          onChange={(e) => update('status', e.target.value)}
        >
          <option value="active">active</option>
          <option value="paused">paused</option>
          <option value="archived">archived</option>
        </select>
      </label>

      <label className={grid ? 'span-2' : undefined}>
        Owner (created_by)
        <input
          type="text"
          value={values.created_by ?? ''}
          onChange={(e) => update('created_by', e.target.value)}
          placeholder="security-team@example.com"
        />
      </label>

      <label className={grid ? 'span-2' : undefined}>
        Description
        <textarea
          rows={grid ? 4 : 3}
          value={values.description ?? ''}
          onChange={(e) => update('description', e.target.value)}
          placeholder="External asset monitoring program"
        />
      </label>

      {error && <p className={`form-error${grid ? ' span-2' : ''}`}>{error}</p>}

      <div className={`form-actions${grid ? ' span-2' : ''}`}>
        <button type="submit" className="btn btn-primary" disabled={submitting}>
          {submitting ? 'Saving…' : isEditing ? 'Save changes' : 'Create program'}
        </button>
        <button type="button" className="btn" onClick={onCancel} disabled={submitting}>
          Cancel
        </button>
      </div>
    </form>
  )
}
