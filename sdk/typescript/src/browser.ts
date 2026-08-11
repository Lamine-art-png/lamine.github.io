export function createBrowserClient(): never {
  throw new Error("AGRO-AI Platform API keys are server credentials and cannot be used in browser code");
}
