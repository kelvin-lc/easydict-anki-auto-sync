#!/usr/bin/env python3
"""Local Easydict history -> durable SQLite queue -> AnkiConnect."""
import argparse
import fcntl
import html
import hashlib
import json
import logging
import os
import pathlib
import plistlib
import re
import sqlite3
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import urllib.parse

ROOT = pathlib.Path(os.environ.get('EASYDICT_ANKI_DATA_DIR',
                    pathlib.Path.home() / 'Library/Application Support/EasydictAnkiSync'))
DECK = os.environ.get('EASYDICT_ANKI_DECK', 'Easydict 生词')
MODEL = 'Easydict English-Chinese'
PROFILE = os.environ.get('EASYDICT_ANKI_PROFILE', 'User 1')
POLL_SECONDS = int(os.environ.get('EASYDICT_ANKI_POLL_SECONDS', '300'))
VOICE = os.environ.get('EASYDICT_ANKI_VOICE', 'Samantha')
FFMPEG = os.environ.get('EASYDICT_ANKI_FFMPEG') or shutil.which('ffmpeg')
if POLL_SECONDS < 60:
    raise ValueError('EASYDICT_ANKI_POLL_SECONDS must be at least 60')
RICH_FIELDS = ['Phonetic', 'Definition', 'Forms', 'Examples', 'Related', 'Source', 'Audio',
               'Family', 'Roots', 'Mnemonic']
WORD = re.compile(r"[a-z]+(?:[-'][a-z]+)*")
CSS = '''.card {
  --paper: #faf9f6;
  --ink: #242f2b;
  --muted: #5b6962;
  --accent: #35685f;
  --rule: #d8dfd9;
  --wash: #edf2ed;
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif;
  font-size: 20px;
  line-height: 1.75;
  text-align: left;
  color: var(--ink);
  background: var(--paper);
  margin: 0;
  padding: 40px 28px 64px;
  -webkit-font-smoothing: antialiased;
}
.entry { max-width: 680px; margin: 0 auto; overflow-wrap: anywhere; }
.word {
  font-family: Georgia, "Times New Roman", serif;
  font-size: clamp(36px, 7vw, 56px);
  font-weight: 500;
  line-height: 1.2;
  letter-spacing: -0.025em;
  margin: 12px 0 16px;
}
.phonetic { color: var(--muted); font-size: 16px; line-height: 1.8; }
.phonetic span { display: inline-block; margin-right: 22px; }
#answer { border: 0; border-top: 1px solid var(--rule); margin: 28px 0; }
.sense { margin: 14px 0; }
.pos { display: inline-block; font-size: 16px; color: var(--accent); font-style: italic; margin-right: 12px; }
h2 { color: var(--muted); font-size: 14px; font-weight: 600; margin: 34px 0 12px; }
.example { margin: 0 0 22px; }
.example b { color: var(--accent); font-weight: 650; }
.translation { color: var(--muted); font-size: 17px; margin-top: 6px; }
.forms, .related, .family { font-size: 17px; line-height: 1.9; margin: 12px 0 20px; }
.memory { margin: 22px 0 6px; padding: 10px 16px; border-left: 3px solid var(--accent);
  background: var(--wash); border-radius: 0 8px 8px 0; font-size: 17px; line-height: 1.7; }
.memory div + div { margin-top: 6px; }
.label { display: inline-block; min-width: 2.6em; color: var(--accent); font-size: 14px; font-weight: 600; }
.extra { border-top: 1px solid var(--rule); margin-top: 26px; padding-top: 8px; }
.extra + .extra { margin-top: 0; }
summary { color: var(--muted); font-size: 15px; padding: 10px 0; cursor: pointer; }
summary:hover { color: var(--accent); }
.source { font-size: 12px; color: var(--muted); margin-top: 32px; }
a { color: var(--accent); text-underline-offset: 4px; }
.source a { color: inherit; }
.replay-button { display: inline-flex; vertical-align: middle; margin-left: 6px; padding: 6px; }
.replay-button svg { width: 36px; height: 36px; }
.replay-button svg circle { fill: var(--wash); stroke: var(--rule); }
.replay-button svg path { fill: var(--accent); }
.replay-button:hover svg circle { stroke: var(--accent); }
a:focus-visible, summary:focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; border-radius: 4px; }
::selection { background: #cde4da; color: #152e27; }
.nightMode.card, .night_mode.card {
  --paper: #202724;
  --ink: #e8ede9;
  --muted: #b2c0b7;
  --accent: #a2d2bf;
  --rule: #44564b;
  --wash: #2b3830;
}
@media (max-width: 480px) {
  .card { padding: 24px 20px 40px; font-size: 18px; }
  .phonetic { font-size: 15px; }
  .translation, .forms, .related, .family, .memory { font-size: 16px; }
  #answer { margin: 24px 0; }
}
'''
FRONT = '<div class="entry"><div class="word">{{Word}} {{Audio}}</div>{{#Phonetic}}<div class="phonetic">{{Phonetic}}</div>{{/Phonetic}}</div>'
BACK = '''{{FrontSide}}<div class="entry"><hr id="answer">
{{#Definition}}<div class="definitions">{{Definition}}</div>{{/Definition}}
{{^Definition}}<div class="definitions">{{Meaning}}</div>{{/Definition}}
{{#Roots}}<div class="memory"><div><span class="label">词根</span>{{Roots}}</div>{{#Mnemonic}}<div><span class="label">助记</span>{{Mnemonic}}</div>{{/Mnemonic}}</div>{{/Roots}}
{{#Examples}}<h2>例句</h2>{{Examples}}{{/Examples}}
{{#Forms}}<details class="extra"><summary>词形变化</summary><div class="forms">{{Forms}}</div></details>{{/Forms}}
{{#Family}}<details class="extra"><summary>同根词</summary><div class="family">{{Family}}</div></details>{{/Family}}
{{#Related}}<details class="extra"><summary>近义词</summary><div class="related">{{Related}}</div></details>{{/Related}}
{{#Source}}<div class="source">{{Source}}</div>{{/Source}}</div>'''


