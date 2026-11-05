import { tool } from "@opencode-ai/plugin"
import { existsSync, readFileSync } from "node:fs"
import { dirname, join } from "node:path"

const VAULT = process.env.SKILLS_VAULT ?? "/mnt/SkillsVault"

type Reference = {
  name: string
  title: string
  description: string
  path: string
  license: string
}

type Skill = {
  name: string
  group: string
  description: string
  path: string
  license: string
  aliases: string[]
  references: Reference[]
}

type SkillIndex = { skills: Record<string, Skill> }
type GroupDoc = {
  groups: Record<string, { description: string; skills: string[] }>
  agents: Record<string, string[]>
  unknown_agent_groups: string[]
}

let cache: { index: SkillIndex; groups: GroupDoc } | null = null

function load() {
  if (cache) return cache
  const index = JSON.parse(readFileSync(join(VAULT, "index", "skills.json"), "utf8")) as SkillIndex
  const groups = JSON.parse(readFileSync(join(VAULT, "index", "groups.json"), "utf8")) as GroupDoc
  cache = { index, groups }
  return cache
}

function allowedGroups(agent: string, doc: GroupDoc): Set<string> {
  const groups = doc.agents[agent] ?? doc.unknown_agent_groups ?? []
  return new Set(groups)
}

function visibleSkills(index: SkillIndex, doc: GroupDoc, agent: string): Skill[] {
  const allowed = allowedGroups(agent, doc)
  return Object.values(index.skills).filter((s) => allowed.has(s.group))
}

function score(skill: Skill, query: string): number {
  const q = query.toLowerCase().trim()
  const tokens = q.split(/[^a-z0-9]+/).filter(Boolean)
  const name = skill.name.toLowerCase()
  const desc = skill.description.toLowerCase()
  const aliases = skill.aliases.map((a) => a.toLowerCase())
  let value = 0
  if (name.includes(q)) value += 80
  for (const t of tokens) {
    if (t === name) value += 30
    else if (name.includes(t)) value += 20
    if (aliases.some((a) => a.includes(t))) value += 12
    if (desc.includes(t)) value += 6
    if (skill.references.some((r) => r.name.toLowerCase().includes(t) || r.description.toLowerCase().includes(t))) value += 2
  }
  return value
}

function groupLine(name: string, doc: GroupDoc): string {
  const meta = doc.groups[name]
  return `${name.padEnd(12)} ${String(meta.skills.length).padStart(3)}  ${meta.description}`
}

export default tool({
  description: "List, search, and load portable skills by group from the SkillsVault registry.",
  args: {
    action: tool.schema.enum(["groups", "list", "search", "load", "path"]),
    group: tool.schema.string().optional().describe("Group name for action=list"),
    query: tool.schema.string().optional().describe("Search text for action=search"),
    name: tool.schema.string().optional().describe("Skill name for action=load or action=path"),
    reference: tool.schema.string().optional().describe("Optional reference name or path for action=load"),
    limit: tool.schema.number().optional().describe("Maximum search results (default 12)"),
  },
  async execute(args, context) {
    const { index, groups } = load()
    const agent = (context as { agent?: string }).agent ?? "build"
    const allowed = allowedGroups(agent, groups)

    if (args.action === "groups") {
      const lines = Object.keys(groups.groups)
        .filter((g) => allowed.has(g))
        .sort()
        .map((g) => groupLine(g, groups))
      return [`Groups visible to ${agent}:`, "", ...lines].join("\n")
    }

    if (args.action === "list") {
      if (!args.group) return "Error: group is required for action=list"
      if (!allowed.has(args.group)) return `Error: group not allowed for agent ${agent}: ${args.group}`
      const names = groups.groups[args.group]?.skills ?? []
      const lines = names.sort().map((name) => {
        const s = index.skills[name]
        return `${s.name.padEnd(32)} ${s.description}  [${s.references.length} refs]`
      })
      return [`Group ${args.group} (${names.length} skills):`, "", ...lines].join("\n")
    }

    if (args.action === "search") {
      if (!args.query) return "Error: query is required for action=search"
      const limit = args.limit ?? 12
      const results = visibleSkills(index, groups, agent)
        .map((s) => ({ s, score: score(s, args.query as string) }))
        .filter((x) => x.score > 0)
        .sort((a, b) => b.score - a.score || a.s.name.localeCompare(b.s.name))
        .slice(0, limit)
      if (!results.length) return `No skills matched "${args.query}".`
      return results
        .map(({ s }) => `${s.name.padEnd(32)} ${s.description}  [${s.group}, ${s.references.length} refs]`)
        .join("\n")
    }

    if (args.action === "path") {
      if (!args.name) return "Error: name is required for action=path"
      const skill = index.skills[args.name]
      if (!skill) return `Error: unknown skill: ${args.name}`
      if (!allowed.has(skill.group)) return `Error: skill not allowed for agent ${agent}: ${args.name}`
      return join(VAULT, skill.path)
    }

    if (args.action === "load") {
      if (!args.name) return "Error: name is required for action=load"
      const skill = index.skills[args.name]
      if (!skill) return `Error: unknown skill: ${args.name}. Use action=search first.`
      if (!allowed.has(skill.group)) return `Error: skill not allowed for agent ${agent}: ${args.name}`
      const skillPath = join(VAULT, skill.path)
      if (!existsSync(skillPath)) return `Error: missing skill file: ${skillPath}`

      let path = skillPath
      let label = skill.name
      if (args.reference) {
        const refSlug = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")
        const wanted = refSlug(String(args.reference))
        const ref = skill.references.find(
          (r) =>
            r.name === args.reference ||
            r.path === args.reference ||
            r.path.endsWith(`/${args.reference}`) ||
            refSlug(r.name) === wanted ||
            refSlug(r.title) === wanted,
        )
        if (!ref) return `Error: unknown reference: ${args.reference}. Use action=load without reference to see the list.`
        path = join(dirname(skillPath), ref.path)
        label = `${skill.name}/${ref.name}`
      }
      if (!existsSync(path)) return `Error: missing skill file: ${path}`
      const content = readFileSync(path, "utf8")
      return [
        `<skill_content name="${label}">`,
        content.trim(),
        "",
        `Base directory: ${dirname(path)}`,
        "</skill_content>",
      ].join("\n")
    }

    return `Error: unknown action: ${args.action}`
  },
})
