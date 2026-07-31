import { create } from 'zustand'

const API = '/api'

export const useStore = create((set, get) => ({
  // node type schemas from the backend
  nodeTypes: [],
  loadNodeTypes: async () => {
    const r = await fetch(`${API}/nodes`)
    const j = await r.json()
    set({ nodeTypes: j.nodes || [] })
  },

  // current workflow
  workflow: { id: null, name: 'Untitled Workflow', description: '', nodes: [], edges: [] },
  setWorkflow: (wf) => set({ workflow: wf }),
  setNodes: (nodes) => set((s) => ({ workflow: { ...s.workflow, nodes } })),
  setEdges: (edges) => set((s) => ({ workflow: { ...s.workflow, edges } })),
  updateMeta: (meta) => set((s) => ({ workflow: { ...s.workflow, ...meta } })),

  // saved workflows list
  saved: [],
  loadSaved: async () => {
    const r = await fetch(`${API}/workflows`)
    const j = await r.json()
    set({ saved: j.workflows || [] })
  },

  saveWorkflow: async () => {
    const wf = get().workflow
    const r = await fetch(`${API}/workflows`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(wf)
    })
    const saved = await r.json()
    set({ workflow: saved })
    await get().loadSaved()
    return saved
  },

  loadWorkflow: async (id) => {
    const r = await fetch(`${API}/workflows/${id}`)
    const wf = await r.json()
    set({ workflow: wf })
  },

  newWorkflow: () => set({
    workflow: { id: null, name: 'Untitled Workflow', description: '', nodes: [], edges: [] }
  }),

  // run
  runResult: null,
  running: false,
  runWorkflow: async () => {
    set({ running: true, runResult: null })
    try {
      const wf = get().workflow
      const r = await fetch(`${API}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workflow: wf, inputs: {} })
      })
      const result = await r.json()
      set({ runResult: result, running: false })
    } catch (e) {
      set({ running: false, runResult: { status: 'error', error: String(e) } })
    }
  },
}))
