import type { Plugin, PluginInput } from "@opencode-ai/plugin";

const NOTIFIER_TITLE = "sparknet";

/**
 * Devices to notify. When SPARKNET_KDE_DEVICES is set it is a comma-separated
 * list of device ids (or names accepted by `kdeconnect-cli -d`). Otherwise the
 * plugin discovers reachable devices dynamically.
 */
function configuredDevices(): string[] {
  const raw = process.env.SPARKNET_KDE_DEVICES;
  if (!raw) return [];
  return raw
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
}

async function reachableDevices($: PluginInput["$"]): Promise<string[]> {
  const configured = configuredDevices();
  if (configured.length > 0) return configured;

  const result = await $`kdeconnect-cli -a --id-only`.quiet().nothrow();
  if (result.exitCode !== 0) return [];
  return result
    .text()
    .trim()
    .split("\n")
    .map((id) => id.trim())
    .filter(Boolean);
}

async function notify($: PluginInput["$"], body: string): Promise<void> {
  try {
    const ids = await reachableDevices($);
    if (ids.length === 0) return;

    await Promise.all(
      ids.map((id) =>
        $`kdeconnect-cli -d ${id} --ping-msg "${NOTIFIER_TITLE}: ${body}"`
          .quiet()
          .nothrow()
      )
    );
  } catch {
    // Notification failures must never block a session.
  }
}

export const KdeNotify: Plugin = async ({ $ }) => ({
  "tool.execute.before": async (input) => {
    if (input.tool === "question") {
      await notify($, "The agent has a question");
    }
  },
  "permission.ask": async (_input, output) => {
    if (output.status === "ask") {
      await notify($, "Permission requested");
    }
  },
  event: async ({ event }) => {
    if (event.type === "session.idle") {
      await notify($, "Session complete");
    }
  },
});

export default KdeNotify;