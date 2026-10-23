import { assert } from "chai";
import { ensureConversationKeyLedgerEntry } from "../../src/shared/conversationKeyLedger";
import { resolveLiveAgentCredentials } from "../agent/liveAgentCredentials";
import {
  getPaperLearningRoot,
  installPaperLearningResources,
} from "../../src/agent/paperLearning";
import { sha256Text } from "../../src/agent/store/journalRecoveryBlobStore";
import { joinLocalPath } from "../../src/utils/localPath";

declare const Zotero: any;
declare const Services: any;
declare const IOUtils: any;

// Opt-in live provider test. The paper and its PDF are synthetic and removed afterwards.
describe("paper learning with the configured live provider", function () {
  this.timeout(240000);
  it("persists a delivered quick review in the Zotero profile", async function () {
    const credentials = await resolveLiveAgentCredentials();
    assert.isOk(credentials, "Configure live provider credentials");
    const prefix = "extensions.zotero.llmforzotero";
    const saved = new Map<string, unknown>();
    const changes = {
      enableAgentMode: true,
      agentExecutionEngine: "deepseek_harness",
      originalAgentPermissionMode: "safe",
      deepseekHarnessNodePath: Services.env.get("LLM_FOR_ZOTERO_HARNESS_NODE"),
      deepseekHarnessWorkerPath: Services.env.get(
        "LLM_FOR_ZOTERO_HARNESS_WORKER",
      ),
    };
    const item = new Zotero.Item("journalArticle");
    item.setField("title", "Synthetic paper learning verification");
    await item.saveTx();
    const pdfPath = joinLocalPath(
      Zotero.getTempDirectory().path,
      `paper-learning-${Date.now()}.pdf`,
    );
    let attachment: any;
    let reviewDirectory: string | undefined;
    try {
      for (const [key, value] of Object.entries(changes)) {
        saved.set(key, Zotero.Prefs.get(`${prefix}.${key}`, true));
        Zotero.Prefs.set(`${prefix}.${key}`, value, true);
      }
      await Zotero.File.putContentsAsync(
        pdfPath,
        "%PDF-1.4\n% synthetic hash-only fixture\n%%EOF",
      );
      attachment = await Zotero.Attachments.importFromFile({
        file: pdfPath,
        parentItemID: item.id,
      });
      await installPaperLearningResources();
      for (const file of [
        "quick_review.py",
        "learning_archive.py",
        "note-template.md",
        "references/workflow.md",
      ]) {
        const resourcePath = joinLocalPath(getPaperLearningRoot(), file);
        assert.isTrue(await IOUtils.exists(resourcePath));
        const resource = await Zotero.File.getContentsAsync(resourcePath);
        assert.isAbove(resource.length, 100);
        assert.notInclude(resource, "[object XMLHttpRequest]");
        if (file.endsWith(".py")) assert.match(resource, /^#!.*python3\n/);
      }
      const conversationKey = 2_600_100_000 + (Date.now() % 100000);
      await ensureConversationKeyLedgerEntry({
        conversationKey,
        instanceID: "paper-learning-live",
        conversationID: "paper-learning-live",
        system: "upstream",
        kind: "paper",
        profileSignature: "paper-learning-live",
        libraryID: item.libraryID,
        paperItemID: item.id,
        issuedAt: Date.now(),
      });
      const result = await Zotero.LLMForZotero.api.agent.runTurn(
        {
          ...credentials,
          conversationKey,
          mode: "agent",
          conversationKind: "paper",
          libraryID: item.libraryID,
          activeItemId: item.id,
          activePaperContext: {
            libraryID: item.libraryID,
            itemId: item.id,
            contextItemId: attachment.id,
            title: item.getField("title"),
          },
          userText:
            "快速理解：这是自动验收用的虚构论文。唯一证据：把任务分成两批可以减少队列等待；测试仅涉及保存正文。不要读取 PDF、不要调用工具、不要加载技能。请直接用中文输出四个 H2：## 1. 序；## 2. 快速理解论文；## 3. 故事类比；## 4. 包装技巧。每节一句话，说明这是假设示例。不要写任何文件，宿主负责保存。",
        },
        () => {},
      );
      assert.equal(result.kind, "completed");
      reviewDirectory = joinLocalPath(
        getPaperLearningRoot(),
        "reviews",
        (await sha256Text(`${item.libraryID}:${item.key}`)).slice(0, 20),
      );
      const manifest = JSON.parse(
        await Zotero.File.getContentsAsync(
          joinLocalPath(reviewDirectory, "completed-chat.json"),
        ),
      );
      const answer = await Zotero.File.getContentsAsync(
        manifest.chatMarkdownPath,
      );
      assert.equal(answer, result.text);
      assert.equal(manifest.chatSha256, await sha256Text(answer));
      assert.match(manifest.pdfSha256, /^[a-f0-9]{64}$/);
      const report = Services.env.get("LLM_FOR_ZOTERO_PAPER_LEARNING_REPORT");
      if (report)
        await Zotero.File.putContentsAsync(
          report,
          JSON.stringify(
            {
              model: credentials!.model,
              resourceInstall: true,
              hostSavedCompleteAnswer: true,
              pdfIdentityVerified: true,
            },
            null,
            2,
          ),
        );
    } finally {
      for (const [key, value] of saved) {
        if (value === undefined) Zotero.Prefs.clear(`${prefix}.${key}`, true);
        else Zotero.Prefs.set(`${prefix}.${key}`, value, true);
      }
      await Zotero.Items.erase([
        ...(attachment ? [attachment.id] : []),
        item.id,
      ]);
      await IOUtils.remove(pdfPath, { ignoreAbsent: true });
      if (reviewDirectory)
        await IOUtils.remove(reviewDirectory, {
          recursive: true,
          ignoreAbsent: true,
        });
    }
  });
});
