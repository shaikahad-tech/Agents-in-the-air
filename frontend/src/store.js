import { create } from 'zustand'

const API = '/api'

// Centralized API helper — handles errors, auth header, JSON parsing
async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...opts.headers }
  // Attach API key if available (stored in localStorage by the user)
  const apiKey = localStorage.getItem('aita_api_key')
  if (apiKey) headers['X-API-Key'] = apiKey

  const r = await fetch(`${API}${path}`, { ...opts, headers })
  if (!r.ok) {
    let detail = `HTTP ${r.status}`
    try { const j = await r.json(); detail = j.detail || detail } catch { /* not JSON */ }
    throw new Error(detail)
  }
  return r.json()
}

export const useStore = create((set, get) => ({
  // ─── Node type schemas from the backend ───────────────────────────
  nodeTypes: [],
  loadingNodes: false,
  loadNodeTypes: async () => {
    set({ loadingNodes: true })
    try {
      const j = await api('/nodes')
      set({ nodeTypes: j.nodes || [], loadingNodes: false })
    } catch (e) {
      set({ loadingNodes: false, error: e.message })
    }
  },

  // ─── Current workflow ─────────────────────────────────────────────
  workflow: { id: null, name: 'Untitled Workflow', description: '', nodes: [], edges: [] },
  setWorkflow: (wf) => set({ workflow: wf }),
  setNodes: (nodes) => set((s) => ({ workflow: { ...s.workflow, nodes } })),
  setEdges: (edges) => set((s) => ({ workflow: { ...s.workflow, edges } })),
  updateMeta: (meta) => set((s) => ({ workflow: { ...s.workflow, ...meta } })),

  // ─── Saved workflows list ────────────────────────────────────────
  saved: [],
  loadSaved: async () => {
    try {
      const j = await api('/workflows?page=1&page_size=100')
      set({ saved: j.workflows || [] })
    } catch (e) {
      set({ error: e.message })
    }
  },

  saveWorkflow: async () => {
    const wf = get().workflow
    set({ saving: true })
    try {
      const saved = await api('/workflows', {
        method: 'POST',
        body: JSON.stringify(wf),
      })
      set({ workflow: saved, saving: false, toast: { type: 'success', msg: 'Workflow saved!' } })
      await get().loadSaved()
      get()._clearToast()
      return saved
    } catch (e) {
      set({ saving: false, toast: { type: 'error', msg: `Save failed: ${e.message}` } })
      get()._clearToast()
      throw e
    }
  },

  loadWorkflow: async (id) => {
    try {
      const wf = await api(`/workflows/${id}`)
      set({ workflow: wf })
    } catch (e) {
      set({ toast: { type: 'error', msg: `Load failed: ${e.message}` } })
      get()._clearToast()
    }
  },

  newWorkflow: () => set({
    workflow: { id: null, name: 'Untitled Workflow', description: '', nodes: [], edges: [] },
    runResult: null,
  }),

  // ─── Run workflow ────────────────────────────────────────────────
  runResult: null,
  running: false,
  runWorkflow: async () => {
    const wf = get().workflow
    if (!wf.nodes.length) {
      set({ toast: { type: 'error', msg: 'Add at least one node before running.' } })
      get()._clearToast()
      return
    }
    set({ running: true, runResult: null })
    try {
      const result = await api('/run', {
        method: 'POST',
        body: JSON.stringify({ workflow: wf, inputs: {} }),
      })
      set({ runResult: result, running: false })
      if (result.status === 'error') {
        set({ toast: { type: 'error', msg: 'Workflow completed with errors.' } })
      } else {
        set({ toast: { type: 'success', msg: 'Workflow completed successfully!' } })
      }
      get()._clearToast()
    } catch (e) {
      set({ running: false, runResult: { status: 'error', error: e.message },
            toast: { type: 'error', msg: `Run failed: ${e.message}` } })
      get()._clearToast()
    }
  },

  // ─── Toast / notification ────────────────────────────────────────
  toast: null,
  _clearToast: () => {
    setTimeout(() => set({ toast: null }), 3500)
  },
  dismissToast: () => set({ toast: null }),
}))
