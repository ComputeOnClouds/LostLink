/**
 * nowLocal() -> current local time formatted for <input type="datetime-local">
 * (YYYY-MM-DDTHH:mm). Forms prefill their time field with this so the user sees and can
 * change the value that will be submitted; if left unchanged, this exact time is sent
 * (matches the backend "default to now" behaviour, made explicit in the UI).
 */
export function nowLocal(): string {
  const d = new Date();
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

export function isoToLocalInput(value?: string | null): string {
  if (!value) return nowLocal();
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 16);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

export function formatLocalTime(value?: string | null): string {
  if (!value) return 'Time not provided';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
