// Asynchronous loader hooks of the cache capture (src/cache/capture.js, installAsyncLoaderHooks): every file Node's
// loader loads, and every specifier it fails to resolve, is posted to the thread that registered the hooks.
let port = null;

export function initialize(data) {
  port = data && data.port;
}

export async function resolve(specifier, context, next) {
  if (port && (specifier === 'node:sqlite' || specifier === 'sqlite')) port.postMessage({ sqlite: true });
  try {
    return await next(specifier, context);
  } catch (e) {
    if (port) port.postMessage({ failed: String(specifier), parent: context && context.parentURL });
    throw e;
  }
}

export async function load(url, context, next) {
  if (port && typeof url === 'string' && url.startsWith('file:')) port.postMessage({ loaded: url });
  return next(url, context);
}
