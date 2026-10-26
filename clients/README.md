# Connecting an AI assistant

The ready made configurations for four clients.
[Connect your AI assistant](https://dpolens.com/docs/connect) has the steps for each of them, and
for any other client that speaks MCP over HTTP.

| Folder | What it holds |
| --- | --- |
| `claude-code/` | The Claude Code plugin's skill and its two commands, `/dpolens:policy-check` and `/dpolens:policy-tour`. The plugin installs from this repository's marketplace |
| `codex/` | `config.toml`, which goes to `~/.codex/config.toml`, or to `.codex/config.toml` in a trusted project |
| `cursor/` | `mcp.json`, which goes to `.cursor/mcp.json`, and `dpolens.mdc`, the rule that tells Cursor when to search, which goes to `.cursor/rules/dpolens.mdc` |
| `cursor-plugin/` | The Cursor plugin, which this repository's `.cursor-plugin/marketplace.json` lists. It connects to the community version, `https://mcp.dpolens.com/`, which holds the law alone and needs no token, and carries the same rule |
| `vscode/` | `mcp.json` for GitHub Copilot in VS Code, which goes to `.vscode/mcp.json` |

Except for the Cursor plugin, each needs the URL of your instance's MCP server, `http://localhost:8765/mcp` for a local
`docker compose up`, and your own personal access token, made in the dashboard under Tokens.
