# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

This is a new, empty project. No source code exists yet.

## MCP Servers

Three MCP servers are configured in `.claude/settings.local.json`:

- **ruflo** — memory, hooks, swarm routing
- **ruv-swarm** — agent orchestration, DAA (Dynamic Adaptive Agents), neural patterns
- **flow-nexus** — sandboxes, workflows, neural training, app marketplace

Use `ToolSearch("keyword")` to discover available tools from these servers before invoking them.
