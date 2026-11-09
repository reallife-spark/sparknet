import { tool, type Plugin } from "@opencode-ai/plugin"
import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs"
import { dirname, join, resolve } from "node:path"

const DATA_DIRS = [".understand-anything", ".ua"]
const GRAPH = "knowledge-graph.json"
const SKIP = new Set([".git", "node_modules", ".ua", ".understand-anything", ".venv", "__pycache__", "dist", "build", "target"])

type Graph = {
  version?: string
  project?: { name?: string; analyzedAt?: string; gitCommitHash?: string }
  nodes?: Array<{ id: string; type?: string; name?: string; summary?: string; filePath?: string; tags?: string[] }>
  edges?: Array<{ source: string; target: string; type: string }>
  layers?: unknown[]
  tour?: unknown[]
}

function dataDir(root: string): string {
  for (const name of DATA_DIRS) {
    const candidate = join(root, name)
    if (existsSync(candidate)) return candidate
  }
  return join(root, ".ua")
}

function loadGraph(root: string): Graph | null {
  const path = join(dataDir(root), GRAPH)
  if (!existsSync(path)) return null
  try {
    return JSON.parse(readFileSync(path, "utf8")) as Graph
  } catch {
    return null
  }
}

function sharedScript(root: string): string | null {
  let current = resolve(root)
  for (;;) {
    const candidate = join(current, "shared", "sparknet-understand.py")
    if (existsSync(candidate)) return candidate
    const parent = dirname(current)
    if (parent === current) return null
    current = parent
  }
}

function newestSource(root: string): { path: string; mtime: number } {
  let newest = { path: "", mtime: 0 }
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.name.startsWith(".") && entry.name !== ".env") continue
      if (SKIP.has(entry.name)) continue
      const full = join(dir, entry.name)
      if (entry.isDirectory()) {
        walk(full)
        continue
      }
      try {
        const stat = statSync(full)
        if (stat.mtimeMs > newest.mtime) newest = { path: full, mtime: stat.mtimeMs }
      } catch {
        // An unreadable file is not a reason to fail a staleness check.
      }
    }
  }
  walk(root)
  return newest
}

function matches(node: NonNullable<Graph["nodes"]>[number], terms: string[]): boolean {
  const haystack = [node.id, node.name, node.summary, node.filePath, ...(node.tags ?? [])].join(" ").toLowerCase()
  return terms.every((term) => haystack.includes(term))
}

function markStale(root: string): void {
  const dir = dataDir(root)
  mkdirSync(dir, { recursive: true })
  writeFileSync(join(dir, ".stale"), `${new Date().toISOString()}\n`, "utf8")
}

export const UnderstandPlugin: Plugin = async ({ $, directory, worktree }) => {
  const root = worktree || directory
  return {
    tool: {
      understand_query: tool({
        description: "Search the project's .ua/knowledge-graph.json by text.",
        args: {
          text: tool.schema.string().describe("search text; empty returns the most connected nodes"),
          limit: tool.schema.number().int().positive().max(100).optional().describe("maximum results (default 20)"),
        },
        execute: async (args, context) => {
          const graph = loadGraph(context.directory)
          if (!graph) return "No graph found. Run /understand first."
          const terms = args.text.toLowerCase().split(/\s+/).filter(Boolean)
          const limit = args.limit ?? 20
          const nodes = (graph.nodes ?? []).filter((node) => matches(node, terms)).slice(0, limit)
          return JSON.stringify({ project: graph.project, nodes }, null, 2)
        },
      }),
      understand_build: tool({
        description: "Build or rebuild the code-understanding graph with the shared Python core.",
        args: {
          full: tool.schema.boolean().optional().describe("also drop the incremental fingerprint cache"),
          exclude: tool.schema.string().optional().describe("comma-separated extra ignore patterns"),
        },
        execute: async (args, context) => {
          const script = sharedScript(context.directory)
          if (!script) return "Cannot find shared/sparknet-understand.py above this project."
          const out = join(dataDir(context.directory), GRAPH)
          if (args.full) {
            try {
              writeFileSync(join(dataDir(context.directory), "fingerprints.json"), "{}\n", "utf8")
            } catch {
              // The build still runs; a missing cache only means a full scan.
            }
          }
          const exclude = args.exclude ? ["--exclude", args.exclude] : []
          const result = await $`python3 ${script} build --root ${context.directory} --out ${out} ${exclude}`
            .cwd(context.directory)
            .quiet()
            .nothrow()
          if (result.exitCode !== 0) return `Build failed:\n${result.stderr.toString()}`
          const graph = loadGraph(context.directory)
          return JSON.stringify(
            {
              ok: true,
              graph: out,
              nodes: graph?.nodes?.length ?? 0,
              edges: graph?.edges?.length ?? 0,
              layers: graph?.layers?.length ?? 0,
              tour: graph?.tour?.length ?? 0,
            },
            null,
            2,
          )
        },
      }),
      understand_stale: tool({
        description: "Check whether the graph is older than the newest source file.",
        args: {},
        execute: async (_args, context) => {
          const dir = dataDir(context.directory)
          const graphPath = join(dir, GRAPH)
          if (!existsSync(graphPath)) return JSON.stringify({ stale: true, reason: "no graph" })
          const newest = newestSource(context.directory)
          const graphTime = statSync(graphPath).mtimeMs
          return JSON.stringify(
            {
              stale: newest.mtime > graphTime || existsSync(join(dir, ".stale")),
              graph: graphPath,
              graphMtime: new Date(graphTime).toISOString(),
              newestSource: newest.path,
              newestSourceMtime: newest.mtime ? new Date(newest.mtime).toISOString() : null,
            },
            null,
            2,
          )
        },
      }),
    },
    event: async ({ event }) => {
      if (event.type !== "file.edited") return
      const file = (event as { properties?: { file?: string } }).properties?.file
      if (!file || file.includes("/.ua/") || file.includes("/.understand-anything/")) return
      markStale(worktree || directory)
    },
    "tool.execute.after": async (input) => {
      if (input.tool === "edit" || input.tool === "write" || input.tool === "patch") {
        markStale(worktree || directory)
      }
    },
  }
}
