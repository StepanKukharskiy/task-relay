# Task Relay Web hosting

Build an isolated deployment with `python3 scripts/build_relay_web_server.py --out
/absolute/private/deploy-directory`. Upload only that directory to a separate
web service; it contains no Desktop runtime, project database or development
tunnel. It is separate from the existing Task Relay website.

The Docker image runs without root, exposes the hosting platform's `PORT`
(default 8080), and requires `TASK_RELAY_PUBLIC_ORIGIN` to be the actual HTTPS
origin. Set it after the host assigns its public domain. `/health` reports the
runtime version; `/mcp` is the stateless streamable HTTP endpoint. The health
route alone does not verify MCP discovery or ChatGPT operation.

No user authentication, separate account, database or volume is needed. The
service validates and returns supplied proposals/files in memory; reviewed
exports are delivered to the panel. It does not retain the user's material.
Application access logs are disabled. Hosting infrastructure may have its own
traffic/operational logs; confirm its practices before publishing a privacy
policy. No hosting retention commitments are implied by this source.

Transport guards reject requests over 2 MB (including chunked uploads), uploads
with 15 seconds of inactivity, more than eight concurrent MCP requests and more
than 300 MCP requests per minute per process. Busy responses include Retry-After;
these are global process limits, not per-user quotas or distributed protection.
Place the service behind the host's HTTPS ingress and edge protections. Do not
enable request-body logging or mount local Relay data. Selected ChatGPT file
URLs are fetched only from the supported OpenAI file domains.

Verify the real HTTPS endpoint using the MCP SDK, including discovery, proposal,
independent reviewed export, import, fresh context and revision lineage. Then
connect the existing development plugin to that server and run its review
cases in ChatGPT. The submission package connects to the verified `/mcp` URL;
building or deploying this directory does not publish a directory listing.
