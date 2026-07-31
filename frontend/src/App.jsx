import React, { useCallback, useEffect, useMemo } from 'react'
import ReactFlow, {
  Background, Controls, MiniMap, addEdge, useNodesState, useEdgesState,
  Handle, Position, applyNodeChanges, applyEdgeChanges
} from 'reactflow'
import 'reactflow/dist/style.css'
import { useStore } from './store'
import Sidebar from './Sidebar'
import ConfigPanel from './ConfigPanel'
import ResultPanel from './ResultPanel'
import './App.css'

const NODE_COLORS = {
  llm: '#7c3aed', http: '#0ea5e9', code: '#16a34a',
  file: '#f59e0b', transform: '#ec4899',
}

function CustomNode({ id, data }) {
  const color = NODE_COLORS[data.type] || '#64748b'
  return (
    <div className="aita-node" style={{ borderColor: color }}>
      <Handle type="target" position={Position.Left} style={{ background: color }} />
      <div className="aita-node-header" style={{ background: color }}>
        {data.label || data.type}
      </div>
      <div className="aita-node-body">
        <code>{id}</code>
      </div>
      <Handle type="source" position={Position.Right} style={{ background: color }} />
    </div>
  )
}

const nodeTypes = { custom: CustomNode }

export default function App() {
  const { workflow, nodeTypes, loadNodeTypes, setNodes, setEdges, saved, loadSaved,
          saveWorkflow, newWorkflow, runWorkflow, running, runResult } = useStore()

  useEffect(() => { loadNodeTypes(); loadSaved() }, [])

  const [rfNodes, setRfNodes, onNodesChange] = useNodesState(
    workflow.nodes.map(n => ({ ...n, type: 'custom', data: { type: n.type, label: n.type, ...n.data } }))
  )
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState(workflow.edges)

  const onNodesChangeSync = useCallback((chg) => {
    onNodesChange(chg)
    const next = applyNodeChanges(chg, rfNodes)
    setNodes(next.map(({ id, type: _t, data, position, ...rest }) => ({
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

  const onDragOver = (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move' }
  const onDrop = useCallback((e) => {
    e.preventDefault()
    const type = e.dataTransfer.getData('application/aita-node')
    if (!type) return
    const schema = nodeTypes.find(n => n.type === type)
    const position = { x: e.clientX - 300, y: e.clientY - 60 }
    const id = `${type}_${Date.now().toString(36)}`
    const config = {}
    ;(schema?.fields || []).forEach(f => { if (f.default !== undefined) config[f.name] = f.default })
    const newNode = {
      id, type: 'custom', position,
      data: { type, label: schema?.label || type, config },
    }
    setRfNodes(nds => nds.concat(newNode))
    const storeNode = { id, type, config, position }
    setNodes([...rfNodes.map(n => ({ id: n.id, type: n.data.type, config: n.data.config || {}, position: n.position, data: n.data })), storeNode])
  }, [nodeTypes, rfNodes, setRfNodes, setNodes])

  const [selected, setSelected] = React.useState(null)
  const onNodeClick = useCallback((_, node) => {
    setSelected(node.id)
  }, [])

  const selectedNode = rfNodes.find(n => n.id === selected)

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
            nodeTypes={nodeTypes}
            fitView
          >
            <Background />
            <Controls />
            <MiniMap />
          </ReactFlow>
        </div>
        <div className="right-panel">
          <ConfigPanel node={selectedNode} onUpdate={(config) => {
            setRfNodes(nds => nds.map(n => n.id === selected ? { ...n, data: { ...n.data, config } } : n))
            setNodes(rfNodes.map(n => n.id === selected ? { ...n, type: n.data.type, config, position: n.position, data: n.data } : { id: n.id, type: n.data.type, config: n.data.config || {}, position: n.position, data: n.data }))
          }} />
          <ResultPanel result={runResult} running={running} />
        </div>
      </div>
    </div>
  )
}

function Topbar({ workflow, saved, onSave, onLoad, onNew, onRun, running }) {
  const { updateMeta } = useStore()
  return (
    <div className="topbar">
      <div className="brand">⚡ Agents-in-the-air</div>
      <input
        className="wf-name"
        value={workflow.name}
        onChange={e => updateMeta({ name: e.target.value })}
      />
      <button onClick={onSave}>💾 Save</button>
      <select onChange={e => e.target.value && onLoad(e.target.value)} value="">
        <option value="">Load...</option>
        {saved.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}
      </select>
      <button onClick={onNew}>+ New</button>
      <button className="run-btn" onClick={onRun} disabled={running}>
        {running ? '⏳ Running...' : '▶ Run'}
      </button>
    </div>
  )
}