def dictionary_fields(word):
    """Use the Youdao V4 request/field mapping used by Easydict (GPL-3.0).

    Reference: tisfeng/Easydict YoudaoService+Dict.swift, EZQueryResult+DictV4.swift;
    official Anki field organization: PR #1241. See THIRD_PARTY.md.
    """
    salt = hashlib.md5((word + 'webdict').encode()).hexdigest()
    t = len(word + 'webdict') % 10
    sign = hashlib.md5(f'web{word}{t}Mk6hqtUp33DGGtoS63tTJbMUYjRrG1Lu{salt}'.encode()).hexdigest()
    params = dict(q=word, le='en', client='web', t=t, sign=sign, keyfrom='webdict')
    request = urllib.request.Request('https://dict.youdao.com/jsonapi_s?doctype=json&jsonversion=4',
                                    data=urllib.parse.urlencode(params).encode())
    with urllib.request.urlopen(request, timeout=12) as response:
        data = json.load(response)
    return render_dictionary(data, word)


def render_dictionary(data, word):
    entry = (data.get('ec') or {}).get('word') or {}
    if not entry.get('trs'):
        raise ValueError('No dictionary definitions')
    returned = entry.get('return-phrase', word).strip().lower()
    if returned != word:
        raise ValueError('Dictionary returned a different word')
    esc = lambda s: html.escape(str(s), quote=True)
    phonetic = ''.join(f'<span>{label} /{esc(entry[key])}/</span>'
                       for label, key in [('英', 'ukphone'), ('美', 'usphone')] if entry.get(key))
    # Keep a card scannable: skip personal-name senses and show four glosses per part of speech.
    definitions = ''.join(f'<div class="sense"><span class="pos">{esc(item.get("pos", ""))}</span>'
                          f'{esc("；".join(item["tran"].split("；")[:4]))}</div>'
                          for item in entry['trs'] if item.get('tran') and not item['tran'].startswith('【名】'))
    forms = '<br>'.join(f'{esc(item["wf"].get("name", ""))}：{esc(item["wf"]["value"])}'
                       for item in entry.get('wfs', []) if (item.get('wf') or {}).get('value'))
    examples = []
    for item in (data.get('blng_sents_part') or {}).get('sentence-pair', [])[:2]:
        if item.get('sentence') and item.get('sentence-translation'):
            english = esc(item['sentence'])
            english = re.sub(r'(?i)\b' + re.escape(word) + r'\b', lambda m: '<b>' + m[0] + '</b>', english)
            examples.append(f'<div class="example"><div>{english}</div><div class="translation">{esc(item["sentence-translation"])}</div></div>')
    related = '<br>'.join(f'{esc(item.get("pos", ""))} {esc(", ".join(item.get("ws", [])))} — {esc(item.get("tran", ""))}'
                         for item in (data.get('syno') or {}).get('synos', []) if item.get('ws'))
    rel = data.get('rel_word') or {}
    family = [f'<span class="pos">{esc(group["rel"].get("pos", ""))}</span>{esc(item["word"])} '
              f'<span class="translation">{esc(item.get("tran", "").split("；")[0])}</span>'
              for group in rel.get('rels', []) if group.get('rel')
              for item in group['rel'].get('words', []) if item.get('word')][:6]
    if family and rel.get('stem') and rel['stem'] != word:
        family.insert(0, f'词干：{esc(rel["stem"])}')
    return dict(Phonetic=phonetic, Definition=definitions, Forms=forms,
                Examples=''.join(examples), Related=related, Family='<br>'.join(family),
                Source=f'<a href="https://dict.youdao.com/result?word={urllib.parse.quote(word)}&lang=en">有道词典</a>')


