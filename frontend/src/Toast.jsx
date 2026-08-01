import { memo, useEffect, useState } from 'react'

const Toast = memo(function Toast({ toast, onDismiss }) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (toast) {
      setVisible(true)
      const t = setTimeout(() => setVisible(false), 3200)
      return () => clearTimeout(t)
    }
  }, [toast])

  if (!toast) return null

  const icon = toast.type === 'success' ? '✅' : toast.type === 'error' ? '❌' : 'ℹ️'

  return (
    <div className={`toast-container ${visible ? 'toast-show' : 'toast-hide'}`}>
      <div className={`toast ${toast.type}`} onClick={onDismiss}>
        <span className="toast-icon">{icon}</span>
        <span className="toast-msg">{toast.msg}</span>
        <span className="toast-close">✕</span>
      </div>
    </div>
  )
})

export default Toast
