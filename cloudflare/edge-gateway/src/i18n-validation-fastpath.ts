export function validationOnlyUrl(raw: string): string {
  const url = new URL(raw);
  url.searchParams.set("validate_only", "1");
  return url.toString();
}
