// Local audit trail of human decisions taken in this browser. It complements,
// never replaces, the server records: entries are labelled "local".
import { readPref, writePref } from './storage.js';

const KEY = 'audit';
const MAX = 300;

/** @typedef {import('../types.js').AuditEvent} AuditEvent */

/** @returns {AuditEvent[]} */
export function listAudit() {
  const items = readPref(KEY, /** @type {AuditEvent[]} */ ([]));
  return Array.isArray(items) ? items : [];
}

/**
 * @param {Omit<AuditEvent, 'id'|'at'|'recordedIn'>} entry
 * @returns {AuditEvent}
 */
export function recordAudit(entry) {
  /** @type {AuditEvent} */
  const event = { ...entry, id: 'aud-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 7),
                  at: new Date().toISOString(), recordedIn: 'local' };
  const items = [event, ...listAudit()].slice(0, MAX);
  writePref(KEY, items);
  return event;
}
