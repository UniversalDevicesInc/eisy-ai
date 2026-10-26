"""Network-facing MCP proxy: terminates TLS on a LAN-reachable TCP port and
relays already-passed-the-auth-hook traffic to nucore-ai's MCP server over a
Unix domain socket. See design/mcp-server.md (nucore-ai repo) for the full
design, and auth.py's own docstring for the AuthHook contract Phase 2 is
expected to fill in -- this package's own relay logic (proxy.py) is not
meant to change when that happens."""
