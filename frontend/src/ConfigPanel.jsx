import { memo, useCallback } from 'react'
import { useStore } from './store'

const ConfigPanel = memo(function ConfigPanel({ node, onUpdate }) {
  const { nodeTypes } = useStore()

  const setField = useCallback((name, value) => {
    onUpdate({ ...(node.data.config || {}), [name]: value })
  }, [node, onUpdate])

  if (!node) {
    return (
      <div className="config-panel">
        <h3>Configuration</h3>
        <div className="empty-state">
          <div className="empty-state-icon">⚙️</div>
          <p>Select a node on the canvas to edit its configuration.</p>
        </div>
      </div>
    )
  }

  const schema = nodeTypes.find(n => n.type === node.data.type)
  const config = node.data.config || {}
  const s = schema?.schema || schema || {}
  const fields = s.fields || []
  const label = s.label || node.data.label || node.data.type

  return (
    <div className="config-panel">
      <h3>Config — {label}</h3>
      <div className="config-node-id"><code>id: {node.id}</code></div>
      {fields.length === 0 && <p className="hint">No configurable fields.</p>}
      {fields.map(f => (
        <div key={f.name} className="field">
          <label>{f.name}{f.required ? <span className="required"> *</span> : ''}</label>
          {renderField(f, config[f.name], setField)}
        </div>
      ))}
    </div>
  )
})

function renderField(f, value, set) {
  if (f.type === 'select') {
    return (
      <select value={value ?? ''} onChange={e => set(f.name, e.target.value)}>
        <option value="" disabled>Select…</option>
        {f.options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    )
  }
  if (f.type === 'boolean') {
    return (
      <label className="switch">
        <input type="checkbox" checked={!!value} onChange={e => set(f.name, e.target.checked)} />
        <span className="switch-track"><span className="switch-thumb" /></span>
      </label>
    )
  }
  if (f.type === 'number') {
    return <input type="number" value={value ?? ''} step="0.1"
      onChange={e => set(f.name, parseFloat(e.target.value))} />
  }
  if (f.type === 'textarea') {
    return <textarea rows="4" value={value ?? ''}
      onChange={e => set(f.name, e.target.value)}
      placeholder={f.default ?? ''} />
  }
  if (f.type === 'code') {
    return <textarea rows="10" className="code-editor" value={value ?? ''}
      onChange={e => set(f.name, e.target.value)}
      spellCheck={false}
      placeholder={f.default ?? ''} />
  }
  if (f.type === 'object') {
    return <textarea rows="4" value={JSON.stringify(value ?? {}, null, 2)}
      onChange={e => { try { set(f.name, JSON.parse(e.target.value)) } catch { /* partial JSON */ } }}
      spellCheck={false} />
  }
  if (f.type === 'secret') {
    return (
      <div className="secret-field">
        <input type="password" value={value ?? ''}
          onChange={e => set(f.name, e.target.value)}
          placeholder={f.default ?? 'Enter value or use ${{env:…}}'} />
        <span className="secret-icon">🔒</span>
      </div>
    )
  }
  return <input type="text" value={value ?? ''}
    onChange={e => set(f.name, e.target.value)}
    placeholder={f.default ?? ''} />
}

export default ConfigPanel
