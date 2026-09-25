// Hash router (ADR-006). Pure matching functions are unit-tested.

/**
 * @typedef {Object} RouteDef
 * @property {string} name
 * @property {string} pattern e.g. "/agentes/:id"
 */
/**
 * @typedef {Object} RouteMatch
 * @property {string} name
 * @property {Record<string, string>} params
 * @property {string} path
 * @property {URLSearchParams} query
 */

/**
 * Normalize "#/agentes/x?y=1" to { path: "/agentes/x", query }.
 * @param {string} hash
 * @returns {{path: string, query: URLSearchParams}}
 */
export function parseHash(hash) {
  const raw = (hash || '').replace(/^#/, '') || '/';
  const [pathPart, queryPart = ''] = raw.split('?');
  let path = pathPart.startsWith('/') ? pathPart : '/' + pathPart;
  if (path.length > 1) path = path.replace(/\/+$/, '');
  return { path, query: new URLSearchParams(queryPart) };
}

/**
 * @param {RouteDef[]} routes
 * @param {string} hash
 * @returns {RouteMatch|null}
 */
export function matchRoute(routes, hash) {
  const { path, query } = parseHash(hash);
  const segments = path.split('/').filter(Boolean);
  for (const route of routes) {
    const parts = route.pattern.split('/').filter(Boolean);
    if (parts.length !== segments.length) continue;
    /** @type {Record<string, string>} */
    const params = {};
    let ok = true;
    for (let i = 0; i < parts.length; i += 1) {
      if (parts[i].startsWith(':')) {
        try {
          params[parts[i].slice(1)] = decodeURIComponent(segments[i]);
        } catch {
          ok = false;
          break;
        }
      } else if (parts[i] !== segments[i]) {
        ok = false;
        break;
      }
    }
    if (ok) return { name: route.name, params, path, query };
  }
  return null;
}

/**
 * Build a hash for a route pattern.
 * @param {string} pattern
 * @param {Record<string, string>} [params]
 */
export function href(pattern, params = {}) {
  return '#' + pattern.replace(/:([a-zA-Z]+)/g, (_m, key) => encodeURIComponent(params[key] ?? ''));
}

/**
 * @param {RouteDef[]} routes
 * @param {(match: RouteMatch|null) => void} onChange
 * @returns {{start: () => void, stop: () => void, go: (hash: string) => void}}
 */
export function createRouter(routes, onChange) {
  const listener = () => onChange(matchRoute(routes, window.location.hash));
  return {
    start() {
      window.addEventListener('hashchange', listener);
      listener();
    },
    stop() {
      window.removeEventListener('hashchange', listener);
    },
    go(hash) {
      if (window.location.hash === hash) listener();
      else window.location.hash = hash;
    },
  };
}
