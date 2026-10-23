#!/usr/bin/python3
"""Quiz progress and verified local Obsidian bundles for Zotero."""
import difflib
import hashlib
import json
import math
import struct
import xml.etree.ElementTree as ET
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote

BASE = Path(__file__).resolve().parent
CONFIG = BASE / 'obsidian.json'
FIELDS = ['论文名称', '作者', '阅读日期', '核心问题', '论文方案', '掌握程度', 'benchmark', 'baseline', '故事类比', '论文方案图']


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix('.tmp')
    temp.touch(mode=0o600, exist_ok=True)
    temp.chmod(0o600)
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def image_suffix(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if data.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    raise ValueError('Expected a real PNG or JPEG paper image.')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate(data):
    for key in ['paperKey', 'title', 'authors', 'date', 'problem', 'method', 'markdownPath', 'pdfPath', 'sources']:
        if not data.get(key):
            raise ValueError('Missing field: ' + key)
    if data.get('quizMode', 'learning') not in ['learning', 'acceptance']:
        raise ValueError('quizMode must be learning or acceptance.')
    date.fromisoformat(data['date'])
    for key in ['markdownPath', 'pdfPath']:
        path = Path(data[key])
        if not path.is_absolute() or not path.is_file():
            raise ValueError('Expected an existing absolute file: ' + key)
    for name in ['discussion', 'annotations', 'notes']:
        source = data['sources'].get(name)
        if isinstance(source, dict) and source.get('missing'):
            continue
        if not isinstance(source, str) or not Path(source).is_absolute() or not Path(source).is_file():
            raise ValueError('Provide an existing source file or an explicit missing reason: ' + name)
    images = data.get('images', [])
    for image in images:
        path = Path(image.get('path', ''))
        if not path.is_absolute() or not path.is_file() or not image.get('caption') or not isinstance(image.get('page'), int) or image['page'] < 1:
            raise ValueError('Each image needs an absolute source path, caption and PDF page number.')
        image_suffix(path.read_bytes())
        if data.get('imagePolicy') == 'figure-crops':
            receipt = read(image.get('receiptPath', str(path) + '.json'))
            if (receipt.get('kind') != 'pdf_figure_crop' or receipt.get('sha256') != digest(path.read_bytes())
                    or receipt.get('pdfSha256') != digest(Path(data['pdfPath']).read_bytes())
                    or receipt.get('page') != image['page']):
                raise ValueError('A figure crop receipt must match the image, current PDF and page.')
            check_crop_bounds(receipt['bbox'], receipt['pageSize'])
    replacements = data.get('imageReplacements', {})
    if not isinstance(replacements, dict):
        raise ValueError('imageReplacements must map old relative image paths to new image paths.')
    for old, new in replacements.items():
        if not old or Path(unquote(old)).is_absolute() or '..' in Path(unquote(old)).parts or new not in [i['path'] for i in images]:
            raise ValueError('Each image replacement needs a vault-relative source and a listed new image.')
    if not Path(data['pdfPath']).read_bytes().startswith(b'%PDF-'):
        raise ValueError('The original document must be a PDF file.')
    questions = data.get('questions', [])
    if not 5 <= len(questions) <= 10:
        raise ValueError('The quiz requires 5–10 questions.')
    seen = set()
    topics = set()
    for q in questions:
        if data.get('quizPolicy') == 'paper-core-v1':
            evidence = q.get('evidence', {})
            if (q.get('topic') not in ['problem', 'mechanism', 'detail', 'evidence', 'boundary']
                    or not isinstance(evidence.get('page'), int) or evidence['page'] < 1
                    or not evidence.get('quote') or not evidence.get('locator')):
                raise ValueError('Each core-paper question needs a topic, PDF page, locator and supporting passage.')
            topics.add(q['topic'])
    if data.get('quizPolicy') == 'paper-core-v1' and sum(q.get('topic') in ['mechanism', 'detail'] for q in questions) * 2 < len(questions):
        raise ValueError('At least half the questions must test the mechanism or a decisive detail.')
    if data.get('quizPolicy') == 'paper-core-v1' and not {'mechanism', 'detail', 'evidence', 'boundary'} <= topics:
        raise ValueError('Cover the core mechanism, a decisive detail, experimental evidence and an applicability boundary.')
    for q in questions:
        if not q.get('id') or q['id'] in seen or not q.get('question') or not q.get('explanation'):
            raise ValueError('Each question needs a unique id, question, and explanation.')
        seen.add(q['id'])
        options = q.get('options', [])
        ids = [o['id'] for o in options if o.get('id') and o.get('label')]
        if not 3 <= len(options) <= 4 or len(set(ids)) != len(options) or q.get('correct') not in ids or 'skip' in ids:
            raise ValueError('Each question requires 3–4 distinct options and one correct option.')


def complete(job):
    answers = job.get('answers', [])
    if len(answers) != len(job['questions']) or any(a['questionId'] != q['id'] for a, q in zip(answers, job['questions'])):
        raise ValueError('Finish every quiz question before preparing or publishing the archive.')


def mastery(job):
    complete(job)
    correct = sum(a['selected'] == q['correct'] for a, q in zip(job['answers'], job['questions']))
    return correct, max(1, min(5, int(correct / len(job['questions']) * 5 + 0.5)))


def vault_path():
    vault = Path(read(CONFIG)['vaultPath']).expanduser()
    if not vault.is_absolute() or not vault.is_dir() or not (vault / '.obsidian').is_dir():
        raise ValueError('Configure an existing absolute Obsidian vault directory.')
    return vault


def index_bytes():
    config = {'filters': {'and': ['kind == "paper-study"']},
              'formulas': {'论文笔记': 'file.asLink(note["论文名称"])', '方案图预览': 'if(note["论文方案图"], image(note["论文方案图"]))'},
              'properties': {**{'note.' + n: {'displayName': n} for n in FIELDS[1:]},
                             'formula.论文笔记': {'displayName': '论文名称'}, 'formula.方案图预览': {'displayName': '论文方案图'}},
              'views': [{'type': 'table', 'name': '论文索引', 'rowHeight': 'extra', 'order': ['formula.论文笔记'] + ['note.' + n for n in FIELDS[1:-1]] + ['formula.方案图预览']}]}
    return json.dumps(config, ensure_ascii=False, indent=2).encode()


def pdf_binary(name):
    binary = shutil.which(name)
    if not binary:
        raise ValueError('Install Poppler and add ' + name + ' to PATH.')
    return binary


def update_index(vault):
    """Keep custom views; add a managed, expanded review table when YAML is user-authored."""
    path = vault / '论文索引.base'
    config = json.loads(index_bytes())
    if path.exists():
        previous = path.read_bytes()
        try:
            current = json.loads(previous)
        except ValueError:
            import yaml
            current = yaml.safe_load(previous) or {}
        backup = BASE / 'backups' / ('index-' + digest(previous)[:16] + '.base')
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            backup.write_bytes(previous)
        current.setdefault('formulas', {}).update(config['formulas'])
        current.setdefault('properties', {}).update(config['properties'])
        views = current.setdefault('views', [])
        table = next((v for v in views if v.get('name') == '论文索引' and v.get('type') == 'table'), None)
        if table is None:
            views.append(config['views'][0])
        else:
            order = list(dict.fromkeys('note.' + column if column in FIELDS else column for column in table.get('order', [])))
            table['order'] = order
            for column in config['views'][0]['order']:
                if column not in order:
                    order.append(column)
            table['rowHeight'] = 'extra'
            table.pop('groupBy', None)
        config = current
    save(path, config)
    return path


LEGACY_SECTIONS = ['一句话总结', '核心问题与研究动机', '方法与核心机制', '关键证据与图表', '边界、局限与复现要点', '概念与易错点', '关联与后续思考', '我的思考与补充']
SECTIONS = ['摘要译文', '序：为什么值得读', '快速理解论文', '故事类比', '包装技巧', '我的核心问题与理解变化', '批注与笔记中的思考', '我的关联、启发与下一步', '复习时问自己', '我的自由补充']
PERSONAL = '## 9. 我的自由补充'
IMAGE = re.compile(r'!\[([^\]\n]*)\]\((?:<([^>\n]+)>|([^)\n]+))\)')


def metadata(text):
    text = text.replace('\r\n', '\n')
    fields = {}
    if text.startswith('---\n') and '\n---\n' in text[4:]:
        raw, text = text[4:].split('\n---\n', 1)
        for line in raw.splitlines():
            m = re.match(r'^([^:#][^:]*):\s*(.*)$', line)
            if m:
                try:
                    fields[m[1]] = json.loads(m[2])
                except ValueError:
                    fields[m[1]] = m[2].strip("'\"")
    return fields, text.lstrip('\n')


def doi(value):
    return re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)', '', unquote(str(value or '')).strip(), flags=re.I).lower()


