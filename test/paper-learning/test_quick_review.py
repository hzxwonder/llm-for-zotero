import sys
sys.dont_write_bytecode = True
import unittest, tempfile, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'addon/content/paper-learning'))
import quick_review as q
class QuickReviewTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  old=q.BASE;q.BASE=self.root;self.addCleanup(lambda:setattr(q,'BASE',old))
  (self.root/'a.pdf').write_bytes(b'%PDF-test-a');(self.root/'b.pdf').write_bytes(b'%PDF-test-b')
  self.note='## 0. 摘要译文\n\n> [!quote]- 摘要\n> 摘要正文\n\n## 1. 序：为什么值得读\n\n开场。\n\n## 2. 快速理解论文\n\n机制。\n\n## 3. 故事类比：仓库\n\n1. 自检问题？\n\n> [!check]- 展开核对要点\n> 私有答案。\n\n## 4. 包装技巧\n\n| 段落 | 小白认知对比 |\n| --- | --- |\n| P1 | 直觉→认识 |\n\n**整条论证链：** P1→P2\n\n> [!example]- 展开Introduction\n> 六项详解。\n\n### 可以迁移到我写作中的技巧\n\n写作迁移内容。\n'
  (self.root/'note.md').write_text(self.note);(self.root/'figure.png').write_bytes(b'picture')
  self.data={'paperKey':'1:KEY','pdfPath':str(self.root/'a.pdf'),'noteMarkdownPath':str(self.root/'note.md'),'assets':[str(self.root/'figure.png')],'pending':[]}
 def test_chat_only_and_note_unchanged(self):
  r=q.publish(self.data);chat=Path(r['chatMarkdownPath']).read_text()
  for secret in ['摘要正文','私有答案','六项详解','写作迁移内容','[!'] :self.assertNotIn(secret,chat)
  for visible in ['开场','机制','自检问题','小白认知对比','P1→P2']:self.assertIn(visible,chat)
  self.assertEqual(Path(r['noteMarkdownPath']).read_text(),self.note)
 def test_reuse_is_read_only(self):
  q.publish(self.data);before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
  self.assertTrue(q.find(self.data)['found']);self.assertEqual(before,{p:p.read_bytes() for p in before})
 def test_paper_identity_isolated(self):
  q.publish(self.data);self.assertFalse(q.find(dict(self.data,paperKey='1:OTHER'))['found'])
 def test_changed_pdf_invalidates(self):
  q.publish(self.data);self.assertFalse(q.find(dict(self.data,pdfPath=str(self.root/'b.pdf')))['found'])
 def test_changed_or_missing_assets_invalidates(self):
  r=q.publish(self.data);p=Path(r['assets'][0]);p.write_bytes(b'changed');self.assertFalse(q.find(self.data)['found']);p.unlink();self.assertFalse(q.find(self.data)['found'])
 def test_changed_note_or_chat_invalidates(self):
  r=q.publish(self.data);Path(r['chatMarkdownPath']).write_text('changed');self.assertFalse(q.find(self.data)['found'])
  r=q.publish(self.data);Path(r['noteMarkdownPath']).write_text(self.note+'change');self.assertFalse(q.find(self.data)['found'])
 def test_work_directory_cleanup_keeps_snapshot(self):
  r=q.publish(self.data);(self.root/'note.md').unlink();(self.root/'figure.png').unlink()
  self.assertTrue(q.find(self.data)['found']);self.assertTrue(Path(r['noteMarkdownPath']).is_file())
 def test_host_answer_fallback_reuses_complete_chat(self):
  chat=self.root/'delivered.md';chat.write_text('已交付的完整讲解')
  path=q.cache_path(self.data);q.save(path.parent/'completed-chat.json',{'paperKey':self.data['paperKey'],'pdfSha256':q.digest((self.root/'a.pdf').read_bytes()),'chatMarkdownPath':str(chat),'chatSha256':q.digest(chat.read_bytes()),'createdAt':'2999-01-01'})
  result=q.find(self.data);self.assertTrue(result['found']);self.assertTrue(result['chatOnly'])
  self.assertEqual(Path(result['chatMarkdownPath']).read_text(),'已交付的完整讲解')
 def test_matching_host_copy_keeps_full_snapshot(self):
  result=q.publish(self.data);path=q.cache_path(self.data);manifest=q.read(path)
  q.save(path.parent/'completed-chat.json',{'paperKey':self.data['paperKey'],'pdfSha256':manifest['pdf']['sha256'],'chatMarkdownPath':result['chatMarkdownPath'],'chatSha256':manifest['chat']['sha256'],'createdAt':'2999-01-01'})
  result=q.find(self.data);self.assertTrue(result['found']);self.assertNotIn('chatOnly',result);self.assertEqual(len(result['assets']),1)
 def test_reject_missing_or_extra_sections(self):
  for text in [self.note.replace('## 0.','## 9.'),self.note+'\n## 5. 个人\n',self.note.replace('## 2. 快速理解论文','## 1. 重复\n\n## 2. 快速理解论文')]:
   with self.assertRaises(ValueError):q.project(text)
 def test_reject_html_chat(self):
  with self.assertRaises(ValueError):q.project(self.note.replace('机制。','<details>机制</details>'))
 def test_pending_retained(self):
  self.assertEqual(q.publish(dict(self.data,pending=['补读摘要']))['pending'],['补读摘要'])
if __name__=='__main__':unittest.main()
