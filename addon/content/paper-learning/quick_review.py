#!/usr/bin/python3
"""Keep paper review evidence outside the vault and project it for chat."""
import json
import shutil
import tempfile
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.dont_write_bytecode = True
from learning_archive import BASE, digest, read, save


def sections(text):
    if re.findall(r'(?m)^## ([0-4])\. ', text) != list('01234'):
        raise ValueError('Each review section must occur exactly once, in order.')
    parts = re.split(r'(?m)^(## [0-4]\. .+)$', text)
    result = {int(parts[i][3]): parts[i] + '\n' + parts[i + 1]
              for i in range(1, len(parts), 2)}
    if list(result) != list(range(5)) or re.search(r'(?m)^## (?![0-4]\. )', text):
        raise ValueError('The note review must contain only sections 0–4, in order.')
    return result


def project(text):
    output = []
    for number, section in sections(text).items():
        if number == 0:
            continue
        if number == 4:
            section = re.split(r'(?m)^### 可以迁移|^\*\*(?:论证缺口|写作迁移)', section)[0]
        lines, in_callout = [], False
        for line in section.splitlines():
            if re.match(r'^\s*>\s*\[!', line):
                in_callout = True
                continue
            if in_callout:
                if re.match(r'^\s*>', line) or not line.strip():
                    continue
                in_callout = False
            lines.append(line)
        output.append('\n'.join(lines).strip())
    chat = '\n\n'.join(output) + '\n'
    if re.search(r'\[![\w-]+\]|<\/?[a-zA-Z][^>]*>|^%%', chat, re.M):
        raise ValueError('Use standard Markdown for chat; put note markup in callouts.')
    return chat


def cache_path(identity):
    if not isinstance(identity.get('paperKey'), str) or not identity['paperKey'].strip():
        raise ValueError('paperKey is required.')
    return BASE / 'reviews' / digest(identity['paperKey'].encode())[:20] / 'review.json'


def file_record(path):
    path = Path(path)
    if not path.is_absolute() or not path.is_file():
        raise ValueError('Expected an existing absolute file: ' + str(path))
    return {'path': str(path), 'sha256': digest(path.read_bytes())}


def publish(data):
    path = cache_path(data)
    pdf = file_record(data['pdfPath'])
    if not Path(pdf['path']).read_bytes().startswith(b'%PDF-'):
        raise ValueError('pdfPath must be the original PDF.')
    # Publish immutable copies. Later edits or cleanup of the work directory do not invalidate a review.
    source_note = file_record(data['noteMarkdownPath'])
    source_text = Path(source_note['path']).read_text(encoding='utf-8')
    project(source_text)
    source_assets = [file_record(p) for p in data.get('assets', [])]
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = Path(tempfile.mkdtemp(prefix='snapshot-', dir=path.parent))
    snapshot.chmod(0o700)
    assets = []
    for number, record in enumerate(source_assets):
        target = snapshot / (str(number) + '-' + Path(record['path']).name)
        shutil.copyfile(record['path'], target); target.chmod(0o600)
        source_text = source_text.replace(record['path'], str(target))
        assets.append(file_record(target))
    note_path = snapshot / 'note-review.md'
    note_path.write_text(source_text, encoding='utf-8'); note_path.chmod(0o600)
    note = file_record(note_path)
    chat = project(source_text)
    pending = data.get('pending', [])
    if not isinstance(pending, list) or any(not isinstance(p, str) for p in pending):
        raise ValueError('pending must be a list of missing work descriptions.')
    path.parent.mkdir(parents=True, exist_ok=True)
    chat_path = snapshot / 'chat.md'
    chat_path.write_text(chat, encoding='utf-8'); chat_path.chmod(0o600)
    manifest = {'schema': 1, 'paperKey': data['paperKey'], 'pdf': pdf,
                'note': note, 'chat': file_record(chat_path), 'assets': assets,
                'pending': pending, 'createdAt': datetime.now(timezone.utc).isoformat()}
    save(path, manifest)
    return find(data)


def find(identity):
    path = cache_path(identity)
    host = path.parent / 'completed-chat.json'
    if host.is_file():
        record = read(host)
        cached = read(path) if path.is_file() else {}
        host_file = Path(record.get('chatMarkdownPath', ''))
        if (record.get('paperKey') == identity['paperKey'] and host_file.is_file() and
                record.get('pdfSha256') == file_record(identity['pdfPath'])['sha256'] and
                digest(host_file.read_bytes()) == record.get('chatSha256') and
                record.get('chatSha256') != cached.get('chat', {}).get('sha256') and
                record.get('createdAt', '') > cached.get('createdAt', '')):
            return {'found': True, 'chatOnly': True, 'paperKey': identity['paperKey'],
                    'chatMarkdownPath': record['chatMarkdownPath'],
                    'pdfSha256': record['pdfSha256'], 'assets': [],
                    'pending': ['Reuse the saved chat. Add only missing note-only sections and evidence.']}
    if not path.is_file():
        return {'found': False, 'reason': 'No saved review for this paper.'}
    manifest = read(path)
    if manifest.get('schema') != 1 or manifest.get('paperKey') != identity['paperKey']:
        return {'found': False, 'reason': 'Review identity or schema differs.'}
    if file_record(identity['pdfPath'])['sha256'] != manifest['pdf']['sha256']:
        return {'found': False, 'reason': 'The current PDF differs; verify affected evidence.'}
    invalid = []
    for record in [manifest['note'], manifest['chat'], *manifest['assets']]:
        p = Path(record['path'])
        if not p.is_file() or digest(p.read_bytes()) != record['sha256']:
            invalid.append(record['path'])
    if invalid:
        return {'found': False, 'reason': 'Saved files changed or are missing.', 'invalidFiles': invalid}
    return {'found': True, 'manifestPath': str(path), 'paperKey': identity['paperKey'],
            'noteMarkdownPath': manifest['note']['path'], 'chatMarkdownPath': manifest['chat']['path'],
            'assets': [r['path'] for r in manifest['assets']], 'pending': manifest['pending'],
            'noteSha256': manifest['note']['sha256'], 'pdfSha256': manifest['pdf']['sha256']}


if __name__ == '__main__':
    try:
        command = {'find': find, 'publish': publish}[sys.argv[1]]
        print(json.dumps(command(read(sys.argv[2])), ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False)); sys.exit(1)
