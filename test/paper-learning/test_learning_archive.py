import sys
sys.dont_write_bytecode = True
import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('archive', Path(__file__).resolve().parents[2] / 'addon/content/paper-learning/learning_archive.py')
a = importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
def synthetic_pdf():
    objects = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>']
    for _ in range(2):
        objects.append('<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>')
    objects.extend(['<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>', '<< /Length 48 >>\nstream\nBT /F1 12 Tf 30 750 Td (Synthetic evidence) Tj ET\nendstream'])
    data = b'%PDF-1.4\n'; offsets=[0]
    for i, value in enumerate(objects, 1):
        offsets.append(len(data));data += (str(i)+' 0 obj\n'+value+'\nendobj\n').encode()
    start=len(data);data += ('xref\n0 7\n0000000000 65535 f \n'+''.join(f'{n:010d} 00000 n \n' for n in offsets[1:])+'trailer\n<< /Size 7 /Root 1 0 R >>\nstartxref\n'+str(start)+'\n%%EOF').encode()
    return data

class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        old = (a.BASE, a.CONFIG);self.addCleanup(lambda: self.restore(old))
        a.BASE = self.root;a.CONFIG = self.root / 'obsidian.json'
        self.vault = self.root / 'vault';(self.vault / '.obsidian').mkdir(parents=True)
        a.save(a.CONFIG, {'vaultPath': str(self.vault)})
        (self.root / 'paper.pdf').write_bytes(synthetic_pdf())
        (self.root / 'figure.png').write_bytes(__import__('base64').b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII='))
        (self.root / 'paper.md').write_text(self.body('用批处理减少排队等待。', '![实验结果](<' + str(self.root / 'figure.png') + '>)\n\n原文第2页。'))
        for name in ['discussion','annotations','notes']:(self.root / (name+'.md')).write_text('# '+name+'\nSOURCE-'+name)
        self.job = {'paperKey': '1:fixture', 'title': '验证论文', 'authors': 'Test Author', 'date': '2026-10-18',
                    'problem': '排队等待', 'method': '自适应批处理', 'model': 'test-model',
                    'sources': {k: str(self.root / (k+'.md')) for k in ['discussion','annotations','notes']},
                    'images': [{'path': str(self.root / 'figure.png'), 'caption': '原文第2页图版', 'page': 2}],
                    'markdownPath': str(self.root / 'paper.md'), 'pdfPath': str(self.root / 'paper.pdf'),
                    'questions': [{'id': 'q'+str(i), 'question': '问题 '+str(i), 'correct': 'A', 'explanation': '解释，原文第1页',
                                   'options': [{'id': c, 'label': '选项'+c} for c in 'ABC']} for i in range(1, 8)], 'answers': []}
        self.path = self.root / 'job.json';a.save(self.path, self.job)
    def body(self, mechanism='整理好的论文笔记。', figure=''):
        contents=['摘要译文。','研究排队等待。',mechanism+'\n\n'+figure,'故事与专业机制。','论证依据。','实际讨论中的疑问。','批注尚未记录。','后续验证更多负载。','复习问题。','']
        return '\n\n'.join('## '+str(i)+'. '+heading+'\n\n'+content for i,(heading,content) in enumerate(zip(a.SECTIONS,contents))).rstrip()+'\n'
    def observe(self):
        result=self.command('lookup',str(self.path))
        job=a.read(self.path);job['existingNote']={k:result[k] for k in ['notePath','sha256']};a.save(self.path,job)
        return result
    def restore(self, old):a.BASE, a.CONFIG = old
    def command(self,*args):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):a.main(list(args))
        return json.loads(out.getvalue())
    def finish(self):
        for i in range(1,8):self.command('answer',str(self.path),'q'+str(i),'skip' if i==7 else 'A')
        return a.read(self.path)
    def core_questions(self):
        topics=['mechanism','detail','mechanism','detail','evidence','boundary','problem']
        return [dict(q,topic=topic,evidence={'page':2,'locator':'§3','quote':'Synthetic evidence'}) for q,topic in zip(self.job['questions'],topics)]
    def test_plain_directory_saves_markdown_and_referenced_images(self):
        (self.vault/'.obsidian').rmdir()
        self.finish();result=self.command('archive',str(self.path));note=Path(result['notePath'])
        self.assertEqual(result['format'],'markdown');self.assertEqual(result['noteUrl'],note.as_uri())
        self.assertNotIn('obsidianUrl',result);self.assertNotIn('indexPath',result)
        self.assertFalse((self.vault/'论文索引.base').exists());self.assertFalse((self.vault/'.obsidian').exists())
        self.assertIn('## 9. 我的自由补充',note.read_text());self.assertEqual(result['imagesVerified'],1)
        self.assertEqual(len(list(self.vault.rglob('*.md'))),1)
        self.assertFalse(list(self.vault.rglob('*.pdf')))
    def test_unconfigured_archive_uses_default_local_notes(self):
        a.CONFIG.unlink();self.finish();result=self.command('archive',str(self.path))
        self.assertEqual(Path(result['vaultPath']),(self.root/'notes').resolve())
        self.assertTrue(Path(result['notePath']).is_file());self.assertEqual(result['format'],'markdown')
    def test_plain_markdown_merge_preserves_personal_content_and_images(self):
        (self.vault/'.obsidian').rmdir()
        self.finish();result=self.command('archive',str(self.path));note=Path(result['notePath'])
        images={p.name:p.read_bytes() for p in (note.parent/'图片').iterdir()}
        note.write_text(note.read_text()+'\n我的新思考。\n')
        self.observe();draft=Path(self.job['markdownPath'])
        draft.write_text(draft.read_text().replace('用批处理减少排队等待。','批次大小需匹配流量。'))
        updated=self.command('archive',str(self.path))
        self.assertEqual(result['notePath'],updated['notePath'])
        self.assertIn('我的新思考。',note.read_text());self.assertIn('批次大小需匹配流量。',note.read_text())
        self.assertEqual(images,{p.name:p.read_bytes() for p in (note.parent/'图片').iterdir()})
        self.assertEqual(updated,self.command('archive',str(self.path)))
    def test_opening_markdown_directory_as_vault_keeps_existing_note(self):
        (self.vault/'.obsidian').rmdir()
        self.finish();first=self.command('archive',str(self.path));note=Path(first['notePath'])
        note.write_text(note.read_text()+'\n个人补充。\n');self.observe()
        (self.vault/'.obsidian').mkdir();result=self.command('archive',str(self.path))
        self.assertEqual(result['format'],'obsidian');self.assertEqual(result['notePath'],first['notePath'])
        self.assertIn('个人补充。',note.read_text());self.assertTrue(Path(result['indexPath']).is_file())
        self.assertTrue(result['obsidianUrl'].startswith('obsidian://'))
    def test_plain_directory_leaves_existing_bases_file_untouched(self):
        (self.vault/'.obsidian').rmdir();index=self.vault/'论文索引.base';index.write_text('Personal index')
        self.finish();self.command('archive',str(self.path));self.assertEqual(index.read_text(),'Personal index')
    def test_archive_rejects_relative_or_file_destination(self):
        self.finish()
        for path in ['relative/notes',str(self.root/'paper.pdf')]:
            a.save(a.CONFIG,{'vaultPath':path})
            with self.assertRaisesRegex(ValueError,'absolute local notes directory'):
                self.command('archive',str(self.path))
    def test_property_additions_merge_with_personal_properties(self):
        base='---\nkind: "paper-study"\n---\n\nText\n'
        current=base.replace('kind:', 'tags: [mine]\nkind:')+'\nMy thought.\n'
        proposed=base.replace('kind:', 'benchmark: "Task A"\nkind:')
        result=a.merge_note(base,current,proposed)
        self.assertIn('tags: [mine]',result);self.assertIn('benchmark: "Task A"',result);self.assertIn('My thought.',result)
    def test_core_quiz_requires_evidence_and_decisive_topics(self):
        job=dict(self.job,quizPolicy='paper-core-v1',questions=self.core_questions())
        a.validate(job)
        job['questions'][0]['evidence']['page']=0
        with self.assertRaises(ValueError):a.validate(job)
        job['questions']=self.core_questions()
        job['questions'][5]['topic']='problem'
        with self.assertRaises(ValueError):a.validate(job)
    def test_recall_metadata_and_scheme_image_survive_merge(self):
        self.job.update(benchmark='Task Suite A (test split)',baseline='Reference method B',故事类比='仓库分批发货，减少排队。',methodFigure=str(self.root/'figure.png'))
        a.save(self.path,self.job);self.finish();r=self.command('archive',str(self.path))
        note=Path(r['notePath']);fields,_=a.metadata(note.read_text())
        self.assertEqual(fields['benchmark'],self.job['benchmark']);self.assertTrue((self.vault/fields['论文方案图']).is_file())
        note.write_text(note.read_text().replace('baseline: "Reference method B"','baseline: "我的补充基线"')+'\n我的补充。\n')
        self.observe();self.command('archive',str(self.path));fields,_=a.metadata(note.read_text())
        self.assertEqual(fields['baseline'],'我的补充基线');self.assertIn('我的补充。',note.read_text())
    def test_existing_index_sort_widths_and_custom_view_are_preserved(self):
        config=json.loads(a.index_bytes());config['views'][0].update(sort=[{'property':'阅读日期','direction':'DESC'}],columnSize={'note.作者':120},groupBy={'property':'作者','direction':'ASC'})
        config['views'].append({'type':'cards','name':'我的卡片'})
        index=self.vault/'论文索引.base';a.save(index,config);a.update_index(self.vault);updated=a.read(index)
        self.assertEqual(updated['views'][0]['sort'],config['views'][0]['sort']);self.assertEqual(updated['views'][0]['columnSize'],config['views'][0]['columnSize'])
        self.assertNotIn('groupBy',updated['views'][0]);self.assertEqual(updated['views'][1]['name'],'我的卡片')
    def test_question_count(self):
        for n in [4,11]:
            with self.assertRaises(ValueError):a.validate(dict(self.job,questions=(self.job['questions']*2)[:n]))
    def test_listed_local_image_uri_is_archived_as_vault_image(self):
        path=Path(self.job['markdownPath']);image=Path(self.job['images'][0]['path'])
        path.write_text(path.read_text().replace(str(image),image.as_uri()))
        self.finish();result=self.command('archive',str(self.path))
        text=Path(result['notePath']).read_text()
        self.assertNotIn('file:///',text)
        self.assertEqual(result['imagesVerified'],1)
    def test_single_question_and_no_answer_leak(self):
        r=self.command('next',str(self.path));self.assertEqual(r['id'],'q1');self.assertNotIn('correct',r);self.assertNotIn('explanation',r)
    def test_reject_invalid_option_and_wrong_id(self):
        for q,ans in [('q2','A'),('q1','D')]:
            with self.assertRaises(ValueError):self.command('answer',str(self.path),q,ans)
        self.assertEqual(a.read(self.path)['answers'],[])
    def test_retries_do_not_answer_next_question(self):
        self.command('answer',str(self.path),'q1','A')
        with self.assertRaises(ValueError):self.command('answer',str(self.path),'q1','A')
        self.assertEqual(self.command('next',str(self.path))['id'],'q2')
    def test_resume_retains_record(self):
        self.command('answer',str(self.path),'q1','A');a.save(self.root/'input.json',self.job)
        first=self.command('init',str(self.root/'input.json'));self.command('answer',first['jobPath'],'q1','B')
        again=self.command('init',str(self.root/'input.json'));self.assertEqual(again['answered'],1)
    def test_prevents_premature_archive(self):
        with self.assertRaises(ValueError):self.command('archive',str(self.path))
        self.assertFalse((self.vault/'论文').exists())
    def test_only_note_and_referenced_images_are_exported(self):
        self.finish();r=self.command('archive',str(self.path));p=Path(r['notePath']).parent
        self.assertEqual({f.relative_to(p).as_posix() for f in p.rglob('*') if f.is_file()}, {'论文笔记.md','图片/figure-'+a.digest((self.root/'figure.png').read_bytes())[:16]+'.png'})
        self.assertEqual((p/('图片/figure-'+a.digest((self.root/'figure.png').read_bytes())[:16]+'.png')).read_bytes(),(self.root/'figure.png').read_bytes())
        self.assertTrue((self.root/'paper.pdf').is_file())
        self.assertEqual(r['filesVerified'],2);self.assertEqual(r['imagesVerified'],1)
    def test_curated_body_and_quiz_stay_in_their_locations(self):
        self.finish();r=self.command('archive',str(self.path));text=Path(r['notePath']).read_text()
        self.assertIn('用批处理减少排队等待。',text)
        self.assertIn('![实验结果](%E5%9B%BE%E7%89%87/figure-'+a.digest((self.root/'figure.png').read_bytes())[:16]+'.png)',text)
        self.assertNotIn(str(self.root),text);self.assertNotIn('原文.pdf',text)
        self.assertNotIn('SOURCE-',text);self.assertNotIn('选项C',text)
        self.assertEqual(text.count('![实验结果]'),1);self.assertEqual(r['mastery'],4)
        job=a.read(self.path);self.assertEqual(len(job['answers']),7)
        for source in job['sources'].values():self.assertTrue(Path(source).is_file())
    def test_manifest_stays_with_private_job(self):
        self.finish();r=self.command('archive',str(self.path));p=Path(r['notePath']).parent
        manifest=a.read(self.path)['archiveFiles']
        self.assertEqual(len(manifest),2)
        for name,m in manifest.items():self.assertEqual(hashlib.sha256((p/name).read_bytes()).hexdigest(),m['sha256'])
        self.assertFalse((p/'归档清单.json').exists())
    def test_unused_images_are_not_copied(self):
        unused=self.root/'unused.png';unused.write_bytes((self.root/'figure.png').read_bytes())
        self.job['images'].append({'path':str(unused),'caption':'未引用图','page':2})
        a.save(self.path,self.job);self.finish();r=self.command('archive',str(self.path))
        self.assertEqual(r['imagesVerified'],1)
        self.assertFalse((Path(r['notePath']).parent/'图片/figure-2.png').exists())
    def test_note_without_images(self):
        (self.root/'paper.md').write_text(self.body('整理好的纯文字笔记。'))
        self.job['images']=[];a.save(self.path,self.job);self.finish();r=self.command('archive',str(self.path))
        self.assertEqual(r['filesVerified'],1);self.assertEqual(r['imagesVerified'],0)
        self.assertFalse((Path(r['notePath']).parent/'图片').exists())
    def test_repeated_image_is_copied_once(self):
        note=self.root/'paper.md';note.write_text(note.read_text().replace('原文第2页。','原文第2页。\n![同一图](<' + str(self.root/'figure.png') + '>)'))
        self.finish();r=self.command('archive',str(self.path))
        self.assertEqual(r['imagesVerified'],1)
        self.assertEqual(Path(r['notePath']).read_text().count('%E5%9B%BE%E7%89%87/figure-'+a.digest((self.root/'figure.png').read_bytes())[:16]+'.png'),2)
    def test_unlisted_image_is_rejected_before_export(self):
        (self.root/'paper.md').write_text(self.body(figure='![缺失图片](/missing.png)'))
        self.finish()
        with self.assertRaises(ValueError):self.command('archive',str(self.path))
        self.assertFalse((self.vault/'论文').exists())
    def test_existing_extra_files_are_preserved(self):
        self.finish();r=self.command('archive',str(self.path));extra=Path(r['notePath']).parent/'用户资料.md'
        extra.write_text('用户内容')
        self.observe();self.command('archive',str(self.path))
        self.assertEqual(extra.read_text(),'用户内容')
    def test_idempotent_and_preserves_user_edits(self):
        self.finish();r=self.command('archive',str(self.path));self.assertEqual(r,self.command('archive',str(self.path)))
        note=Path(r['notePath']);note.write_text(note.read_text()+'\n用户补充')
        with self.assertRaises(ValueError):self.command('archive',str(self.path))
        self.observe();self.command('archive',str(self.path))
        self.assertIn('用户补充',note.read_text());self.assertEqual(len(list((self.vault/'论文').iterdir())),1)
    def test_requires_real_image_and_pdf(self):
        (self.root/'figure.png').write_text('placeholder')
        with self.assertRaises(ValueError):a.validate(self.job)
    def test_missing_material_status_stays_in_private_job(self):
        self.job['sources']['notes']={'missing':'此论文没有子笔记'};a.save(self.path,self.job);self.finish()
        r=self.command('archive',str(self.path))
        self.assertEqual(a.read(self.path)['sources']['notes']['missing'],'此论文没有子笔记')
        self.assertFalse((Path(r['notePath']).parent/'资料').exists())
    def test_expanded_index_with_recall_columns(self):
        self.finish();r=self.command('archive',str(self.path));base=json.loads(Path(r['indexPath']).read_text())
        self.assertEqual(len(base['views'][0]['order']),10);self.assertEqual(base['filters']['and'],['kind == "paper-study"'])
        self.assertEqual(base['views'][0]['order'][0], 'formula.论文笔记')
        self.assertEqual(base['formulas']['论文笔记'], 'file.asLink(note["论文名称"])')
    def test_cancellation_is_not_recorded_as_answer(self):
        self.command('next',str(self.path));self.assertEqual(a.read(self.path)['answers'],[])

    def test_template_requires_fixed_sections(self):
        (self.root/'paper.md').write_text('## 随意标题\n正文')
        self.finish()
        with self.assertRaises(ValueError):self.command('archive',str(self.path))
    def test_generated_personal_section_is_protected(self):
        (self.root/'paper.md').write_text(self.body()+'模型填入用户思考')
        self.finish()
        with self.assertRaises(ValueError):self.command('archive',str(self.path))
    def test_lookup_returns_actual_content_and_identity(self):
        self.finish();r=self.command('archive',str(self.path));found=self.command('lookup',str(self.path))
        self.assertTrue(found['found']);self.assertEqual(found['notePath'],r['notePath'])
        self.assertEqual(found['content'],Path(r['notePath']).read_text());self.assertEqual(found['match'],'zotero_key')
    def test_doi_lookup_reuses_moved_and_renamed_note(self):
        (self.root/'paper.md').write_text(self.body())
        self.job['doi']='https://doi.org/10.1234/PAPER';a.save(self.path,self.job)
        self.finish();r=self.command('archive',str(self.path));note=Path(r['notePath'])
        moved=self.vault/'我的论文';moved.mkdir();renamed=moved/'自定文件名.md';note.rename(renamed)
        job=a.read(self.path);job['paperKey']='2:another';job['doi']='doi:10.1234/paper';job['title']='更新后的题目'
        a.save(self.path,job);found=self.observe();self.assertEqual(found['match'],'doi')
        # This fixture has no images after moving; use a body without image references.
        (self.root/'paper.md').write_text(self.body())
        out=self.command('archive',str(self.path));self.assertEqual(out['notePath'],str(renamed.resolve()))
        self.assertEqual(len(list(self.vault.rglob('*.md'))),1)
    def test_title_alone_does_not_merge_different_papers(self):
        self.finish();self.command('archive',str(self.path));job=a.read(self.path);job['paperKey']='2:different';job.pop('existingNote');job.pop('archive');job.pop('archiveFiles');a.save(self.path,job)
        found=self.command('lookup',str(self.path));self.assertFalse(found['found']);self.assertEqual(len(found['titleCandidates']),1)
        self.command('archive',str(self.path));self.assertEqual(len(list((self.vault/'论文').iterdir())),2)
    def test_duplicate_identity_is_not_silently_chosen(self):
        self.finish();r=self.command('archive',str(self.path));(self.vault/'重复.md').write_text(Path(r['notePath']).read_text())
        with self.assertRaises(ValueError):self.command('lookup',str(self.path))
    def test_updates_same_note_preserving_manual_content_and_metadata(self):
        self.finish();r=self.command('archive',str(self.path));note=Path(r['notePath'])
        note.write_text(note.read_text().replace('kind:','tags: [moe, reading]\nkind:',1).replace('研究排队等待。','研究排队等待。\n我手写的研究动机。')+'\n我的个人理解和待办。\n')
        self.observe();(self.root/'paper.md').write_text(self.body('新增：自适应批处理减少等待，准确率需另行检验。'))
        result=self.command('archive',str(self.path));text=note.read_text()
        self.assertEqual(result['notePath'],str(note));self.assertIn('新增：自适应',text)
        self.assertIn('我手写的研究动机。',text);self.assertIn('我的个人理解和待办。',text);self.assertIn('tags: [moe, reading]',text)
        self.assertEqual(len(list((self.vault/'论文').iterdir())),1)
        self.assertTrue(list((self.root/'backups').rglob('论文笔记.md')))
    def test_conflict_retains_current_and_creates_private_draft(self):
        self.finish();r=self.command('archive',str(self.path));note=Path(r['notePath'])
        note.write_text(note.read_text().replace('用批处理减少排队等待。','我的人工修正。'));self.observe();before=note.read_bytes()
        (self.root/'paper.md').write_text(self.body('模型也修正同一段。'))
        with self.assertRaisesRegex(ValueError,'Merge conflict'):self.command('archive',str(self.path))
        self.assertEqual(note.read_bytes(),before);self.assertEqual(len(list((self.root/'merge-drafts').rglob('draft.json'))),1)
    def test_concurrent_edit_requires_lookup_again(self):
        self.finish();r=self.command('archive',str(self.path));self.observe();note=Path(r['notePath']);note.write_text(note.read_text()+'\n随后手写')
        with self.assertRaisesRegex(ValueError,'lookup first'):self.command('archive',str(self.path))
        self.assertIn('随后手写',note.read_text())
    def test_legacy_note_is_read_and_preserved_on_template_adoption(self):
        note=self.vault/'已有笔记.md';note.write_text('---\nzotero_key: "1:fixture"\ntags:\n  - 阅读中\n---\n# 我的标题\n\n手写的重要旧笔记。')
        self.observe();self.finish();r=self.command('archive',str(self.path));text=note.read_text()
        self.assertEqual(r['notePath'],str(note.resolve()));self.assertIn('手写的重要旧笔记。',text);self.assertIn('## 0. 摘要译文',text)
        self.assertIn('tags:\n  - 阅读中',text)
    def test_existing_referenced_images_survive_a_shorter_generated_note(self):
        self.finish();r=self.command('archive',str(self.path));image=next((Path(r['notePath']).parent/'图片').iterdir());self.observe()
        (self.root/'paper.md').write_text(self.body());r=self.command('archive',str(self.path))
        self.assertTrue(image.exists());self.assertEqual(r['imagesVerified'],1)
        self.assertIn(image.name,Path(r['notePath']).read_text())
    def test_completed_job_starts_new_quiz_with_old_record_retained(self):
        self.finish();self.command('archive',str(self.path));a.save(self.root/'input.json',self.job)
        first=self.command('init',str(self.root/'input.json'))
        for i in range(1,8):self.command('answer',first['jobPath'],'q'+str(i),'A')
        self.observe();first_job=a.read(first['jobPath']);first_job['existingNote']=a.read(self.path)['existingNote'];a.save(first['jobPath'],first_job)
        self.command('archive',first['jobPath'])
        again=self.command('init',str(self.root/'input.json'));self.assertEqual(again['answered'],0)
        self.assertEqual(len(list(Path(first['jobPath']).parent.glob('completed-*.json'))),1)

    def test_lookup_hashes_actual_crlf_bytes_and_preserves_yaml(self):
        note=self.vault/'Windows笔记.md';note.write_bytes('---\r\nzotero_key: "1:fixture"\r\ntags:\r\n  - 保留\r\n---\r\n手写笔记。\r\n'.encode())
        found=self.observe();self.assertEqual(found['sha256'],a.digest(note.read_bytes()))
        self.finish();self.command('archive',str(self.path));text=note.read_text()
        self.assertIn('手写笔记。',text);self.assertIn('tags:\n  - 保留',text)
    def test_wiki_image_in_personal_section_is_retained(self):
        self.finish();r=self.command('archive',str(self.path));note=Path(r['notePath']);image=next((note.parent/'图片').iterdir())
        note.write_text(note.read_text()+'\n我补充的图片：![['+image.name+']]\n');self.observe()
        (self.root/'paper.md').write_text(self.body());self.command('archive',str(self.path))
        self.assertTrue(image.is_file());self.assertIn('![['+image.name+']]',note.read_text())

    def test_acceptance_answers_do_not_set_personal_mastery(self):
        self.job['quizMode']='acceptance';a.save(self.path,self.job);self.finish()
        result=self.command('archive',str(self.path));fields,_=a.metadata(Path(result['notePath']).read_text())
        self.assertIsNone(fields['掌握程度']);self.assertEqual(fields['测验用途'],'自动验收');self.assertIsNone(result['mastery'])
    def test_acceptance_keeps_existing_personal_mastery(self):
        self.finish();result=self.command('archive',str(self.path));note=Path(result['notePath']);self.observe()
        job=a.read(self.path);job['quizMode']='acceptance';a.save(self.path,job)
        self.command('archive',str(self.path));fields,_=a.metadata(note.read_text());self.assertEqual(fields['掌握程度'],4)

    def test_unwrapped_image_path_with_spaces_is_archived(self):
        image=self.root/'folder with spaces'/'paper image.png';image.parent.mkdir();image.write_bytes((self.root/'figure.png').read_bytes())
        self.job['images']=[{'path':str(image),'caption':'真实图片','page':2}];a.save(self.path,self.job)
        (self.root/'paper.md').write_text(self.body(figure='![含空格路径]('+str(image)+')'))
        self.finish();r=self.command('archive',str(self.path));text=Path(r['notePath']).read_text()
        self.assertEqual(r['imagesVerified'],1);self.assertNotIn(str(image),text)
        exported=next((Path(r['notePath']).parent/'图片').iterdir());self.assertEqual(exported.read_bytes(),image.read_bytes())

    def test_legacy_template_migration_preserves_personal_edits_and_images(self):
        self.finish();result=self.command('archive',str(self.path));note=Path(result['notePath'])
        job=a.read(self.path);fields,_=a.metadata(note.read_text())
        state_path=a.BASE/'note-state'/(fields['paper_note_id']+'.json')
        state=a.read(state_path)
        header=note.read_text().split('## 0. 摘要译文',1)[0]
        image=next((note.parent/'图片').iterdir())
        contents=['旧总结','旧动机','旧方法','![旧图](图片/'+image.name+')','旧边界','旧概念','旧启发','']
        legacy=header+'\n\n'.join('## '+str(i)+'. '+n+'\n\n'+c for i,(n,c) in enumerate(zip(a.LEGACY_SECTIONS,contents),1))+'\n'
        state['generated']=legacy;a.save(state_path,state)
        note.write_text(legacy.replace('旧动机','旧动机\n人工动机补充')+'\n个人补充与图片：![['+image.name+']]\n')
        self.observe();before=image.read_bytes()
        # Keep the original motivation so this change is independent of the manual addition.
        (self.root/'paper.md').write_text(self.body().replace('研究排队等待。','旧动机'))
        result=self.command('archive',str(self.path));text=note.read_text()
        self.assertEqual(result['notePath'],str(note));self.assertIn('人工动机补充',text)
        self.assertIn('个人补充与图片',text);self.assertIn('## 9. 我的自由补充',text)
        self.assertIn('![['+image.name+']]',text);self.assertEqual(image.read_bytes(),before)
        self.assertEqual(a.metadata(text)[0]['模板版本'],5)

    def test_legacy_migration_conflict_preserves_the_existing_file(self):
        self.finish();result=self.command('archive',str(self.path));note=Path(result['notePath'])
        fields,_=a.metadata(note.read_text());state_path=a.BASE/'note-state'/(fields['paper_note_id']+'.json')
        state=a.read(state_path);header=note.read_text().split('## 0. 摘要译文',1)[0]
        legacy=header+'\n\n'.join('## '+str(i)+'. '+n+'\n\n'+('旧方法' if i==3 else '') for i,n in enumerate(a.LEGACY_SECTIONS,1))+'\n'
        state['generated']=legacy;a.save(state_path,state)
        note.write_text(legacy.replace('旧方法','用户修正的方法'));self.observe();before=note.read_bytes()
        with self.assertRaisesRegex(ValueError,'Merge conflict'):self.command('archive',str(self.path))
        self.assertEqual(note.read_bytes(),before)

    def test_missing_retained_image_does_not_replace_the_note(self):
        self.finish();result=self.command('archive',str(self.path));note=Path(result['notePath'])
        image=next((note.parent/'图片').iterdir());image.unlink();self.observe();before=note.read_bytes()
        (self.root/'paper.md').write_text(self.body())
        with self.assertRaisesRegex(ValueError,'retained image is missing'):self.command('archive',str(self.path))
        self.assertEqual(note.read_bytes(),before)

    def test_story_title_accepts_an_analogy_name(self):
        body=self.body().replace('## 3. 故事类比','## 3. 故事类比：厨房备菜')
        self.assertEqual(a.structured(body),body)

    def test_template_files_are_excluded_from_lookup(self):
        (self.vault/'模板.md').write_text('---\nkind: paper-template\nzotero_key: "1:fixture"\n---\n模板')
        self.assertFalse(self.command('lookup',str(self.path))['found'])

    def test_pdf_layout_has_page_dimensions_and_positioned_lines(self):
        result=self.command('pdf-layout',str(self.root/'paper.pdf'),'2')
        self.assertEqual(result['page'],2)
        self.assertEqual(len(result['pageSize']),2)
        self.assertTrue(result['blocks'])
        self.assertTrue(all(len(line['bbox'])==4 for b in result['blocks'] for line in b['lines']))

    def test_native_pdf_crop_has_verified_geometry_and_source_receipt(self):
        result=self.command('crop-figure',str(self.root/'paper.pdf'),'2','20','20','200','200',str(self.root/'crop.png'))
        self.assertEqual(result['pixelSize'],[360,360])
        self.assertEqual(result['kind'],'pdf_figure_crop')
        self.assertEqual(result['sha256'],a.digest((self.root/'crop.png').read_bytes()))
        self.assertEqual(a.read(result['receiptPath'])['pdfSha256'],a.digest((self.root/'paper.pdf').read_bytes()))

    def test_invalid_or_full_page_crop_bounds_are_rejected(self):
        for bbox in [[0,0,612,792],[-1,0,10,10],[0,0,900,20],[10,10,5,20],[0,0,float('nan'),20]]:
            with self.assertRaises(ValueError):a.check_crop_bounds(bbox,[612,792])

    def test_crop_output_is_not_silently_replaced(self):
        args=['crop-figure',str(self.root/'paper.pdf'),'2','20','20','200','200',str(self.root/'crop.png')]
        self.command(*args)
        self.command(*args)
        with self.assertRaises(ValueError):self.command(*args[:3],'30','30','200','200',args[-1])

    def test_figure_policy_requires_receipt_for_the_current_pdf_and_page(self):
        r=self.command('crop-figure',str(self.root/'paper.pdf'),'2','20','20','200','200',str(self.root/'crop.png'))
        image={'path':r['path'],'caption':'Figure 1','page':2,'receiptPath':r['receiptPath']}
        a.validate(dict(self.job,imagePolicy='figure-crops',images=[image]))
        for changes in [{'page':1},{'path':str(self.root/'figure.png')}]:
            with self.assertRaises(ValueError):a.validate(dict(self.job,imagePolicy='figure-crops',images=[dict(image,**changes)]))

    def test_approved_page_image_replacement_preserves_personal_content(self):
        self.finish();first=self.command('archive',str(self.path));note=Path(first['notePath'])
        old=next(n for n in a.read(self.path)['archiveFiles'] if n.startswith('图片/'))
        note.write_text(note.read_text()+'\nPERSONAL-KEEP-CROP\n')
        crop=self.command('crop-figure',str(self.root/'paper.pdf'),'2','20','20','200','200',str(self.root/'crop.png'))
        self.observe();job=a.read(self.path)
        job.update(imagePolicy='figure-crops',images=[{'path':crop['path'],'caption':'Figure 1','page':2,'receiptPath':crop['receiptPath']}],imageReplacements={a.quote(old):crop['path']})
        Path(job['markdownPath']).write_text(self.body(figure='![Figure 1](<'+a.quote(old)+'>)'))
        a.save(self.path,job)
        result=self.command('archive',str(self.path))
        result=self.command('archive',str(self.path))
        self.assertEqual(result['notePath'],first['notePath'])
        self.assertIn('PERSONAL-KEEP-CROP',note.read_text())
        self.assertEqual(result['imagesVerified'],1)
        self.assertNotIn(old,note.read_text())
        self.assertFalse((note.parent/old).exists())
        self.assertTrue(list((self.root/'backups').rglob(Path(old).name)))

    def test_archive_preserves_existing_index_customization(self):
        index=self.vault/'论文索引.base';custom='views: []\n# personal configuration\n';index.write_text(custom)
        self.finish();self.command('archive',str(self.path))
        updated=json.loads(index.read_text())
        self.assertEqual(updated['views'][0]['rowHeight'],'extra')
        self.assertEqual(next((self.root/'backups').glob('index-*.base')).read_text(),custom)

    def test_existing_zotero_navigation_link_is_not_duplicated(self):
        self.job['zoteroUrl']='zotero://select/library/items/fixture'
        link='[返回 Zotero]('+self.job['zoteroUrl']+')'
        Path(self.job['markdownPath']).write_text(self.body().replace(a.PERSONAL,link+'\n\n'+a.PERSONAL))
        a.save(self.path,self.job);self.finish();r=self.command('archive',str(self.path))
        self.assertEqual(Path(r['notePath']).read_text().count(link),1)

if __name__=='__main__':unittest.main()
