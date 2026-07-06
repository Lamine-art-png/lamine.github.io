export function retryDelaySeconds(attempts: number): number {
  const value = Number.isFinite(attempts) ? attempts : 0;
  const bounded = Math.min(Math.max(value, 0), 6);
  return Math.min(900, 15 * 2 ** bounded);
}

export function shouldAcknowledgeUpstream(status: number): boolean {
  return status >= 200 && status < 300;
}

export function matchesConfiguredToken(supplied: string, primary?: string, previous?: string): boolean {
  if (!supplied) return false;
  return [primary, previous]
    .map((value) => (value || "").trim())
    .filter(Boolean)
    .some((candidate) => equalLengthSafeCompare(supplied, candidate));
}

function equalLengthSafeCompare(left: string, right: string): boolean {
  if (left.length !== right.length) return false;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return difference === 0;
}
