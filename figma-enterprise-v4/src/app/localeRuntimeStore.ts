let revision = 0;
const listeners = new Set<() => void>();

export function subscribeLocaleRuntime(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getLocaleRuntimeSnapshot() {
  return revision;
}

export function notifyLocaleRuntime() {
  revision += 1;
  for (const listener of listeners) listener();
}
