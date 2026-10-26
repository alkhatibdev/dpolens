<p align="center">
  <br>
  <br>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/brand/dpolens-logo-on-dark.svg">
    <img alt="DPOLens" src="docs/brand/dpolens-logo.svg" height="64">
  </picture>
  <br>
  <br>
</p>

<p align="center">
  <strong>DPOLens is an open-source MCP server that gives your AI coding assistant your
  organisation's privacy policies and the law, with exact, versioned citations.</strong>
</p>

<p align="center">
  <a href="https://github.com/alkhatibdev/dpolens/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/alkhatibdev/dpolens/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://github.com/alkhatibdev/dpolens/releases"><img alt="Release" src="https://img.shields.io/github/v/release/alkhatibdev/dpolens?filter=v*&sort=semver&label=release&color=12784E"></a>
  <a href="LICENSE"><img alt="Licence: Apache-2.0" src="https://img.shields.io/badge/licence-Apache--2.0-12784E"></a>
</p>

<p align="center">
  <a href="https://dpolens.com/docs/introduction">Docs</a> ·
  <a href="https://dpolens.com/docs/get-started">Get started</a> ·
  <a href="https://dpolens.com/community">Community version</a> ·
  <a href="https://dpolens.com/laws">Supported laws</a> ·
  <a href="CONTRIBUTING.md">Contribute</a>
</p>

## Get started

DPOLens runs on your own servers with Docker Compose, so your policies stay there.
[Get started](https://dpolens.com/docs/get-started) takes you from the first command to your
first question, and [Connect your AI assistant](https://dpolens.com/docs/connect) sets up Claude
Code, Codex, Cursor and GitHub Copilot in VS Code.

To try it first, add the community version to your AI assistant: public privacy law only, with
no sign-in and no token.

<p>
  <a href="https://cursor.com/install-mcp?name=dpolens&config=eyJ1cmwiOiJodHRwczovL21jcC5kcG9sZW5zLmNvbS8ifQ%3D%3D"><img alt="Install in Cursor" src="https://img.shields.io/badge/Cursor-Install-000000?logo=cursor&logoColor=white"></a>
  <a href="https://vscode.dev/redirect/mcp/install?name=dpolens&config=%7B%22type%22%3A%22http%22%2C%22url%22%3A%22https%3A%2F%2Fmcp.dpolens.com%2F%22%7D"><img alt="Install in Copilot in VS Code" src="https://img.shields.io/badge/Copilot_in_VS_Code-Install-0098FF?logo=githubcopilot&logoColor=white"></a>
  <a href="https://claude.ai/directory/dpolens"><img alt="Connect in Claude" src="https://img.shields.io/badge/Claude-Connect-D97757?logo=claude&logoColor=white"></a>
</p>

For Claude Code, Codex, ChatGPT and the others, [the community version's page](https://dpolens.com/community)
has the line to add.

## What's inside

- **An MCP server** with four tools to search and read the law and your policies, quoting each
  clause word for word with its key, its version and the date that version took effect.
  [The MCP server](https://dpolens.com/docs/mcp)
- **Laws as packs**, each from its official source: GDPR and the UAE PDPL today, and more as
  their packs are released. [Supported laws](https://dpolens.com/laws)
- **Your own policies**, from Word or Markdown files, read into clauses without an AI model and
  published as versions that never change. [Your own policies](https://dpolens.com/docs/policies)
- **Search by words and by meaning**, in English and Arabic, on the CPU, with no LLM and no API
  key.
- **A dashboard and two logs:** a governance log that is append-only and hash-chained, and every
  question asked, with personal data taken out. [The governance log](docs/governance-log.md)
- **An HTTP API**, the same one the dashboard and the MCP server use.
  [The HTTP API](https://dpolens.com/docs/api)

## Measured

- **Search:** on held-out questions, the clause the guidance points at is among the top five
  answers 77% of the time for GDPR, and 55% for the UAE's law.
  [How it was measured](evals/retrieval.md)
- **Use:** Claude Code with the plugin searched before writing code in 36 of 36 runs of tasks
  that touch personal data, and in 3 of 45 runs of tasks that do not.
  [How it was measured](evals/trigger-test.md)

## Contributing

Law packs are the contribution that matters most, and [CONTRIBUTING.md](CONTRIBUTING.md) says
what one needs. A security problem is reported privately, as [SECURITY.md](SECURITY.md) says.

## Licence

The code is Apache-2.0, with DCO sign-off and no CLA. `packs/` carries its own licence: the law
text keeps its source's, and the structure around it is CC-BY-4.0.