def setup_model(call= None):
    call = call or api
    names = call('modelFieldNames', modelName=MODEL)
    for name in RICH_FIELDS:
        if name not in names:
            call('modelFieldAdd', modelName=MODEL, fieldName=name)
    call('updateModelStyling', model={'name': MODEL, 'css': CSS})
    call('updateModelTemplates', model={'name': MODEL, 'templates': {'英文 → 中文': {'Front': FRONT, 'Back': BACK}}})


def enrich(db, now, call=None, fetch=dictionary_fields):
    call = call or api
    rows = db.execute('SELECT word,note_id,rich_json FROM words WHERE note_id IS NOT NULL AND enriched=0 AND retry_at<=? LIMIT 3', (now,)).fetchall()
    for word, note_id, cached in rows:
        try:
            notes = call('notesInfo', notes=[note_id])
            if not notes or not notes[0] or not notes[0].get('fields'):
                db.execute('UPDATE words SET enriched=1 WHERE word=?', (word,))
                db.commit()
                continue
            fields = json.loads(cached) if cached else fetch(word)
            db.execute('UPDATE words SET rich_json=? WHERE word=?', (json.dumps(fields, ensure_ascii=False), word))
            db.commit()
            call('updateNoteFields', note={'id': note_id, 'fields': fields})
            db.execute('UPDATE words SET enriched=1 WHERE word=?', (word,))
            logging.info('Enriched note %s', note_id)
        except AnkiUnavailable:
            raise
        except Exception as exc:
            db.execute('UPDATE words SET retry_at=? WHERE word=?', (now + 3600, word))
            logging.warning('Dictionary enrichment deferred for note %s: %s', note_id, exc)
        db.commit()


MEMORY_PROMPT = """你为中文母语、注意力容易分散的英语学习者制作单词卡的记忆提示。只输出一个 JSON 对象，不要代码块，只含三个键：
"lemma"：仅当该词只是另一个词的屈折变化（复数、第三人称单数、-ing、过去式、过去分词、比较级、最高级），且自身没有独立的常用词义时，填原形小写；否则填该词本身。
"roots"：词素拆解，格式如「re-(回) + serve(保存) → 留着备用」。不可拆分的词，用一句话说明来源语言、原词和原义。不确定时写通行说法，不要编造。不超过 40 个汉字。
"mnemonic"：一句有画面感的助记，把词形或读音与核心词义连起来，不要冒充词源。不超过 30 个汉字。"""


