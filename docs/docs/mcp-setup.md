# MCP Setup Guide for sf-org-analyzer

## Overview

This project uses the **Salesforce DX MCP server** to run live SOQL queries against your org. MCP (Model Context Protocol) is needed only for the `/runtime` command and Phase 5 of `/analyze`. The core metadata scan (Phases 1–4) works entirely locally via grep — no MCP required.

---

## What MCP is used for

| Command | Uses MCP? | Why |
|---|---|---|
| `/analyze` | Partially (Phase 5 only) | Record counts, report last-run dates, scheduled job status |
| `/retrieve` | No | Uses Salesforce CLI (`sf`) directly via shell |
| `/runtime` | Yes — required | All queries are live SOQL via MCP |

MCP tool used: `mcp__salesforce-dx__run_soql_query`

---

## Step 1 — Install the Salesforce DX MCP server

The MCP server is provided by Salesforce as part of the `@salesforce/mcp` package.

```bash
npm install -g @salesforce/mcp
```

Verify:

```bash
npx @salesforce/mcp --version
```

---

## Step 2 — Configure MCP in Claude Code

Add the server to your Claude Code MCP configuration file.

### Config file location

| Platform | Path |
|---|---|
| macOS / Linux | `~/.claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

### Minimal configuration (all tools)

```json
{
  "mcpServers": {
    "salesforce-dx": {
      "command": "npx",
      "args": ["@salesforce/mcp", "--tools=all"],
      "env": {}
    }
  }
}
```

### Restricted configuration (tools used by this project only)

```json
{
  "mcpServers": {
    "salesforce-dx": {
      "command": "npx",
      "args": [
        "@salesforce/mcp",
        "--tools=run_soql_query,get_username,list_all_orgs"
      ],
      "env": {}
    }
  }
}
```

---

## Step 3 — Authenticate your Salesforce org

MCP uses the same authenticated session as the Salesforce CLI. Authenticate before starting Claude Code.

### Sandbox

```bash
sf org login web \
  --alias MyOrg \
  --instance-url https://your-org.sandbox.my.salesforce.com
```

### Production

```bash
sf org login web --alias MyOrg
```

### Verify authentication

```bash
sf org list
sf org display --target-org MyOrg
```

You should see your org listed with `Status: Connected`.

---

## Step 4 — Set the default org

So MCP knows which org to query without requiring an explicit alias in every call:

```bash
sf config set target-org MyOrg
```

Verify:

```bash
sf config get target-org
```

---

## Step 5 — Update CLAUDE.md

Edit `CLAUDE.md` in the project root and update the org config section at the top:

```
Alias:    MyOrg
Type:     Sandbox
Instance: https://your-org.sandbox.my.salesforce.com
CPQ:      installed
```

---

## Step 6 — Verify the setup

Launch Claude Code in the project directory:

```bash
cd sf-org-analyzer
claude
```

Then run a quick runtime check:

```
/runtime Are any CPQ Price Rules configured
```

Expected: Claude runs `SELECT COUNT() FROM SBQQ__PriceRule__c` via MCP and returns a result.

If you see a tool permission error, verify:

- The MCP server name in `claude_desktop_config.json` is exactly `salesforce-dx`
- The org is authenticated: `sf org list`
- Claude Code was restarted after editing the config file

---

## Troubleshooting

### "MCP server not found" or tool not available

Restart Claude Code after any config change. MCP servers are loaded at startup.

Check the config is valid JSON:

```bash
cat ~/.claude/claude_desktop_config.json | python3 -m json.tool
```

### "INVALID_SESSION_ID" or authentication error

Re-authenticate and verify the session:

```bash
sf org login web --alias MyOrg
sf org display --target-org MyOrg
```

### "Entity type cannot be queried: SBQQ__PriceRule__c"

CPQ is not installed in this org. Update `CLAUDE.md`: set `CPQ: not installed`. Claude will skip CPQ queries automatically.

### Slow SOQL responses

This is normal for large orgs. The `/runtime` command is intentionally minimal — it only queries what grep cannot answer. Most analysis is local and runs in milliseconds.

---

## MCP is optional for metadata-only analysis

If you only need to analyze metadata structure (fields, automations, flows, formulas) and do not need live runtime data, MCP is not required. `/analyze` will complete Phases 1–4 using local grep on retrieved XML, and will skip Phase 5 SOQL gracefully if MCP is unavailable.

To retrieve metadata without MCP:

```bash
bash scripts/retrieve.sh MyOrg
```

This uses the Salesforce CLI directly, not MCP.

---

## Setup checklist

- [ ] `npm install -g @salesforce/mcp`
- [ ] MCP server added to `~/.claude/claude_desktop_config.json`
- [ ] Org authenticated: `sf org login web --alias MyOrg`
- [ ] Default org set: `sf config set target-org MyOrg`
- [ ] `CLAUDE.md` updated with correct alias and instance URL
- [ ] Claude Code restarted
- [ ] Verified with: `/runtime Are any CPQ Price Rules configured`
