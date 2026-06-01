import { actions, useCommandStore } from "../state/commandStore";

export function Toast() {
  const message = useCommandStore((s) => s.toast);
  if (!message) return null;
  return (
    <div className="toast" role="status" aria-live="polite" onClick={() => actions.dismissToast()}>
      {message}
    </div>
  );
}
