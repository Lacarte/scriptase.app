/**
 * Scriptase endpoint configuration.
 *
 * V2 hardcoded ws://localhost:5050. Scriptase serves on :5000, and swapping one
 * hardcoded port for another only moves the bug: the socket would silently never
 * connect the moment SCRIPTASE_PORT is set, and it would look like a provider
 * fault rather than a launcher one.
 *
 * So the port is injected instead. tools/chromium.ps1 stages a copy of this
 * extension under data/chromium-extensions/ and rewrites the marked line below
 * with the port the backend actually bound. The values here are what a
 * hand-loaded extension gets when nobody has injected anything -- correct for
 * the default install, wrong for nothing.
 *
 *   host           WebSocket/HTTP host for the Scriptase backend.
 *   appPorts       Ports to probe for the backend. appPorts[0] is the HTTP base.
 *   uiPorts        Ports the app UI may be served from (Flask + the Vite dev
 *                  server), used to find the Scriptase tab.
 *   automationPort ai-web-auto's WebSocket server.
 *
 * The marker comment is load-bearing: Sync-ScriptaseExtensions matches on it.
 */
/* @scriptase-endpoint */ export const STS_ENDPOINT = {"host":"localhost","appPorts":[5000],"uiPorts":[5000,5173],"automationPort":8765};
