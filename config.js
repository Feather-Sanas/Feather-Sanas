/* Backend origin for the hosted front-end.
 *
 * Empty string = same-origin: use this when the FastAPI backend serves these files
 * itself (local dev, EC2 single-host). When the front-end is hosted separately
 * (e.g. AWS Amplify), set this to the backend's public origin, e.g.
 *   window.SAN_API_BASE = "https://api.your-domain.com";
 *
 * On Amplify this file is REGENERATED at build time from the SAN_API_BASE
 * environment variable (see amplify.yml), so you don't edit it by hand there —
 * set SAN_API_BASE in the Amplify console. This committed copy is the
 * same-origin fallback used when the backend serves the front-end.
 */
window.SAN_API_BASE = window.SAN_API_BASE || "";