def lookup(job):
    vault = vault_path().resolve()
    matches, candidates = [], []
    for path in vault.rglob('*.md'):
        if any(part.startswith('.') for part in path.relative_to(vault).parts) or not path.resolve().is_relative_to(vault):
            continue
        raw = path.read_bytes()
        text = raw.decode('utf-8')
        fields, _ = metadata(text)
        if fields.get('kind') == 'paper-template':
            continue
        same_key = bool(job.get('paperKey') and fields.get('zotero_key') == job['paperKey'])
        same_doi = bool(doi(job.get('doi')) and doi(fields.get('doi')) == doi(job['doi']))
        if same_key or same_doi:
            matches.append({'notePath': str(path), 'sha256': digest(raw), 'match': 'zotero_key' if same_key else 'doi', 'content': text})
        elif job.get('title') and str(fields.get('论文名称') or path.stem).strip().casefold() == job['title'].strip().casefold():
            candidates.append(str(path))
    if len(matches) > 1:
        raise ValueError('Multiple notes match this paper; resolve duplicates before updating: ' + json.dumps([m['notePath'] for m in matches], ensure_ascii=False))
    return {'found': bool(matches), **(matches[0] if matches else {}), 'titleCandidates': candidates}


def structured(markdown):
    headings = re.findall(r'^## (.+)$', markdown, flags=re.M)
    normalized = [re.sub(r'^(3\. 故事类比)[：:].*$', r'\1', h) for h in headings]
    if normalized != [str(i) + '. ' + name for i, name in enumerate(SECTIONS)]:
        raise ValueError('Use the ten sections (0–9) from 模板/论文复习与思考.md in order.')
    if re.search(r'^# ', markdown, flags=re.M) or markdown.startswith('---\n'):
        raise ValueError('Provide the template body only; the helper writes the title and properties.')
    if markdown.split(PERSONAL, 1)[1].strip():
        raise ValueError('Leave the personal section empty in generated input; existing personal content is preserved.')
    return markdown.rstrip() + '\n'


