// Page-lifetime guard for requests that outlive a confirmed deletion. Durable
// admission protection remains on the server; old promises cannot outlive reload.
const deleted = new Set<string>();
export function markSessionDeleted(session: string) { deleted.add(session); }
export function isDeletedSession(session: string) { return deleted.has(session); }
