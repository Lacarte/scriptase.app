/**
 * User-facing text for a failed API call. The api client parses the
 * standard {error:{code,message}} envelope into `err.message`/`err.code`;
 * include the stable code so the surfaced reason is diagnosable, and fall
 * back to the generic text only when there is no real message at all.
 */
export function apiErrorText(err, fallback) {
  const message = err?.message || fallback
  return err?.code ? `${message} [${err.code}]` : message
}