def migrate_legacy(text):
    pattern = r'^## (?:' + '|'.join(re.escape(str(i) + '. ' + n) for i, n in enumerate(LEGACY_SECTIONS, 1)) + r')\s*$'
    parts = re.split(pattern, text, flags=re.M)
    if len(parts) != 9:
        return text
    # Transform baseline and current text identically so user edits remain mergeable.
    content = ['', parts[2], '\n'.join(parts[i] for i in [1, 3, 4, 5, 6]), '', '', '', '', parts[7], '', parts[8]]
    return parts[0].rstrip() + '\n\n' + '\n\n'.join('## ' + str(i) + '. ' + n + '\n\n' + body.strip() for i, (n, body) in enumerate(zip(SECTIONS, content))).rstrip() + '\n'


def retain_images(current, note):
    def embeds(text):
        found = [(unquote(m[2] or m[3]), m[0]) for m in IMAGE.finditer(text)]
        found += [(m[1].split('|', 1)[0], m[0]) for m in re.finditer(r'!\[\[([^\]\n]+)\]\]', text)]
        return found
    seen = {source for source, _ in embeds(note)}
    retained = []
    for source, embed in embeds(current):
        if source not in seen:
            retained.append(embed)
            seen.add(source)
    if retained:
        note = re.sub(r'^## 3\. 故事类比', lambda m: '### 参考图表\n\n' + '\n\n'.join(retained) + '\n\n' + m[0], note, count=1, flags=re.M)
    return note


