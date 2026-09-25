// Declarative validation for forms and for data crossing the network boundary.
import { t } from './i18n.js';

/**
 * @typedef {Object} Rule
 * @property {boolean} [required]
 * @property {number} [minLength]
 * @property {number} [maxLength]
 * @property {number} [min]
 * @property {number} [max]
 * @property {boolean} [integer]
 * @property {RegExp} [pattern]
 * @property {string} [patternMessage] i18n key
 * @property {readonly string[]} [oneOf]
 * @property {(value: string, values: Record<string, string>) => string|null} [check] returns an i18n key or null
 */
/** @typedef {Record<string, Rule>} Schema */

/**
 * Validate string form values. Returns field → message (empty when valid).
 * @param {Schema} schema
 * @param {Record<string, string>} values
 * @returns {Record<string, string>}
 */
export function validate(schema, values) {
  /** @type {Record<string, string>} */
  const errors = {};
  for (const [field, rule] of Object.entries(schema)) {
    const raw = values[field] ?? '';
    const value = raw.trim();
    if (!value) {
      if (rule.required) errors[field] = t('validation.required');
      continue;
    }
    if (rule.minLength !== undefined && value.length < rule.minLength) {
      errors[field] = t('validation.minLength', { n: rule.minLength });
    } else if (rule.maxLength !== undefined && value.length > rule.maxLength) {
      errors[field] = t('validation.maxLength', { n: rule.maxLength });
    } else if (rule.min !== undefined || rule.max !== undefined || rule.integer) {
      const number = Number(value.replace(',', '.'));
      if (!Number.isFinite(number)) errors[field] = t('validation.number');
      else if (rule.integer && !Number.isInteger(number)) errors[field] = t('validation.integer');
      else if (rule.min !== undefined && number < rule.min) errors[field] = t('validation.min', { n: rule.min });
      else if (rule.max !== undefined && number > rule.max) errors[field] = t('validation.max', { n: rule.max });
    } else if (rule.pattern && !rule.pattern.test(value)) {
      errors[field] = t(rule.patternMessage || 'validation.pattern');
    } else if (rule.oneOf && !rule.oneOf.includes(value)) {
      errors[field] = t('validation.oneOf');
    }
    if (!errors[field] && rule.check) {
      const key = rule.check(value, values);
      if (key) errors[field] = t(key);
    }
  }
  return errors;
}

/** Error raised when a response does not match the expected contract. */
export class ContractError extends Error {
  /** @param {string} what @param {string} path */
  constructor(what, path) {
    super(`Respuesta inesperada del servidor: ${what} en ${path}`);
    this.name = 'ContractError';
  }
}

/**
 * @param {unknown} value
 * @param {string} path
 * @returns {Record<string, unknown>}
 */
export function expectObject(value, path) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new ContractError('se esperaba un objeto', path);
  return /** @type {Record<string, unknown>} */ (value);
}

/**
 * @param {unknown} value
 * @param {string} path
 * @returns {unknown[]}
 */
export function expectArray(value, path) {
  if (!Array.isArray(value)) throw new ContractError('se esperaba una lista', path);
  return value;
}

/**
 * @param {Record<string, unknown>} obj
 * @param {string} key
 * @param {string} path
 * @returns {string}
 */
export function str(obj, key, path) {
  const value = obj[key];
  if (typeof value !== 'string') throw new ContractError(`se esperaba texto en '${key}'`, path);
  return value;
}

/**
 * @param {Record<string, unknown>} obj
 * @param {string} key
 * @returns {string|null}
 */
export function optStr(obj, key) {
  const value = obj[key];
  return typeof value === 'string' ? value : null;
}

/**
 * @param {Record<string, unknown>} obj
 * @param {string} key
 * @returns {number|null}
 */
export function optNum(obj, key) {
  const value = obj[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/**
 * @param {Record<string, unknown>} obj
 * @param {string} key
 * @returns {string[]}
 */
export function strList(obj, key) {
  const value = obj[key];
  return Array.isArray(value) ? value.filter((item) => typeof item === 'string') : [];
}
