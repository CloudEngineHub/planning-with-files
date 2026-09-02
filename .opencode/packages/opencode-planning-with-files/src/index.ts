/**
 * OpenCode plugin entry for planning-with-files.
 *
 * Only the plugin function is exported from this module: OpenCode treats every
 * exported function of a plugin module as a plugin, so the helpers live in
 * ./core.js. Hooks (all fail open: a planning error never breaks a turn):
 *
 * - chat.message: append the framed active plan to the outgoing user message
 *   (or a once-per-turn ambiguity notice), plus the queued write reminder
 * - tool.execute.after: append the progress reminder to write-like tool output
 * - experimental.session.compacting: keep the plan pointer and attestation in
 *   the compaction summary
 * - event session.idle: the completion gate in gated mode, re-prompting the
 *   session with the gate reason (Tier 2: follow-up inject)
 * - tools pwf_init, pwf_status, pwf_check for the model
 */
import { tool, type Plugin } from "@opencode-ai/plugin"
import * as crypto from "node:crypto"
import {
  ambiguityNotice,
  buildContext,
  checkComplete,
  compactionNote,
  effectiveProjectRoot,
  evaluateGate,
  initPlan,
  planRootIsPinned,
  resolvePlan,
  summarizeStatus,
  REMINDER,
  VERSION,
  WRITE_LIKE_TOOLS,
} from "./core.js"

type Located = { root: string | null; planDir: string | null; conflicts: string[] }

export const PlanningWithFiles: Plugin = async ({ client, directory }) => {
  const env = process.env
  const sessionDirs = new Map<string, string>()
  const sessionIsChild = new Map<string, boolean>()
  const gateInFlight = new Set<string>()

  async function sessionRoot(sessionID: string): Promise<string> {
    if (!sessionDirs.has(sessionID)) {
      let dir = directory
      let child = false
      try {
        const result = await client.session.get({ path: { id: sessionID } })
        const session = (result as { data?: { directory?: string; parentID?: string } }).data
        if (session?.directory) dir = session.directory
        child = Boolean(session?.parentID)
      } catch {
        // offline or unknown session: fall back to the server directory
      }
      sessionDirs.set(sessionID, dir)
      sessionIsChild.set(sessionID, child)
    }
    return sessionDirs.get(sessionID) ?? directory
  }

  function locate(project: string): Located {
    if (env.PLANNING_DISABLED === "1") return { root: null, planDir: null, conflicts: [] }
    const root = effectiveProjectRoot(project, env)
    if (!root) return { root: null, planDir: null, conflicts: [] }
    const resolved = resolvePlan(root, { explicit: planRootIsPinned(env) }, env)
    return { root, planDir: resolved.planDir, conflicts: resolved.conflicts }
  }

  return {
    "chat.message": async (input, output) => {
      try {
        gateInFlight.delete(input.sessionID)
        const located = locate(await sessionRoot(input.sessionID))
        if (!located.root) return
        let text: string | null = null
        if (located.planDir) text = buildContext(located.root, located.planDir)
        else if (located.conflicts.length) text = ambiguityNotice(located.conflicts)
        if (!text) return
        output.parts.push({
          id: `prt_pwf_${crypto.randomUUID().replace(/-/g, "")}`,
          sessionID: input.sessionID,
          messageID: output.message.id,
          type: "text",
          text,
          synthetic: true,
        } as (typeof output.parts)[number])
      } catch {
        // never break the turn
      }
    },

    "tool.execute.after": async (input, output) => {
      try {
        if (!WRITE_LIKE_TOOLS.has(input.tool)) return
        const located = locate(await sessionRoot(input.sessionID))
        if (!located.planDir) return
        output.output = `${output.output ?? ""}\n\n${REMINDER}`
      } catch {
        // never break the turn
      }
    },

    "experimental.session.compacting": async (input, output) => {
      try {
        const located = locate(await sessionRoot(input.sessionID))
        if (!located.planDir || !located.root) return
        output.context.push(compactionNote(located.root, located.planDir))
      } catch {
        // never break compaction
      }
    },

    event: async ({ event }) => {
      if (event.type !== "session.idle") return
      const sessionID = (event.properties as { sessionID?: string }).sessionID
      if (!sessionID || gateInFlight.has(sessionID)) return
      try {
        await sessionRoot(sessionID)
        if (sessionIsChild.get(sessionID)) return
        const located = locate(sessionDirs.get(sessionID) ?? directory)
        if (!located.planDir) return
        const reason = evaluateGate(located.planDir, env)
        if (!reason) return
        gateInFlight.add(sessionID)
        await client.session.promptAsync({
          path: { id: sessionID },
          body: { parts: [{ type: "text", text: reason }] },
        })
      } catch {
        gateInFlight.delete(sessionID)
      }
    },

    tool: {
      pwf_init: tool({
        description:
          "planning-with-files: create task_plan.md, findings.md and progress.md. A name creates an isolated .planning/YYYY-MM-DD-<slug>/ plan and makes it active; mode autonomous or gated writes the v3 markers and attests the plan.",
        args: {
          name: tool.schema.string().optional().describe("Optional plan name (creates .planning/<date>-<slug>/)"),
          mode: tool.schema.string().optional().describe("Optional v3 mode: autonomous or gated"),
          template: tool.schema.string().optional().describe("default or analytics"),
        },
        async execute(args, context) {
          return JSON.stringify(initPlan(context.directory, args, env))
        },
      }),
      pwf_status: tool({
        description: "planning-with-files: summarize the active plan (id, mode, attestation, current phase, phase counts).",
        args: {},
        async execute(_args, context) {
          return JSON.stringify(summarizeStatus(context.directory, env))
        },
      }),
      pwf_check: tool({
        description: "planning-with-files: report whether every phase of the active plan is complete.",
        args: {},
        async execute(_args, context) {
          return JSON.stringify({ plugin: VERSION, ...checkComplete(context.directory, env) })
        },
      }),
    },
  }
}
