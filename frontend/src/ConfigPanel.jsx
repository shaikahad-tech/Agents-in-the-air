import { useStore } from './store'

export default function ConfigPanel({ node, onUpdate }) {
  const { nodeTypes } = useStore()
  if (!node) {
    return <div className="config-panel"><h3>Config</h3><p className="muted">Select a node to edit its config.</p></div>
  }
  const schema = nodeTypes.find(n => n.type === node.data.type)
  const config = node.data.config || {}

  const setField = (name, value) => {
    onUpdate({ ...config, [name]: value })
  }

  return (
    <div className="config-panel">
      <h3>Config - {node.data.label}</h3>
      <div className="config-node-id"><code>id: {node.id}</code></div>
      {schema?.fields?.map(f => (
        <div key={f.name} className="field">
          <label>{f.name}{f.required ? ' *' : ''}</label>
          {renderField(f, config[f.name], setField)}
        </div>
      ))}
    </div>
  )
}

function renderField(f, value, set) {
  if (f.type === 'select') {
    return <select value={value ?? ''} onChange={e => set(f.name, e.target.value)}>
      {f.options.map(o => <option key={o} value={o}>{o}</option>)}
    </select>
  }
  if (f.type === 'boolean') {
    return <input type="checkbox" checked={!!value} onChange={e => set(f.name, e.target.checked)} />
  }
  if (f.type === 'number') {
    return <input type="number" value={value ?? ''} step="0.1" onChange={e => set(f.name, parseFloat(e.target.value))} />
  }
  if (f.type === 'textarea') {
    return <textarea rows="4" value={value ?? ''} onChange={e => set(f.name, e.target.value)} />
  }
  if (f.type === 'code') {
    return <textarea rows="10" className="code-editor" value={value ?? ''} onChange={e => set(f.name, e.target.value)} />
  }
  if (f.type === 'object') {
    return <textarea rows="4" value={JSON.stringify(value ?? {}, null, 2)}
      onChange={e => { try { set(f.name, JSON.parse(e.target.value)) } catch {} }} />
  }
  return <input type="text" value={value ?? ''} onChange={e => set(f.name, e.target.value)} placeholder={f.default ?? ''} />
}
