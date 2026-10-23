import { getZoteroAgentRuntimeRootDir } from "./skills/nativeSkillPaths";
import { joinLocalPath } from "../utils/localPath";
import { getIOUtils } from "../utils/geckoFs";
import { getNotesDirectoryConfig } from "../utils/notesDirectoryConfig";
import { sha256Bytes, sha256Text } from "./store/journalRecoveryBlobStore";
import { appLogger } from "../core/logging";
import type { AgentRuntimeRequest } from "./types";

const RESOURCES = [
  "learning_archive.py",
  "quick_review.py",
  "note-template.md",
  "requirements.txt",
  "references/writing.md",
  "references/narrative.md",
  "references/workflow.md",
];

export function getPaperLearningRoot(): string {
  return joinLocalPath(getZoteroAgentRuntimeRootDir(), "paper-learning");
}

async function writeText(path: string, text: string): Promise<void> {
  const io = getIOUtils();
  if (!io?.write || !io.makeDirectory)
    throw new Error("Local learning storage is unavailable");
  await io.makeDirectory(path.replace(/[\\/][^\\/]+$/, ""), {
    createAncestors: true,
    ignoreExisting: true,
  });
  await io.setPermissions?.(path.replace(/[\\/][^\\/]+$/, ""), 0o700);
  await io.write(path, new TextEncoder().encode(text), {
    tmpPath: `${path}.tmp`,
  });
  await io.setPermissions?.(path, 0o600);
}

export async function installPaperLearningResources(): Promise<void> {
  const io = getIOUtils();
  if (!io?.write || !io.exists) return;
  for (const file of RESOURCES) {
    const target = joinLocalPath(getPaperLearningRoot(), file);
    // The note template is user-editable. Helper code and reference instructions are managed resources.
    if (file === "note-template.md" && (await io.exists(target))) {
      const existing =
        io.read && new TextDecoder().decode(await io.read(target));
      if (existing !== "[object XMLHttpRequest]") continue;
    }
    const contents: unknown = await Zotero.File.getContentsAsync(
      `chrome://llmforzotero/content/paper-learning/${file}`,
    );
    // Chrome URLs return an XMLHttpRequest in Zotero; local file paths return text.
    const text =
      typeof contents === "string"
        ? contents
        : (contents as { responseText?: unknown })?.responseText;
    if (typeof text !== "string" || !text.trim())
      throw new Error(`Cannot read bundled paper learning resource: ${file}`);
    await writeText(target, text);
  }
}

export async function buildPaperLearningContext(): Promise<string> {
  if (!getIOUtils()?.exists) return "";
  try {
    const root = getPaperLearningRoot();
    if (
      !(await getIOUtils()?.exists?.(
        joinLocalPath(root, "learning_archive.py"),
      ))
    )
      return "";
    const config = getNotesDirectoryConfig();
    if (config)
      await writeText(
        joinLocalPath(root, "obsidian.json"),
        JSON.stringify({ vaultPath: config.directoryPath }),
      );
    const io = getIOUtils();
    const pythonCandidates = [
      joinLocalPath(root, ".venv", "bin", "python"),
      joinLocalPath(root, ".venv", "Scripts", "python.exe"),
    ];
    let python = "python3";
    for (const candidate of pythonCandidates) {
      if (await io?.exists?.(candidate)) {
        python = candidate;
        break;
      }
    }
    return [
      "Paper learning local resources (host-configured):",
      `- Working directory: ${root}`,
      `- Python interpreter: ${python}`,
      `- Template: ${joinLocalPath(root, "note-template.md")}`,
      "- Read references/workflow.md in that directory for the exact helper commands and input schema.",
      "- Use the selected model and its tools. Save and verify the quick-review snapshot before presenting the answer. Before archival, find and reuse this paper's saved review; add only missing work.",
      config
        ? "- Obsidian vault is configured in obsidian.json. Keep source PDFs, quiz jobs and raw discussions in the working directory."
        : "- For archival, ask the user to configure an Obsidian vault in Agent > Notes directory.",
    ].join("\n");
  } catch (error) {
    appLogger.warn("LLM: Cannot prepare paper learning resources", error);
    return "";
  }
}

/** Retain the complete delivered review even when the model omitted its publish call. */
export async function saveCompletedPaperReview(
  request: AgentRuntimeRequest,
  text: string,
): Promise<void> {
  const hasReviewSections = [1, 2, 3, 4].every((number) =>
    new RegExp(`^## ${number}\\. `, "m").test(text),
  );
  if (
    (!hasReviewSections &&
      !/paper-(?:quick-understanding|concepts)|快速理解/.test(
        `${request.userText} ${(request.forcedSkillIds || []).join(" ")}`,
      )) ||
    !/^## (?:1\.|序)/m.test(text) ||
    !/^## (?:[34]\.|故事|包装)/m.test(text)
  )
    return;
  const papers = request.turnPaperScope.papers;
  if (papers.length !== 1) return;
  try {
    const paper = papers[0].paper;
    const item = await Zotero.Items.getAsync(paper.itemId);
    if (!item?.key) return;
    const attachment = await Zotero.Items.getAsync(paper.contextItemId);
    const pdf = attachment?.isPDFAttachment()
      ? attachment
      : await item.getBestAttachment();
    const pdfPath = pdf && (await pdf.getFilePathAsync());
    const io = getIOUtils();
    if (!pdfPath || !io?.read) return;
    const paperKey = `${item.libraryID}:${item.key}`;
    const directory = joinLocalPath(
      getPaperLearningRoot(),
      "reviews",
      (await sha256Text(paperKey)).slice(0, 20),
    );
    const chatMarkdownPath = joinLocalPath(
      directory,
      `completed-chat-${Date.now()}.md`,
    );
    await writeText(chatMarkdownPath, text);
    await writeText(
      joinLocalPath(directory, "completed-chat.json"),
      JSON.stringify({
        paperKey,
        pdfSha256: await sha256Bytes(new Uint8Array(await io.read(pdfPath))),
        chatMarkdownPath,
        chatSha256: await sha256Text(text),
        createdAt: new Date().toISOString(),
      }),
    );
  } catch (error) {
    appLogger.warn("LLM: Cannot save the completed paper review", error);
  }
}