def llm_config():
    """Reuse the OpenAI-compatible service configured in Easydict; env vars override."""
    def pref(name):
        result = subprocess.run(['/usr/bin/defaults', 'read', 'com.izual.Easydict', name],
                                capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else ''
    config = {key: os.environ.get('EASYDICT_ANKI_LLM_' + key.upper()) or pref(name)
              for key, name in [('url', 'EZDeepSeekEndPointKey'), ('key', 'EZDeepSeekAPIKey'),
                                ('model', 'EZDeepSeekModelKey')]}
    return config if all(config.values()) else None


def clip(text, limit):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def parse_memory(content, word):
    match = re.search(r'\{.*\}', re.sub(r'(?s)<think>.*?</think>', '', content), re.S)
    data = json.loads(match[0]) if match else {}
    roots, mnemonic = clip(data.get('roots'), 60), clip(data.get('mnemonic'), 45)
    if not roots and not mnemonic:
        raise ValueError('LLM returned no memory hints')
    lemma = str(data.get('lemma') or word).strip().lower()
    return dict(lemma=lemma if WORD.fullmatch(lemma) else word,
                Roots=html.escape(roots), Mnemonic=html.escape(mnemonic))


def memory_fields(word, gloss, config):
    body = {'model': config['model'], 'temperature': 0.3, 'messages': [
        {'role': 'system', 'content': MEMORY_PROMPT},
        {'role': 'user', 'content': f'单词：{word}\n释义参考：{gloss}'}]}
    request = urllib.request.Request(config['url'], data=json.dumps(body).encode(), headers={
        'Content-Type': 'application/json', 'Authorization': 'Bearer ' + config['key']})
    with urllib.request.urlopen(request, timeout=60) as response:
        content = json.load(response)['choices'][0]['message']['content']
    return parse_memory(content, word)


def find_note(call, word):
    ids = call('findNotes', query=f'note:"{MODEL}" Word:{word}')
    existing = call('notesInfo', notes=ids) if ids else []
    return next((n['noteId'] for n in existing
                 if n['fields']['Word']['value'].strip().lower() == word), None)


def merge(db, call, word, note_id, lemma):
    """Fold an inflected form (reserving) into its lemma (reserve)."""
    db.execute('INSERT OR REPLACE INTO aliases(word,lemma) VALUES (?,?)', (word, lemma))
    known = db.execute('SELECT note_id FROM words WHERE word=?', (lemma,)).fetchone()
    target = known[0] if known and known[0] else find_note(call, lemma)
    if target:
        # The lemma already has a card: drop the duplicate inflected card.
        call('deleteNotes', notes=[note_id])
    else:
        call('updateNoteFields', note={'id': note_id, 'fields': {'Word': lemma, 'Audio': ''}})
        target = note_id
    if known:
        db.execute('DELETE FROM words WHERE word=?', (word,))
        db.execute('UPDATE words SET note_id=? WHERE word=?', (target, lemma))
    else:
        db.execute('UPDATE words SET word=?, note_id=?, rich_json=NULL, enriched=0, retry_at=0, '
                   'audio_done=0, audio_retry_at=0, llm_done=0, llm_retry_at=0 WHERE word=?',
                   (lemma, target, word))
    logging.info('Merged %s into %s', word, lemma)


def memorize(db, now, config, call=None, generate=memory_fields):
    call = call or api
    rows = db.execute('SELECT word,note_id,meaning,rich_json FROM words WHERE note_id IS NOT NULL AND llm_done=0 AND llm_retry_at<=? LIMIT 3', (now,)).fetchall()
    for word, note_id, meaning, cached in rows:
        try:
            notes = call('notesInfo', notes=[note_id])
            if notes and notes[0] and notes[0].get('fields'):
                gloss = re.sub(r'<[^>]+>', ' ', (json.loads(cached) if cached else {}).get('Definition', '')) or meaning
                fields = generate(word, clip(html.unescape(gloss), 200), config)
                lemma = fields.pop('lemma')
                if lemma != word:
                    merge(db, call, word, note_id, lemma)
                    db.commit()
                    continue
                call('updateNoteFields', note={'id': note_id, 'fields': fields})
                logging.info('Added memory hints to note %s', note_id)
            db.execute('UPDATE words SET llm_done=1 WHERE word=?', (word,))
        except AnkiUnavailable:
            raise
        except Exception as exc:
            db.execute('UPDATE words SET llm_retry_at=? WHERE word=?', (now + 3600, word))
            logging.warning('Memory hints deferred for note %s: %s', note_id, exc)
        db.commit()


def make_audio(word):
    """Synthesize once locally; cache a small, portable MP3 for AnkiWeb."""
    if not WORD.fullmatch(word):
        raise ValueError('Invalid audio word')
    directory = ROOT / 'audio'
    directory.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256((VOICE + '-mp3-v1:' + word).encode()).hexdigest()[:24]
    target = directory / f'easydict_{digest}.mp3'
    if target.exists() and target.stat().st_size > 100:
        return target
    with tempfile.TemporaryDirectory(dir=directory) as tmp:
        aiff = pathlib.Path(tmp) / 'speech.aiff'
        mp3 = pathlib.Path(tmp) / 'speech.mp3'
        if not FFMPEG:
            raise RuntimeError('ffmpeg is required to create MP3 audio')
        subprocess.run(['/usr/bin/say', '-v', VOICE, '-r', '165', '-o', str(aiff), word],
                       check=True, capture_output=True, timeout=30)
        subprocess.run([FFMPEG, '-nostdin', '-v', 'error', '-i', str(aiff),
                        '-ac', '1', '-ar', '22050', '-codec:a', 'libmp3lame', '-b:a', '48k',
                        '-threads', '1', str(mp3)], check=True, capture_output=True, timeout=30)
        if mp3.stat().st_size < 100:
            raise ValueError('Audio generation returned an empty file')
        mp3.replace(target)
    return target


def attach_audio(db, now, call=None, generate=make_audio):
    call = call or api
    rows = db.execute('SELECT word,note_id FROM words WHERE note_id IS NOT NULL AND audio_done=0 AND audio_retry_at<=? LIMIT 3', (now,)).fetchall()
    for word, note_id in rows:
        try:
            notes = call('notesInfo', notes=[note_id])
            if notes and notes[0] and notes[0].get('fields'):
                existing = notes[0]['fields'].get('Audio', {}).get('value', '')
                if not existing:
                    path = generate(word)
                    filename = call('storeMediaFile', filename=path.name, path=str(path))
                    if not filename or any(c in filename for c in '[]\r\n'):
                        raise ValueError('Invalid stored media filename')
                    call('updateNoteFields', note={'id': note_id, 'fields': {'Audio': f'[sound:{filename}]'}})
            db.execute('UPDATE words SET audio_done=1 WHERE word=?', (word,))
        except AnkiUnavailable:
            raise
        except Exception as exc:
            db.execute('UPDATE words SET audio_retry_at=? WHERE word=?', (now + 3600, word))
            logging.warning('Audio deferred for note %s: %s', note_id, exc)
        db.commit()


def connect(path):
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE IF NOT EXISTS words (word TEXT PRIMARY KEY, meaning TEXT NOT NULL, seen REAL NOT NULL, note_id INTEGER)')
    columns = {row[1] for row in db.execute('PRAGMA table_info(words)')}
    for name, definition in [('rich_json', 'TEXT'), ('enriched', 'INTEGER NOT NULL DEFAULT 0'), ('retry_at', 'REAL NOT NULL DEFAULT 0'), ('audio_done', 'INTEGER NOT NULL DEFAULT 0'), ('audio_retry_at', 'REAL NOT NULL DEFAULT 0'), ('llm_done', 'INTEGER NOT NULL DEFAULT 0'), ('llm_retry_at', 'REAL NOT NULL DEFAULT 0')]:
        if name not in columns:
            db.execute(f'ALTER TABLE words ADD COLUMN {name} {definition}')
    db.execute('CREATE TABLE IF NOT EXISTS aliases (word TEXT PRIMARY KEY, lemma TEXT NOT NULL)')
    if db.execute('PRAGMA user_version').fetchone()[0] < 2:
        # Version 2 adds the word family and shorter definitions; refetch cached entries once.
        db.execute('UPDATE words SET rich_json=NULL, enriched=0, retry_at=0')
        db.execute('PRAGMA user_version=2')
    db.commit()
    return db


def read_history():
    raw = subprocess.run(['/usr/bin/defaults', 'read', 'com.izual.Easydict',
                          'EZConfiguration_kQueryHistory'], capture_output=True, timeout=5)
    if raw.returncode:
        raise RuntimeError('Easydict history unavailable')
    xml = subprocess.run(['/usr/bin/plutil', '-convert', 'xml1', '-o', '-', '--', '-'],
                         input=raw.stdout, capture_output=True, check=True, timeout=5).stdout
    return [json.loads(item) for item in plistlib.loads(xml)]


def collect(db, records, now):
    for record in records:
        word = record.get('queryText', '').strip().replace('’', "'").lower()
        if record.get('queryFromLanguage') != 'English' or not WORD.fullmatch(word):
            continue
        if db.execute('SELECT 1 FROM aliases WHERE word=?', (word,)).fetchone():
            continue
        meaning = (record.get('translatedResult') or '').strip()
        if not re.search(r'[\u3400-\u9fff]', meaning):
            meaning = ''
        old = db.execute('SELECT meaning FROM words WHERE word=?', (word,)).fetchone()
        if old is None:
            db.execute('INSERT INTO words (word,meaning,seen,note_id) VALUES (?, ?, ?, NULL)', (word, meaning, now))
        elif meaning and not old[0]:
            db.execute('UPDATE words SET meaning=?, seen=? WHERE word=?', (meaning, now, word))
    db.commit()


class AnkiUnavailable(ConnectionError):
    """Anki closed or restarted; keep queued work eligible for the next scan."""


def api(action, **params):
    payload = json.dumps({'action': action, 'version': 6, 'params': params}).encode()
    request = urllib.request.Request('http://127.0.0.1:8765', data=payload,
                                     headers={'Content-Type': 'application/json'})
    # Never route local vocabulary through an HTTP proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=5) as result:
            response = json.load(result)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise AnkiUnavailable(str(exc)) from exc
    if response.get('error'):
        raise RuntimeError(response['error'])
    return response['result']


def sync(db, now, call=api, config=llm_config):
    config = config()
    pending = db.execute('SELECT word, meaning FROM words WHERE note_id IS NULL AND meaning != ? AND seen <= ?', ('', now - 15)).fetchall()
    needs_enrichment = db.execute('SELECT 1 FROM words WHERE note_id IS NOT NULL AND enriched=0 AND retry_at<=? LIMIT 1', (now,)).fetchone()
    needs_audio = db.execute('SELECT 1 FROM words WHERE note_id IS NOT NULL AND audio_done=0 AND audio_retry_at<=? LIMIT 1', (now,)).fetchone()
    needs_memory = config and db.execute('SELECT 1 FROM words WHERE note_id IS NOT NULL AND llm_done=0 AND llm_retry_at<=? LIMIT 1', (now,)).fetchone()
    if not pending and not needs_enrichment and not needs_audio and not needs_memory:
        return 0
    if call('getActiveProfile') != PROFILE:
        raise RuntimeError(f'Waiting for Anki profile {PROFILE}')
    call('createDeck', deck=DECK)
    if MODEL not in call('modelNames'):
        call('createModel', modelName=MODEL, inOrderFields=['Word', 'Meaning'],
             css='.card { font-family: -apple-system, Arial; font-size: 28px; text-align: center; } .meaning { font-size: 23px; line-height: 1.6; }',
             cardTemplates=[{'Name': '英文 → 中文', 'Front': '{{Word}}',
                             'Back': '{{FrontSide}}<hr id="answer"><div class="meaning">{{Meaning}}</div>'}])
        setup_model(call)
    elif set(RICH_FIELDS) - set(call('modelFieldNames', modelName=MODEL)):
        setup_model(call)
    count = 0
    for word, meaning in pending:
        note_id = find_note(call, word)
        if not note_id:
            note_id = call('addNote', note={'deckName': DECK, 'modelName': MODEL,
                'fields': {'Word': html.escape(word, quote=False), 'Meaning': html.escape(meaning).replace('\n', '<br>')},
                'options': {'allowDuplicate': False}, 'tags': ['Easydict', 'auto-import']})
            if not note_id:
                raise RuntimeError('Anki returned no note id')
            count += 1
        db.execute('UPDATE words SET note_id=? WHERE word=?', (note_id, word))
        db.commit()
    # Scan history every five minutes, but finish ready work in this scan.
    # Each batch remains sequential; failed items get a retry time and leave it.
    while db.execute("""SELECT 1 FROM words WHERE note_id IS NOT NULL AND
            ((audio_done=0 AND audio_retry_at<=?) OR (enriched=0 AND retry_at<=?)
             OR (? AND llm_done=0 AND llm_retry_at<=?))
            LIMIT 1""", (now, now, bool(config), now)).fetchone():
        attach_audio(db, now, call)
        enrich(db, now, call)
        if config:
            memorize(db, now, config, call)
        time.sleep(0.3)
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    lock = (ROOT / 'sync.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    logging.basicConfig(filename=ROOT / 'sync.log', level=logging.INFO,
                        format='%(asctime)s %(message)s')
    db = connect(ROOT / 'queue.sqlite3')
    last_error = None
    while True:
        try:
            now = time.time()
            collect(db, read_history(), now)
            count = sync(db, now)
            if count:
                logging.info('Imported %d notes', count)
            if last_error:
                logging.info('Connection recovered')
            last_error = None
        except Exception as exc:
            error = str(exc)
            if error != last_error:
                logging.warning('%s', error)
                last_error = error
        if args.once:
            break
        time.sleep(POLL_SECONDS)


if __name__ == '__main__':
    main()
