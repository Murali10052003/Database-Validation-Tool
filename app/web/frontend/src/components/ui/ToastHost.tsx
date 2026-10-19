import { useToast } from "../../state/ToastContext";

export function ToastHost() {
  const { toasts, dismiss } = useToast();
  return (
    <div className="toast-host" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast--${t.kind}`} onClick={() => dismiss(t.id)}>
          <span className="toast__dot" />
          <span className="toast__msg">{t.message}</span>
        </div>
      ))}
    </div>
  );
}
