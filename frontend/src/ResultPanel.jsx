import { memo, useState } from 'react'

const ResultPanel = memo(function ResultPanel({ result, running }) {
  const [expanded, setExpanded] = useState({})

  const toggle = (id) => setExpanded(s => ({ ...s, [id]: !s[id] }))

  return (
    <div className="result-panel">
      <h3>Results</h3>
      {running && (
        <div className="running-state">
          <div className="spinner spinner-lg" />
          <span>Executing workflow…</span>
        </div>
      )}
      {!running && !result && (
        <div className="empty-state">
          <div className="empty-state-icon">📊</div>
          <p>Run the workflow to see results here.</p>
        </div>
      )}
      {result && (
        <div>
          <div className={`status-badge ${result.status}`}>
            {result.status === 'success' ? '✅ Success' : '❌ Error'}
          </div>
          {result.duration_s != null && (
            <div className="muted">Completed in {result.duration_s}s</div>
          )}
          {result.error && (
            <div className="error-banner">
              <strong>Error:</strong> {result.error}
            </div>
          )}
          {result.nodes && (
            <div className="result-nodes">
              {Object.entries(result.nodes).map(([id, nr]) => (
                <div key={id} className={`result-node ${nr.status}`}>
                  <div className="result-node-header" onClick={() => toggle(id)}>
                    <strong>{id}</strong>
                    <span className={`status-pill ${nr.status}`}>
                      {nr.status === 'success' ? '✓' : nr.status === 'error' ? '✕' : '⊘'}
                      {' '}{nr.status}
                    </span>
                    {nr.output != null && (
                      <span className="expand-toggle">{expanded[id] ? '▾' : '▸'}</span>
                    )}
                  </div>
                  {nr.error && <div className="error-msg">{nr.error}</div>}
                  {nr.output != null && expanded[id] && (
                    <pre className="result-output">
                      {JSON.stringify(nr.output, null, 2)?.slice(0, 5000)}
                    </pre>
                  )}
                  {nr.duration_s != null && (
                    <div className="result-duration">{nr.duration_s}s</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
})

export default ResultPanel
