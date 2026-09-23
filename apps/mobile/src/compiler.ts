export type Snapshot = { version: string; commit: string; manifest_sha256: string };
export type Connection = { url: string; token: string };
export type RunResult = { compiler: Snapshot; ok: boolean; stdout: string;
  diagnostics: { message?: string; level?: string }[]; clarifications: unknown[] };

export function serviceUrl(raw: string, development: boolean): string {
  let url: URL;
  try { url = new URL(raw.trim()); } catch { throw new Error('Enter your compiler service URL.'); }
  if (url.username || url.password || url.search || url.hash || (url.pathname !== '/' && url.pathname !== '')) {
    throw new Error('Use a base URL without credentials, a path, or query parameters.');
  }
  if (url.protocol !== 'https:' && !(development && url.protocol === 'http:')) {
    throw new Error('The compiler connection must use HTTPS.');
  }
  return url.origin;
}
export function sameSnapshot(actual: Snapshot, expected: Snapshot) {
  return actual?.commit === expected.commit && actual?.version === expected.version &&
    actual?.manifest_sha256 === expected.manifest_sha256;
}
export async function compilerRequest(connection: Connection, path: string, development: boolean,
  body?: unknown, fetcher: typeof fetch = fetch) {
  const url = serviceUrl(connection.url, development);
  if (!connection.token.trim()) throw new Error('Add the compiler access token in Connection.');
  const abort = new AbortController();
  const timeout = setTimeout(() => abort.abort(), 25000);
  try {
    const response = await fetcher(url + path, {
      method: body === undefined ? 'GET' : 'POST', signal: abort.signal, redirect: 'error',
      headers: { Authorization: 'Bearer ' + connection.token, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const value = await response.json();
    if (!response.ok) throw new Error(value.error || `Compiler request failed (${response.status}).`);
    return value;
  } catch (error) {
    if (abort.signal.aborted) throw new Error('The compiler took too long. Your note is still saved.');
    if (error instanceof TypeError) throw new Error('Cannot reach the compiler. Check your connection and service URL.');
    throw error;
  } finally { clearTimeout(timeout); }
}
export async function runNote(connection: Connection, source: string, expected: Snapshot,
  development: boolean, fetcher: typeof fetch = fetch, mode: 'run' | 'check' = 'run'): Promise<RunResult> {
  if (!source.trim()) throw new Error('Write a program first. Try: Show the sum of 2 and 3.');
  const value = await compilerRequest(connection, '/v1/' + mode, development, { source, compiler: expected }, fetcher);
  if (!sameSnapshot(value.compiler, expected)) throw new Error('Compiler snapshot mismatch. Update the app and service together.');
  if (typeof value.ok !== 'boolean' || typeof value.stdout !== 'string' || !Array.isArray(value.diagnostics) || !Array.isArray(value.clarifications)) {
    throw new Error('The compiler returned an unreadable response.');
  }
  return value;
}
export function terminalText(result: RunResult) {
  if (result.ok) return result.stdout || 'Finished. No printed output.';
  const diagnostics = result.diagnostics.map(d => d.message).filter(Boolean).join('\n');
  return diagnostics || (result.clarifications.length ? JSON.stringify(result.clarifications, null, 2) : 'This program needs clarification.');
}