def merge_lines(base, current, proposed):
    lines = base.splitlines(keepends=True)
    def edits(text):
        target = text.splitlines(keepends=True)
        return [(i, j, target[x:y]) for tag, i, j, x, y in difflib.SequenceMatcher(None, lines, target, autojunk=False).get_opcodes() if tag != 'equal']
    user, generated = edits(current), edits(proposed)
    combined = list(user)
    for change in generated:
        if change in user:
            continue
        start, end, _ = change
        for left, right, _ in user:
            overlap = max(start, left) < min(end, right)
            # Insertions at a changed boundary need review because their order is ambiguous.
            overlap |= start == end and left <= start <= right
            overlap |= left == right and start <= left <= end
            if overlap:
                raise ValueError('The same passage has user edits and new generated content. Review the private merge draft; the existing note is preserved.')
        combined.append(change)
    for start, end, replacement in sorted(combined, key=lambda e: (e[0], e[1]), reverse=True):
        lines[start:end] = replacement
    return ''.join(lines)


def merge_note(base, current, proposed):
    def split(text):
        normalized = text.replace('\r\n', '\n')
        if normalized.startswith('---\n') and '\n---\n' in normalized[4:]:
            return normalized[4:].split('\n---\n', 1)
        return None
    parts = [split(text) for text in [base, current, proposed]]
    if not all(parts):
        return merge_lines(base, current, proposed)
    (base_header, base_body), (header, current_body), (new_header, new_body) = parts
    def blocks(raw):
        matches = list(re.finditer(r'(?m)^([^:#\s][^:]*):', raw))
        return {match[1]: raw[match.start():matches[i+1].start() if i+1 < len(matches) else len(raw)].rstrip('\n')
                for i, match in enumerate(matches)}
    before, actual, generated = blocks(base_header), blocks(header), blocks(new_header)
    for key, block in generated.items():
        if key in actual and actual[key] != before.get(key):
            continue  # A user-owned property keeps its exact value and formatting.
        if key in actual:
            header = header.replace(actual[key], block, 1)
        else:
            header = header.rstrip('\n') + '\n' + block
    return '---\n' + header.rstrip('\n') + '\n---\n' + merge_lines(base_body, current_body, new_body)


