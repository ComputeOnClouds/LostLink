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
