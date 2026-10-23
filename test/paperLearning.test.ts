import { assert } from "chai";
import {
  readFile,
  writeFile,
  mkdir,
  mkdtemp,
  rm,
  access,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  getPaperLearningRoot,
  installPaperLearningResources,
  buildPaperLearningContext,
  saveCompletedPaperReview,
} from "../src/agent/paperLearning";
import type { AgentRuntimeRequest } from "../src/agent/types";

describe("portable paper learning", function () {
  let directory: string;
  let oldZotero: unknown;
  let oldIO: unknown;
  const g = globalThis as any;
  beforeEach(async function () {
    directory = await mkdtemp(join(tmpdir(), "paper-learning-"));
    oldZotero = g.Zotero;
    oldIO = g.IOUtils;
    const pdfPath = join(directory, "paper.pdf");
    await writeFile(pdfPath, "%PDF-synthetic");
    const item = {
      key: "PAPER",
      libraryID: 1,
      getBestAttachment: async () => attachment,
    };
    const attachment = {
      isPDFAttachment: () => true,
      getFilePathAsync: async () => pdfPath,
    };
    g.Zotero = {
      DataDirectory: { dir: directory },
      Profile: { dir: "profile" },
      Prefs: { get: () => "" },
      File: {
        getContentsAsync: async (url: string) =>
          readFile(
            join(
              process.cwd(),
              "addon/content/paper-learning",
              url.split("/paper-learning/")[1],
            ),
            "utf8",
          ),
      },
      Items: { getAsync: async (id: number) => (id === 1 ? item : attachment) },
    };
    g.IOUtils = {
      exists: async (p: string) => {
        try {
          await access(p);
          return true;
        } catch {
          return false;
        }
      },
      read: async (p: string) => new Uint8Array(await readFile(p)),
      write: async (p: string, data: Uint8Array) => writeFile(p, data),
      makeDirectory: async (p: string) => {
        await mkdir(p, { recursive: true });
      },
    };
  });
  afterEach(async function () {
    g.Zotero = oldZotero;
    g.IOUtils = oldIO;
    await rm(directory, { recursive: true, force: true });
  });
  const request = () =>
    ({
      userText: "$paper-quick-understanding 快速理解",
      turnPaperScope: { papers: [{ paper: { itemId: 1, contextItemId: 2 } }] },
    }) as AgentRuntimeRequest;
  it("installs complete resources and preserves the edited template", async function () {
    await installPaperLearningResources();
    const template = join(getPaperLearningRoot(), "note-template.md");
    await writeFile(template, "My edited template");
    await installPaperLearningResources();
    assert.equal(await readFile(template, "utf8"), "My edited template");
    assert.include(await buildPaperLearningContext(), getPaperLearningRoot());
    for (const file of [
      "learning_archive.py",
      "quick_review.py",
      "references/workflow.md",
      "requirements.txt",
    ])
      await access(join(getPaperLearningRoot(), file));
  });
  it("saves a complete review under the paper identity across conversations", async function () {
    const text =
      "## 1. 序\n开场\n## 2. 快速理解论文\n机制\n## 3. 故事类比\n故事\n## 4. 包装技巧\n论证";
    await saveCompletedPaperReview(request(), text);
    const { sha256Text } =
      await import("../src/agent/store/journalRecoveryBlobStore");
    const path = join(
      getPaperLearningRoot(),
      "reviews",
      (await sha256Text("1:PAPER")).slice(0, 20),
      "completed-chat.json",
    );
    const result = JSON.parse(await readFile(path, "utf8"));
    assert.equal(result.paperKey, "1:PAPER");
    assert.match(result.pdfSha256, /^[a-f0-9]{64}$/);
    assert.equal(await readFile(result.chatMarkdownPath, "utf8"), text);
    assert.equal(result.chatSha256, await sha256Text(text));
  });
  it("saves the completed review when an interrupted task is continued", async function () {
    const req = request();
    req.userText = "继续";
    const text =
      "## 1. 序\n开场\n## 2. 快速理解论文\n机制\n## 3. 故事类比\n故事\n## 4. 包装技巧\n论证";
    await saveCompletedPaperReview(req, text);
    const { sha256Text } =
      await import("../src/agent/store/journalRecoveryBlobStore");
    assert.isTrue(
      await g.IOUtils.exists(
        join(
          getPaperLearningRoot(),
          "reviews",
          (await sha256Text("1:PAPER")).slice(0, 20),
          "completed-chat.json",
        ),
      ),
    );
  });
  it("does not save arbitrary replies or ambiguous paper sets", async function () {
    await saveCompletedPaperReview(request(), "普通回复");
    assert.isFalse(await g.IOUtils.exists(getPaperLearningRoot()));
    const req = request();
    req.turnPaperScope.papers = [];
    await saveCompletedPaperReview(req, "## 1. 序\n## 3. 故事");
    assert.isFalse(await g.IOUtils.exists(getPaperLearningRoot()));
  });
});
