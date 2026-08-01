import { memo } from 'react'

const Sidebar = memo(function Sidebar({ nodeTypes }) {
  const onDragStart = (e, type) => {
    e.dataTransfer.setData('application/aita-node', type)
    e.dataTransfer.effectAllowed = 'move'
  }
  return (
    <div className="sidebar">
      <h3>Nodes</h3>
      <p className="hint">Drag onto canvas →</p>
      {nodeTypes.length === 0 && <p className="hint muted-loading">Loading nodes…</p>}
      {nodeTypes.map(nt => {
        const s = nt.schema || nt
        return (
          <div
            key={nt.type}
            className="palette-node"
            draggable
            onDragStart={(e) => onDragStart(e, nt.type)}
            style={{ borderLeftColor: s.color || '#64748b' }}
          >
            <div className="palette-node-label">{s.label || nt.type}</div>
            <div className="palette-node-desc">{s.description}</div>
          </div>
        )
      })}
      <div className="sidebar-footer">
        <h4>Reference syntax</h4>
        <code>{'{{node_id.field}}'}</code>
        <p>Upstream node output</p>
        <code>{'${{env:MY_KEY}}'}</code>
        <p>Environment secret</p>
      </div>
    </div>
  )
})

export default Sidebar
