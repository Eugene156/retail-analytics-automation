// Loaded through stdin in demo n8n. P3_CONFIG is supplied privately by start.
'use strict';
const { createRequire } = require('node:module');
const sdk = createRequire('/usr/local/lib/node_modules/n8n/node_modules/@n8n/n8n-nodes-langchain/package.json');
const { McpServer } = sdk('@modelcontextprotocol/sdk/server/mcp.js');
const { StreamableHTTPServerTransport } = sdk('@modelcontextprotocol/sdk/server/streamableHttp.js');
const { z } = sdk('zod');
const http = require('node:http');
const crypto = require('node:crypto');
const definitions = [
  ['get_sales_kpis', 'sales-kpis', 'Read real PostgreSQL sales KPIs for 2011-01-28 09:00-10:00 Europe/London. No writes or arguments.'],
  ['get_data_quality', 'data-quality', 'Read real PostgreSQL data quality findings and missing customer counts for the same demo period. No writes or arguments.'],
];
// Serialize the two tools over the existing single-slot read calculator.
let tail = Promise.resolve();
let pending = 0;
async function read(endpoint) {
  if (pending >= 2) throw new Error('busy');
  pending++;
  const task = tail.then(async () => {
    const response = await fetch('http://api:8001/api/p2/' + endpoint, {
      method: 'GET', redirect: 'error', signal: AbortSignal.timeout(130000),
      headers: { Authorization: 'Bearer ' + P3_CONFIG.apiToken },
    });
    if (!response.ok) throw new Error('unavailable');
    const result = await response.json();
    if (result.schema_version !== 'p2-read-tool-v1' || result.access !== 'read-only') throw new Error('contract');
    return result;
  });
  tail = task.catch(() => {});
  try { return await task; } finally { pending--; }
}

function makeServer() {
  const server = new McpServer({ name: 'raa-p3-demo-read-tools', version: '1.0.0' });
  for (const [name, endpoint, description] of definitions) {
    server.registerTool(name, {
      description, inputSchema: z.object({}).strict(),
      annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
    }, async () => {
      try {
        const result = await read(endpoint);
        return { content: [{ type: 'text', text: JSON.stringify(result) }], structuredContent: result };
      } catch {
        return { isError: true, content: [{ type: 'text', text: 'Read tool unavailable; no business action taken.' }] };
      }
    });
  }
  return server;
}

function authorized(req) {
  const incoming = Buffer.from(req.headers.authorization || '');
  const expected = Buffer.from('Bearer ' + P3_CONFIG.mcpToken);
  return incoming.length === expected.length && crypto.timingSafeEqual(incoming, expected);
}

function reject(res, status) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ error: 'Request denied' }));
}

const listener = http.createServer(async (req, res) => {
  if (req.url !== '/mcp' || req.headers.host !== '127.0.0.1:8002' || req.headers.origin) return reject(res, 403);
  if (!authorized(req)) return reject(res, 401);
  if (req.method !== 'POST') return reject(res, 405); // No optional SSE listen stream.
  let server, transport;
  try {
    let body = '';
    for await (const chunk of req) {
      body += chunk.toString('utf8');
      if (Buffer.byteLength(body) > 8192) return reject(res, 413);
    }
    const message = JSON.parse(body);
    if (!['initialize', 'notifications/initialized', 'tools/list', 'tools/call', 'ping', 'notifications/cancelled'].includes(message.method)) return reject(res, 403);
    server = makeServer();
    transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined, enableJsonResponse: true });
    res.on('close', () => { transport.close().catch(() => {}); server.close().catch(() => {}); });
    await server.connect(transport);
    await transport.handleRequest(req, res, message);
  } catch {
    if (!res.headersSent) reject(res, 400);
    else if (!res.writableEnded) res.end();
  }
});
listener.requestTimeout = 150000;
listener.headersTimeout = 10000;
listener.on('error', () => { process.exitCode = 1; });
listener.listen(8002, '127.0.0.1');