def archive(path, job):
    validate(job)
    correct, stars = mastery(job)
    vault = vault_path().resolve()
    index_path = vault / '论文索引.base'
    if index_path.exists():
        try:
            json.loads(index_path.read_bytes())
        except ValueError:
            import yaml
            if not isinstance(yaml.safe_load(index_path.read_bytes()), dict):
                raise ValueError('The existing Bases index must be a configuration object.')
    found = lookup(job)
    observed = job.get('existingNote', {})
    if found['found']:
        prior_hash = job.get('archiveFiles', {}).get(Path(found['notePath']).name, {}).get('sha256')
        if not (observed.get('notePath') == found['notePath'] and observed.get('sha256') == found['sha256']) and prior_hash != found['sha256']:
            raise ValueError('Read lookup first and put its notePath and sha256 in existingNote before updating.')
        note_path = Path(found['notePath'])
        current = found['content']
    else:
        if observed:
            raise ValueError('The previously read note moved or changed identity. Run lookup again.')
        safe_title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '-', job['title']).strip('. ')[:70] or '论文'
        note_path = vault / '论文' / (safe_title + '--' + digest(job['paperKey'].encode())[:12]) / '论文笔记.md'
        if note_path.parent.exists():
            raise ValueError('The destination exists without a matching identity; inspect it before writing.')
        current = ''
    destination = note_path.parent
    fields, old_body = metadata(current)
    note_id = fields.get('paper_note_id') or digest(str(note_path).encode())[:24]
    if not re.fullmatch(r'[a-f0-9]{24}', note_id):
        raise ValueError('Invalid paper_note_id in the existing note.')
    state_path = BASE / 'note-state' / (note_id + '.json')
    state = read(state_path) if state_path.exists() else {}
    files = {}
    markdown = structured(Path(job['markdownPath']).read_text(encoding='utf-8'))
    images = {image['path']: image for image in job.get('images', [])}

    def add_image(source):
        data = Path(source).read_bytes()
        name = '图片/figure-' + digest(data)[:16] + image_suffix(data)
        files[name] = data
        return name

    replacements = {unquote(old): add_image(new) for old, new in job.get('imageReplacements', {}).items()}

    def embed(match):
        source = unquote(match[2] or match[3])
        if source.startswith('file:///'):
            source = source[7:]
        if source in images:
            name = add_image(source)
        elif source in replacements:
            name = replacements[source]
        else:
            image = (destination / source).resolve()
            if Path(source).is_absolute() or not image.is_relative_to(vault) or not image.is_file():
                raise ValueError('Each embedded image must be listed in images or exist inside the vault: ' + source)
            image_suffix(image.read_bytes())
            name = source
        return '![' + match[1] + '](' + quote(name) + ')'

    def replace_images(text):
        text = IMAGE.sub(lambda m: '![' + m[1] + '](' + quote(replacements[unquote(m[2] or m[3])]) + ')' if unquote(m[2] or m[3]) in replacements else m[0], text)
        return re.sub(r'!\[\[([^\]\n]+)\]\]', lambda m: '![[' + replacements.get(unquote(m[1].split('|', 1)[0]), m[1].split('|', 1)[0]) + ('|' + m[1].split('|', 1)[1] if '|' in m[1] else '') + ']]', text)

    if '![[' in markdown:
        raise ValueError('Use Markdown image embeds in generated input.')
    markdown = IMAGE.sub(embed, markdown)
    if job.get('quizMode') == 'acceptance':
        stars = fields.get('掌握程度')
    generated_fields = dict(zip(FIELDS[:6], [job['title'], job['authors'], job['date'], job['problem'], job['method'], stars]))
    for field in ['benchmark', 'baseline', '故事类比']:
        if field in job:
            generated_fields[field] = job[field]
        else:
            generated_fields[field] = fields.get(field, '待核实')
    if job.get('methodFigure'):
        source = job['methodFigure']
        if source not in images:
            raise ValueError('methodFigure must identify one of the verified paper images.')
        relative_image = add_image(source)
        if quote(relative_image) not in markdown and relative_image not in markdown:
            raise ValueError('The method figure must also be referenced in the note.')
        generated_fields['论文方案图'] = (destination / relative_image).relative_to(vault).as_posix()
    generated_fields.update({'kind': 'paper-study', 'zotero_key': job['paperKey'], 'paper_note_id': note_id, '模板版本': 5})
    if job.get('quizMode') == 'acceptance':
        generated_fields['测验用途'] = '自动验收'
    if job.get('doi'):
        generated_fields['doi'] = doi(job['doi'])
    header = '---\n' + '\n'.join(k + ': ' + json.dumps(v, ensure_ascii=False) for k, v in generated_fields.items()) + '\n---\n'
    if job.get('zoteroUrl'):
        zotero_link = '[返回 Zotero](' + job['zoteroUrl'] + ')'
        if zotero_link not in markdown:
            markdown = markdown.replace(PERSONAL, zotero_link + '\n\n' + PERSONAL)
    proposed = header + '\n# ' + job['title'] + '\n\n' + markdown
    if current and state:
        try:
            note = merge_note(replace_images(migrate_legacy(state['generated'])), replace_images(migrate_legacy(current)), proposed)
        except ValueError:
            draft = BASE / 'merge-drafts' / note_id / 'draft.json'
            save(draft, {'notePath': str(note_path), 'base': state['generated'], 'current': current, 'proposed': proposed})
            raise ValueError('Merge conflict. Existing note preserved; review: ' + str(draft))
    elif current:
        # An imported note has no generated baseline. Keep its complete body in the personal section.
        retained = re.sub(r'^(#{1,6}) ', lambda m: '#' * min(6, len(m[1]) + 2) + ' ', old_body, flags=re.M)
        normalized = current.replace('\r\n', '\n')
        raw = normalized[4:].split('\n---\n', 1)[0] if normalized.startswith('---\n') else ''
        for key, value in generated_fields.items():
            line = key + ': ' + json.dumps(value, ensure_ascii=False)
            if re.search(r'^' + re.escape(key) + r':.*$', raw, flags=re.M):
                raw = re.sub(r'^' + re.escape(key) + r':.*$', lambda _: line, raw, count=1, flags=re.M)
            else:
                raw += '\n' + line
        note = '---\n' + raw.strip('\n') + '\n---\n' + proposed.split('\n---\n', 1)[1]
        note += '\n### 已有笔记\n\n' + retained.rstrip() + '\n'
    else:
        note = proposed
    note = retain_images(replace_images(current), note)
    referenced = set()
    for match in IMAGE.finditer(note):
        source = unquote(match[2] or match[3])
        image = (destination / source).resolve()
        if image.is_relative_to(destination) and source not in files:
            if not image.is_file():
                raise ValueError('A retained image is missing: ' + source)
            files[source] = image.read_bytes()
        referenced.add(source)
    # Keep user image embeds in the personal section when checking managed image retention.
    for source in re.findall(r'!\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', note):
        referenced.add(source)
    files = {name: data for name, data in files.items() if name in referenced}
    for name, data in files.items():
        target = destination / name
        if target.exists() and target.read_bytes() != data:
            raise ValueError('An existing image differs. Keep the original image: ' + str(target))
    files[note_path.name] = note.encode()
    manifest = {name: {'sha256': digest(data), 'bytes': len(data)} for name, data in files.items()}
    obsolete = [name for name in state.get('files', {}) if name.startswith('图片/') and name not in files and not any(Path(ref).name == Path(name).name for ref in referenced)]
    if current and (note != current or obsolete):
        backup = BASE / 'backups' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '-' + note_id)
        backup.mkdir(parents=True, mode=0o700)
        shutil.copy2(note_path, backup / note_path.name)
        for name in obsolete:
            old = destination / name
            if old.is_file():
                (backup / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old, backup / name)
    destination.mkdir(parents=True, exist_ok=True)
    # Images are in place before the note is atomically replaced.
    for name, data in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() == data:
            continue
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            staged = Path(handle.name)
            handle.write(data)
        if name == note_path.name and current and digest(note_path.read_bytes()) != found['sha256']:
            staged.unlink()
            raise ValueError('The note changed during archive. Read lookup again.')
        staged.replace(target)
    for name in obsolete:
        (destination / name).unlink(missing_ok=True)
    for name, data in files.items():
        if digest((destination / name).read_bytes()) != digest(data):
            raise ValueError('Archive readback failed: ' + name)
    save(state_path, {'generated': proposed, 'files': manifest, 'notePath': str(note_path)})
    index = vault / '论文索引.base'
    update_index(vault)
    result = {'vaultPath': str(vault), 'notePath': str(note_path), 'indexPath': str(index),
              'filesVerified': len(files), 'imagesVerified': len(files) - 1, 'correct': correct,
              'total': len(job['questions']), 'mastery': stars,
              'obsidianUrl': 'obsidian://open?path=' + quote(str(note_path), safe='')}
    job['archiveFiles'] = manifest
    job['archive'] = result
    job['existingNote'] = {'notePath': str(note_path), 'sha256': digest(note.encode())}
    save(path, job)
    return result


