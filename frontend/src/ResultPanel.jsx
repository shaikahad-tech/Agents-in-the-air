export default function ResultPanel({ result, running }) {
  return (
    <div className="result-panel">
      <h3>Result</h3>
      {running && <div className="muted">Running workflow...</div>}
      {!running && !result && <div className="muted">Run the workflow to see results.</div>}
      {result && (
        <div>
          <div className={`status-badge ${result.status}`}>{result.status}</div>
          {result.duration_s != null && <div className="muted">completed in {result.duration_s}s</div>}
          {result.error && <div className="error-msg">{result.error}</div>}
          {result.nodes && (
            <div className="result-nodes">
              {Object.entries(result.nodes).map(([id, nr]) => (
                <div key={id} className={`result-node ${nr.status}`}>
                  <div className="result-node-header">
                    <strong>{id}</strong>
                    <span className={`status-dot ${nr.status}`}>*</span>
                  </div>
                  {nr.error && <div className="error-msg">{nr.error}</div>}
                  {nr.output != null && (
                    <pre className="result-output">{JSON.stringify(nr.output, null, 2)?.slice(0, 2000)}</pre>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
