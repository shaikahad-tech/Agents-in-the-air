import React, { useCallback, useEffect, useMemo, memo } from 'react'
import ReactFlow, {
  Background, Controls, MiniMap, addEdge, useNodesState, useEdgesState,
  Handle, Position, applyNodeChanges,
} from 'reactflow'
import 'reactflow/dist/style.css'
import { useStore } from './store'
import Sidebar from './Sidebar'
import ConfigPanel from './ConfigPanel'
import ResultPanel from './ResultPanel'
import Toast from './Toast'
import './App.css'

const NODE_COLORS = {
  llm: '#7c3aed', http: '#0ea5e9', code: '#16a34a',
  file: '#f59e0b', transform: '#ec4899',
}

const NODE_ICONS = {
  llm: '🧠', http: '🌐', code: '🐍', file: '📄', transform: '🔧',
}

// ─── Custom node (memoized — prevents re-render of all nodes on any change) ─
const CustomNode = memo(function CustomNode({ id, data, selected }) {
  const color = NODE_COLORS[data.type] || '#64748b'
  const icon = NODE_ICONS[data.type] || '⚡'
  return (
    <div className={`aita-node ${selected ? 'aita-node-selected' : ''}`} style={{ borderColor: color }}>
      <Handle type="target" position={Position.Left} style={{ background: color, width: 10, height: 10 }} />
      <div className="aita-node-header" style={{ background: color }}>
        <span className="aita-node-icon">{icon}</span>
        {data.label || data.type}
      </div>
      <div className="aita-node-body">
        <code>{id}</code>
      </div>
      <Handle type="source" position={Position.Right} style={{ background: color, width: 10, height: 10 }} />
    </div>
  )
})

// ReactFlow nodeTypes — defined ONCE outside the component to prevent re-renders
const rfNodeTypes = { custom: CustomNode }

export default function App() {
  const { workflow, nodeTypes, loadNodeTypes, setNodes, setEdges, saved, loadSaved,
          saveWorkflow, newWorkflow, runWorkflow, running, runResult,
          saving, toast, dismissToast } = useStore()

  useEffect(() => { loadNodeTypes(); loadSaved() }, [])

  const [rfNodes, setRfNodes, onNodesChange] = useNodesState(
    workflow.nodes.map(n => ({
      ...n, type: 'custom', data: { type: n.type, label: n.type, ...n.data }
    }))
  )
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState(workflow.edges)

  const onNodesChangeSync = useCallback((chg) => {
    onNodesChange(chg)
    const next = applyNodeChanges(chg, rfNodes)
    setNodes(next.map(({ id, data, position }) => ({
      id, type: data.type, config: data.config || {}, position, data
    })))
  }, [rfNodes, onNodesChange, setNodes])

  const onEdgesChangeSync = useCallback((chg) => {
    onEdgesChange(chg)
    setEdges(applyEdgeChanges(chg, rfEdges))
  }, [rfEdges, onEdgesChange, setEdges])

  const onConnect = useCallback((conn) => {
    setRfEdges(eds => addEdge({ ...conn, animated: true }, eds))
    const next = addEdge({ ...conn, animated: true }, rfEdges)
    setEdges(next)
  }, [rfEdges, setRfEdges, setEdges])

  const onDragOver = useCallback((e) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }, [])

  const onDrop = useCallback((e) => {
    e.preventDefault()
    const type = e.dataTransfer.getData('application/aita-node')
    if (!type) return
    const schema = nodeTypes.find(n => n.type === type)
    const position = { x: e.clientX - 340, y: e.clientY - 80 }
    const id = `${type}_${Date.now().toString(36)}`
    const config = {}
    ;(schema?.fields || []).forEach(f => {
      if (f.default !== undefined) config[f.name] = f.default
    })
    const newNode = {
      id, type: 'custom', position,
      data: { type, label: schema?.label || type, config },
    }
    setRfNodes(nds => nds.concat(newNode))
    const storeNode = { id, type, config, position }
    setNodes([...rfNodes.map(n => ({
      id: n.id, type: n.data.type, config: n.data.config || {}, position: n.position, data: n.data
    })), storeNode])
  }, [nodeTypes, rfNodes, setRfNodes, setNodes])

  const [selected, setSelected] = React.useState(null)
  const onNodeClick = useCallback((_, node) => setSelected(node.id), [])
  const onPaneClick = useCallback(() => setSelected(null), [])

  const selectedNode = useMemo(
    () => rfNodes.find(n => n.id === selected),
    [rfNodes, selected]
  )

  const onConfigUpdate = useCallback((config) => {
    if (!selected) return
    setRfNodes(nds => nds.map(n =>
      n.id === selected ? { ...n, data: { ...n.data, config } } : n
    ))
    setNodes(rfNodes.map(n =>
      n.id === selected
        ? { ...n, type: n.data.type, config, position: n.position, data: n.data }
        : { id: n.id, type: n.data.type, config: n.data.config || {}, position: n.position, data: n.data }
    ))
  }, [selected, rfNodes, setRfNodes, setNodes])

  return (
    <div className="app">
      <Topbar
        workflow={workflow}
        saved={saved}
        onSave={saveWorkflow}
        onLoad={useStore(s => s.loadWorkflow)}
        onNew={newWorkflow}
        onRun={runWorkflow}
        running={running}
        saving={saving}
      />
      <div className="main">
        <Sidebar nodeTypes={nodeTypes} />
        <div className="canvas" onDrop={onDrop} onDragOver={onDragOver}>
          <ReactFlow
            nodes={rfNodes}
            edges={rfEdges}
            onNodesChange={onNodesChangeSync}
            onEdgesChange={onEdgesChangeSync}
            onConnect={onConnect}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            nodeTypes={rfNodeTypes}
            fitView
            deleteKeyCode={['Backspace', 'Delete']}
            defaultEdgeOptions={{ animated: true, style: { stroke: '#475569', strokeWidth: 2 } }}
          >
            <Background color="#1e293b" gap={20} size={1} />
            <Controls className="rf-controls" />
            <MiniMap
              nodeColor={(n) => NODE_COLORS[n.data?.type] || '#64748b'}
              maskColor="rgba(15, 23, 42, 0.7)"
              className="rf-minimap"
            />
          </ReactFlow>
        </div>
        <div className="right-panel">
          <ConfigPanel node={selectedNode} onUpdate={onConfigUpdate} />
          <ResultPanel result={runResult} running={running} />
        </div>
      </div>
      <Toast toast={toast} onDismiss={dismissToast} />
    </div>
  )
}

// ─── Topbar ───────────────────────────────────────────────────────────────
const Topbar = memo(function Topbar({ workflow, saved, onSave, onLoad, onNew, onRun, running, saving }) {
  const { updateMeta } = useStore()
  return (
    <div className="topbar">
      <div className="brand">
        <span className="brand-icon">⚡</span>
        <span className="brand-text">Agents-in-the-air</span>
      </div>
      <input
        className="wf-name"
        value={workflow.name}
        onChange={e => updateMeta({ name: e.target.value })}
        placeholder="Workflow name…"
      />
      <button onClick={onSave} disabled={saving} className="btn btn-secondary">
        {saving ? '⏳ Saving…' : '💾 Save'}
      </button>
      <select onChange={e => e.target.value && onLoad(e.target.value)} value="">
        <option value="">📂 Load…</option>
        {saved.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
      </select>
      <button onClick={onNew} className="btn btn-secondary">✨ New</button>
      <button className="btn btn-primary run-btn" onClick={onRun} disabled={running}>
        {running ? <><span className="spinner" /> Running…</> : '▶ Run Workflow'}
      </button>
    </div>
  )
})