def page_image(pdf, page, output):
    pdf, output = Path(pdf), Path(output)
    page = int(page)
    if page < 1 or not pdf.is_absolute() or not pdf.is_file() or not output.is_absolute() or output.suffix != '.png':
        raise ValueError('Use an absolute PDF path, a positive page and an absolute .png output path.')
    binary = pdf_binary('pdftoppm')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / 'page'
        result = subprocess.run([binary, '-f', str(page), '-l', str(page), '-singlefile', '-scale-to', '1800', '-png', str(pdf), str(target)], capture_output=True, timeout=60)
        source = target.with_suffix('.png')
        if result.returncode or not source.is_file():
            raise ValueError('Could not render the requested PDF page.')
        data = source.read_bytes()
        image_suffix(data)
        if output.exists() and output.read_bytes() != data:
            raise ValueError('Image output exists with different bytes; choose a fresh output path.')
        output.write_bytes(data)
        output.chmod(0o600)
    return {'path': str(output), 'page': page, 'sha256': digest(data), 'kind': 'pdf_page_image'}


def pdf_layout(pdf, page):
    pdf = Path(pdf)
    page = int(page)
    if not pdf.is_absolute() or not pdf.is_file() or page < 1:
        raise ValueError('Use an existing absolute PDF path and positive page number.')
    binary = pdf_binary('pdftotext')
    result = subprocess.run([binary, '-f', str(page), '-l', str(page), '-bbox-layout', str(pdf), '-'], capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError('Could not read the requested PDF page layout.')
    element = ET.fromstring(result.stdout).find('.//{*}page')
    if element is None:
        raise ValueError('The requested PDF page is unavailable.')
    def bounds(node):
        return [float(node.attrib[k]) for k in ['xMin', 'yMin', 'xMax', 'yMax']]
    blocks = [{'bbox': bounds(block), 'lines': [
        {'bbox': bounds(line), 'text': ' '.join(''.join(w.itertext()) for w in line.findall('{*}word'))}
        for line in block.findall('{*}line')]} for block in element.findall('.//{*}block')]
    return {'page': page, 'pageSize': [float(element.attrib['width']), float(element.attrib['height'])],
            'coordinates': 'PDF points; origin top-left; x increases right; y increases down', 'blocks': blocks}


def check_crop_bounds(bbox, page_size):
    if len(bbox) != 4 or len(page_size) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in [*bbox, *page_size]):
        raise ValueError('Use four finite PDF point coordinates for the figure rectangle.')
    x0, y0, x1, y1 = bbox
    width, height = page_size
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height) or (x0 == y0 == 0 and x1 == width and y1 == height):
        raise ValueError('The figure rectangle must be inside the page and smaller than the full page.')


