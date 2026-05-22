export function requestIdFrom(request: Request): string {
  const inbound = request.headers.get("X-Request-Id");
  return inbound && inbound.length <= 128 ? inbound : crypto.randomUUID();
}

