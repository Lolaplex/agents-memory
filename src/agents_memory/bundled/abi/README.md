# Agent memory ABI



**Version:** see [`VERSION`](VERSION)



Local markdown memory for coding agents — **any provider, any IDE, any MCP host**. Your Agent, or a plain script: if it can read folders and optional MCP, it can use this layout.



Markdown on disk is the **source of truth**. Tools sit above it; they must not become a second store.



## What ships here



| Doc | Contract |

|-----|----------|

| [`LAYOUT.md`](LAYOUT.md) | Folder taxonomy (user + project trees) |

| [`KINDS.md`](KINDS.md) | Where facts go; mutability rules |

| [`INJECTION.md`](INJECTION.md) | AGENTS.md / CLAUDE.md binding |

| [`PLATFORM.md`](PLATFORM.md) | Windows vs Unix, symlinks, per-machine paths |

| [`INSTALL.md`](INSTALL.md) | Sync, injection, scan.json, `--help-json` |

| [`WHY.md`](WHY.md) | Why this exists (vs RAG, vaults, vendor graves) |

| [`MCP.md`](MCP.md) | Tool names and behavior |
| [`INGEST.md`](INGEST.md) | Chat/brain catalog → extract → distill pipeline |



Installed copies: `ensure_memory_layout()` writes `abi/LAYOUT.md` → `~/.agents/memory/LAYOUT.md` (copied, not codegen).



## Generated vs shipped



| Kind | Examples |

|------|----------|

| **Shipped in repo** | `abi/*.md`, `skills/memory-sync/SKILL.md` template |

| **Copied on sync** | `~/.agents/memory/LAYOUT.md` ← `abi/LAYOUT.md` |

| **Generated on sync** | `~/.agents/AGENTS.md`, host always-on rules, per-repo `.agents` inject, skills |

| **Merged on `--init`** | Host MCP config, Zed `context_servers` |

| **CLI spec** | `python -m agents_memory --help-json` (from argparse) |



Inventory scan **skips** `.agents` and `.cursor` directories. Register creates **files only** under `<repo>/.agents/memory/` — no empty folder tree. No `.cursor/` in registered repos.



No roff man page. Agents: use `--help-json`, not README scraping. Details: [`INSTALL.md`](INSTALL.md).



## Reference implementation



This repository's **Python package** (`src/agents_memory/`: MCP server, `store`, `sync`, `inventory`, `ingest`) is the reference implementation of this ABI.

Future work on that package (not ABI changes): [`../ROADMAP.md`](../ROADMAP.md).



Implementations in other languages should treat `abi/` as normative. Bump [`VERSION`](VERSION) on breaking path or tool contract changes; additive folders/kinds are minor bumps.



## Quick mental model



```

~/.agents/memory/          ← identity, project map, cross-cutting notes

<repo>/.agents/memory/     ← that repo's staging, research, plans, decisions (files on write)

~/.agents/AGENTS.md        ← short always-on inject (generated)

MCP (optional)             ← search / add / register / sync

```



## Conformance (informal)



1. No dump files (`facts.md`, monolithic `MEMORY.md`).

2. One home per fact; path encodes kind.

3. Project `staging/` is inbox only — distill, then delete.

4. No empty placeholder folders.

5. Search unions user store and registered project trees.

6. If MCP is provided, tool names and semantics match [`MCP.md`](MCP.md).



## GitHub blurb



```

Local markdown memory for coding agents — any provider, any IDE. Versioned ABI in abi/; Python MCP is the reference implementation. Your folders, your truth.

```