def crop_figure(pdf, page, x0, y0, x1, y1, output):
    layout = pdf_layout(pdf, page)
    bbox = [float(v) for v in [x0, y0, x1, y1]]
    check_crop_bounds(bbox, layout['pageSize'])
    output = Path(output)
    if not output.is_absolute() or output.suffix.lower() != '.png':
        raise ValueError('Use an absolute .png path for the figure crop.')
    # At 144 dpi each PDF point is two pixels; round outward to retain edge labels.
    left, top = math.floor(bbox[0] * 2), math.floor(bbox[1] * 2)
    width, height = math.ceil(bbox[2] * 2) - left, math.ceil(bbox[3] * 2) - top
    binary = pdf_binary('pdftoppm')
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / 'figure'
        result = subprocess.run([binary, '-f', str(page), '-l', str(page), '-singlefile', '-r', '144',
                                 '-x', str(left), '-y', str(top), '-W', str(width), '-H', str(height),
                                 '-png', str(pdf), str(target)], capture_output=True, timeout=60)
        source = target.with_suffix('.png')
        if result.returncode or not source.is_file():
            raise ValueError('Could not render the selected PDF figure rectangle.')
        data = source.read_bytes()
    image_suffix(data)
    dimensions = list(struct.unpack('>II', data[16:24]))
    if dimensions != [width, height]:
        raise ValueError('Rendered crop dimensions differ from the selected figure rectangle.')
    if output.exists() and output.read_bytes() != data:
        raise ValueError('Crop output exists with different bytes; choose a fresh output path.')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    output.chmod(0o600)
    receipt = {'kind': 'pdf_figure_crop', 'path': str(output), 'pdfSha256': digest(Path(pdf).read_bytes()),
               'page': int(page), 'pageSize': layout['pageSize'], 'bbox': bbox, 'pixelSize': dimensions,
               'sha256': digest(data), 'receiptPath': str(output) + '.json'}
    save(receipt['receiptPath'], receipt)
    lines = [line['text'] for block in layout['blocks'] for line in block['lines']
             if line['bbox'][0] >= bbox[0] and line['bbox'][1] >= bbox[1] and line['bbox'][2] <= bbox[2] and line['bbox'][3] <= bbox[3]]
    return {**receipt, 'containedText': lines, 'check': 'Verify axes, legends and all panels; captions belong in Markdown; body paragraphs must remain outside the crop.'}


