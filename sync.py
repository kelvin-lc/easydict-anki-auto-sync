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
RICH_FIELDS = ['Phonetic', 'Definition', 'Forms', 'Examples', 'Related', 'Source', 'Audio']
CSS = '''
.card { font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif;
 font-size: 20px; line-height: 1.65; text-align: left; color: #242b32; background: #faf9f6; margin: 0; padding: 28px 22px; }
.entry { max-width: 660px; margin: 0 auto; overflow-wrap: anywhere; }
.word { font-family: Georgia, "Times New Roman", serif; font-size: 44px; line-height: 1.18; font-weight: 600; margin: 12px 0; }
.phonetic { color: #596570; font-size: 17px; margin: 8px 0 22px; }
.phonetic span { display: inline-block; margin-right: 20px; }
#answer { border: 0; border-top: 1px solid #d6d9d6; margin: 24px 0; }
.sense { margin: 10px 0; }
.pos { font-size: 16px; color: #35685f; margin-right: 10px; font-style: italic; }
h2 { font-size: 14px; font-weight: 600; color: #596570; margin: 27px 0 8px; }
.forms, .related { font-size: 17px; }
.example { margin: 12px 0 18px; }
.translation { font-size: 17px; color: #596570; margin-top: 4px; }
.source { font-size: 12px; color: #596570; margin-top: 30px; }
.source a { color: inherit; text-underline-offset: 3px; }
::selection { background: #cde4da; color: #152e27; }
a:focus-visible { outline: 2px solid #35685f; outline-offset: 3px; }
.nightMode.card { color: #e5e8e6; background: #202524; }
.nightMode .phonetic, .nightMode h2, .nightMode .translation, .nightMode .source { color: #b3bfba; }
.nightMode .pos { color: #9fd2bf; }
.nightMode #answer { border-color: #4c5852; }
@media (max-width: 480px) { .card { padding: 20px 16px; font-size: 19px; } .word { font-size: 36px; } }
'''
FRONT = '<div class="entry"><div class="word">{{Word}} {{Audio}}</div>{{#Phonetic}}<div class="phonetic">{{Phonetic}}</div>{{/Phonetic}}</div>'
BACK = '''{{FrontSide}}<div class="entry"><hr id="answer">
{{#Definition}}<div class="definitions">{{Definition}}</div>{{/Definition}}
{{^Definition}}<div class="definitions">{{Meaning}}</div>{{/Definition}}
{{#Forms}}<h2>词形变化</h2><div class="forms">{{Forms}}</div>{{/Forms}}
{{#Examples}}<h2>例句</h2>{{Examples}}{{/Examples}}
{{#Related}}<h2>近义词</h2><div class="related">{{Related}}</div>{{/Related}}
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
    definitions = ''.join(f'<div class="sense"><span class="pos">{esc(item.get("pos", ""))}</span>{esc(item["tran"])}</div>'
                          for item in entry['trs'] if item.get('tran'))
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
    return dict(Phonetic=phonetic, Definition=definitions, Forms=forms,
                Examples=''.join(examples), Related=related,
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


def make_audio(word):
    """Synthesize once locally; cache a small, portable MP3 for AnkiWeb."""
    if not re.fullmatch(r"[a-z]+(?:[-'][a-z]+)*", word):
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
    for name, definition in [('rich_json', 'TEXT'), ('enriched', 'INTEGER NOT NULL DEFAULT 0'), ('retry_at', 'REAL NOT NULL DEFAULT 0'), ('audio_done', 'INTEGER NOT NULL DEFAULT 0'), ('audio_retry_at', 'REAL NOT NULL DEFAULT 0')]:
        if name not in columns:
            db.execute(f'ALTER TABLE words ADD COLUMN {name} {definition}')
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
        if record.get('queryFromLanguage') != 'English' or not re.fullmatch(r"[a-z]+(?:[-'][a-z]+)*", word):
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


def sync(db, now, call=api):
    pending = db.execute('SELECT word, meaning FROM words WHERE note_id IS NULL AND meaning != ? AND seen <= ?', ('', now - 15)).fetchall()
    needs_enrichment = db.execute('SELECT 1 FROM words WHERE note_id IS NOT NULL AND enriched=0 AND retry_at<=? LIMIT 1', (now,)).fetchone()
    needs_audio = db.execute('SELECT 1 FROM words WHERE note_id IS NOT NULL AND audio_done=0 AND audio_retry_at<=? LIMIT 1', (now,)).fetchone()
    if not pending and not needs_enrichment and not needs_audio:
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
    elif 'Audio' not in call('modelFieldNames', modelName=MODEL):
        setup_model(call)
    count = 0
    for word, meaning in pending:
        ids = call('findNotes', query=f'note:"{MODEL}" Word:{word}')
        existing = call('notesInfo', notes=ids) if ids else []
        exact = [n['noteId'] for n in existing if n['fields']['Word']['value'].strip().lower() == word]
        if exact:
            note_id = exact[0]
        else:
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
            ((audio_done=0 AND audio_retry_at<=?) OR (enriched=0 AND retry_at<=?))
            LIMIT 1""", (now, now)).fetchone():
        attach_audio(db, now, call)
        enrich(db, now, call)
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
