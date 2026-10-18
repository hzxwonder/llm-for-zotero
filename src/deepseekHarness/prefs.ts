import { config } from "../../package.json";

export function getHarnessPreference(name: string): string {
  const value = globalThis.Zotero?.Prefs?.get?.(
    `${config.prefsPrefix}.${name}`,
    true,
  );
  return typeof value === "string" ? value.trim() : "";
}

export function isDeepSeekHarnessEnabled(): boolean {
  return getHarnessPreference("agentExecutionEngine") === "deepseek_harness";
}