def main(args):
    command = args[0]
    if command == 'index':
        print(json.dumps({'indexPath': str(update_index(vault_path()))}, ensure_ascii=False))
        return
    if command == 'status':
        print(json.dumps({'vaultPath': str(vault_path()), 'storage': 'local', 'quizRange': [5, 10]}, ensure_ascii=False))
        return
    if command == 'lookup':
        print(json.dumps(lookup(read(args[1])), ensure_ascii=False))
        return
    if command == 'page-image':
        print(json.dumps(page_image(*args[1:]), ensure_ascii=False))
        return
    if command == 'pdf-layout':
        print(json.dumps(pdf_layout(*args[1:]), ensure_ascii=False))
        return
    if command == 'crop-figure':
        print(json.dumps(crop_figure(*args[1:]), ensure_ascii=False))
        return
    if command == 'init':
        job = read(args[1])
        validate(job)
        key = digest(job['paperKey'].encode())[:20]
        path = BASE / 'jobs' / key / 'job.json'
        if path.exists() and read(path).get('archive'):
            previous = read(path)
            save(path.parent / ('completed-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.json'), previous)
            path.unlink()
        if not path.exists():
            job['answers'] = []
            save(path, job)
        print(json.dumps({'jobPath': str(path), 'answered': len(read(path)['answers'])}, ensure_ascii=False))
        return
    path = Path(args[1]).resolve()
    job = read(path)
    validate(job)
    if command == 'next':
        index = len(job['answers'])
        result = {'complete': True} if index == len(job['questions']) else {
            'number': index + 1, 'total': len(job['questions']),
            **{k: job['questions'][index][k] for k in ('id', 'question', 'options')}}
    elif command == 'answer':
        index = len(job['answers'])
        if index >= len(job['questions']):
            raise ValueError('The quiz is already complete.')
        question = job['questions'][index]
        if args[2] != question['id']:
            raise ValueError('Question id does not match the current question; read next before answering.')
        selected = args[3]
        if selected not in [o['id'] for o in question['options']] + ['skip']:
            raise ValueError('Choose a listed option or skip.')
        job['answers'].append({'questionId': question['id'], 'selected': selected, 'answeredAt': datetime.now(timezone.utc).isoformat()})
        save(path, job)
        result = {'correct': selected == question['correct'], 'answer': question['correct'], 'explanation': question['explanation'], 'remaining': len(job['questions']) - index - 1}
    elif command == 'archive':
        result = archive(path, job)
    else:
        raise ValueError('Unknown command.')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except Exception as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False))
        sys.exit(1)
