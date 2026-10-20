import io
import pathlib
import plistlib
import subprocess
import urllib.error
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import sync


class SyncTests(unittest.TestCase):
    def test_collect_filters_and_deduplicates_history(self):
        with tempfile.TemporaryDirectory() as directory:
            db = sync.connect(pathlib.Path(directory) / 'queue.sqlite3')
            records = [
                {'queryText': 'Gas', 'queryFromLanguage': 'English', 'translatedResult': '气体'},
                {'queryText': 'gas', 'queryFromLanguage': 'English', 'translatedResult': '气体'},
                {'queryText': 'participant User as', 'queryFromLanguage': 'English', 'translatedResult': '参加'},
                {'queryText': 'bonjour', 'queryFromLanguage': 'French', 'translatedResult': '你好'},
            ]
            sync.collect(db, records, 100)
            self.assertEqual(db.execute('SELECT word,meaning FROM words').fetchall(), [('gas', '气体')])

    def test_audio_retries_then_attaches_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory)
            db = sync.connect(path / 'queue.sqlite3')
            db.execute('INSERT INTO words(word,meaning,seen,note_id) VALUES (?,?,?,?)',
                       ('gas', '气体', 1, 123))
            db.commit()
            calls = []

            def anki(action, **params):
                calls.append((action, params))
                if action == 'notesInfo':
                    return [{'fields': {'Audio': {'value': ''}}}]
                if action == 'storeMediaFile':
                    return params['filename']

            def fail(_word):
                raise RuntimeError('temporary audio failure')

            sync.attach_audio(db, 100, anki, fail)
            self.assertEqual(db.execute('SELECT audio_done,audio_retry_at FROM words').fetchone(),
                             (0, 3700))
            sync.attach_audio(db, 3701, anki, lambda _word: path / 'gas.mp3')
            self.assertEqual(db.execute('SELECT audio_done FROM words').fetchone(), (1,))
            self.assertIn(('updateNoteFields', {'note': {'id': 123,
                'fields': {'Audio': '[sound:gas.mp3]'}}}), calls)
            count = len(calls)
            sync.attach_audio(db, 4000, anki, fail)
            self.assertEqual(len(calls), count)

    def test_existing_queue_migrates_without_losing_cards(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'queue.sqlite3'
            db = sqlite3.connect(path)
            db.execute('CREATE TABLE words(word TEXT PRIMARY KEY, meaning TEXT NOT NULL, seen REAL NOT NULL, note_id INTEGER)')
            db.execute('INSERT INTO words VALUES (?,?,?,?)', ('gas', '气体', 1, 123))
            db.commit()
            db.close()
            migrated = sync.connect(path)
            self.assertEqual(migrated.execute('SELECT word,note_id,audio_done FROM words').fetchone(),
                             ('gas', 123, 0))
            migrated.execute("UPDATE words SET enriched=1, rich_json='{}'")
            migrated.commit()
            migrated.close()
            # The one-time refetch for the word family does not repeat.
            self.assertEqual(sync.connect(path).execute('SELECT enriched FROM words').fetchone(), (1,))


class BacklogTests(unittest.TestCase):
    def test_one_scan_finishes_more_than_three_queued_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            db = sync.connect(pathlib.Path(directory) / 'queue.sqlite3')
            for i in range(7):
                db.execute('INSERT INTO words(word,meaning,seen,note_id) VALUES (?,?,?,?)',
                           ('word'+str(i), '释义', 1, 100+i))
            db.commit()
            def anki(action, **params):
                if action == 'getActiveProfile': return sync.PROFILE
                if action == 'modelNames': return [sync.MODEL]
                if action == 'modelFieldNames': return sync.RICH_FIELDS
            def batch(db, now, call, **kwargs):
                db.execute('UPDATE words SET audio_done=1,enriched=1 WHERE note_id IN (SELECT note_id FROM words WHERE enriched=0 LIMIT 3)')
                db.commit()
            with patch.object(sync, 'attach_audio', side_effect=batch), patch.object(sync, 'enrich'):
                sync.sync(db, 100, anki, config=lambda: None)
            self.assertEqual(db.execute('SELECT count(*) FROM words WHERE enriched=0 OR audio_done=0').fetchone()[0], 0)

    def test_anki_disconnect_does_not_delay_work_for_an_hour(self):
        with tempfile.TemporaryDirectory() as directory:
            db = sync.connect(pathlib.Path(directory) / 'queue.sqlite3')
            db.execute('INSERT INTO words(word,meaning,seen,note_id) VALUES (?,?,?,?)',
                       ('gas', '气体', 1, 123))
            db.commit()
            def offline(action, **params):
                raise sync.AnkiUnavailable('connection refused')
            for operation in (sync.attach_audio, sync.enrich):
                with self.assertRaises(sync.AnkiUnavailable):
                    operation(db, 100, offline)
            with self.assertRaises(sync.AnkiUnavailable):
                sync.memorize(db, 100, {}, offline)
            self.assertEqual(db.execute('SELECT enriched,audio_done,retry_at,audio_retry_at FROM words').fetchone(),
                             (0, 0, 0, 0))

def queue(directory, *rows):
    db = sync.connect(pathlib.Path(directory) / 'queue.sqlite3')
    db.executemany('INSERT INTO words(word,meaning,seen,note_id,enriched,audio_done) VALUES (?,?,1,?,1,1)', rows)
    db.commit()
    return db


class MemoryTests(unittest.TestCase):
    def test_parse_memory_cleans_model_output(self):
        content = '<think>x</think>```json\n{"lemma": "Reserve", "roots": "re-(回) + serve(保存)", "mnemonic": "' + '长' * 80 + '", "extra": 1}\n```'
        fields = sync.parse_memory(content, 'reserving')
        self.assertEqual(fields['lemma'], 'reserve')
        self.assertEqual(fields['Roots'], 're-(回) + serve(保存)')
        self.assertEqual(len(fields['Mnemonic']), 45)
        self.assertEqual(sync.parse_memory('{"lemma": "a b", "roots": "<b>"}', 'ab')['lemma'], 'ab')
        self.assertEqual(sync.parse_memory('{"roots": "<b>"}', 'ab')['Roots'], '&lt;b&gt;')
        with self.assertRaises(ValueError):
            sync.parse_memory('not json', 'ab')

    def test_memorize_writes_hints_or_retries_later(self):
        with tempfile.TemporaryDirectory() as directory:
            db = queue(directory, ('deck', '甲板', 7))
            calls = []
            def anki(action, **params):
                calls.append((action, params))
                if action == 'notesInfo':
                    return [{'fields': {'Word': {'value': 'deck'}}}]
            def fail(*_args):
                raise RuntimeError('timeout')
            sync.memorize(db, 100, {}, anki, fail)
            self.assertEqual(db.execute('SELECT llm_done,llm_retry_at FROM words').fetchone(), (0, 3700))
            hints = lambda word, gloss, config: dict(lemma=word, Roots='dec(覆盖)', Mnemonic='甲板上摊牌')
            sync.memorize(db, 3700, {}, anki, hints)
            self.assertIn(('updateNoteFields', {'note': {'id': 7, 'fields': {'Roots': 'dec(覆盖)', 'Mnemonic': '甲板上摊牌'}}}), calls)
            self.assertEqual(db.execute('SELECT llm_done FROM words').fetchone(), (1,))

    def test_inflected_card_is_renamed_to_lemma_and_not_reimported(self):
        with tempfile.TemporaryDirectory() as directory:
            db = queue(directory, ('reserving', '保留', 5))
            calls = []
            def anki(action, **params):
                calls.append((action, params))
                if action == 'notesInfo':
                    return [{'noteId': 5, 'fields': {'Word': {'value': 'reserving'}}}]
                if action == 'findNotes':
                    return []
            sync.memorize(db, 100, {}, anki, lambda *a: dict(lemma='reserve', Roots='r', Mnemonic='m'))
            self.assertIn(('updateNoteFields', {'note': {'id': 5, 'fields': {'Word': 'reserve', 'Audio': ''}}}), calls)
            self.assertEqual(db.execute('SELECT word,note_id,enriched,audio_done,llm_done FROM words').fetchall(),
                             [('reserve', 5, 0, 0, 0)])
            sync.collect(db, [{'queryText': 'reserving', 'queryFromLanguage': 'English', 'translatedResult': '保留'}], 200)
            self.assertEqual(db.execute('SELECT count(*) FROM words').fetchone(), (1,))

    def test_inflected_duplicate_of_existing_lemma_is_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            db = queue(directory, ('reserve', '保留', 9), ('reserving', '保留', 5))
            calls = []
            def anki(action, **params):
                calls.append((action, params))
                if action == 'notesInfo':
                    return [{'noteId': 5, 'fields': {'Word': {'value': 'x'}}}]
            hints = lambda word, *a: dict(lemma='reserve', Roots='r', Mnemonic='m')
            db.execute("UPDATE words SET llm_done=1 WHERE word='reserve'")
            sync.memorize(db, 100, {}, anki, hints)
            self.assertIn(('deleteNotes', {'notes': [5]}), calls)
            self.assertEqual(db.execute('SELECT word,note_id,llm_done FROM words').fetchall(), [('reserve', 9, 1)])

    def test_definitions_skip_names_and_stay_short(self):
        data = {'ec': {'word': {'trs': [{'pos': 'n.', 'tran': '一；二；三；四；五'},
                                        {'tran': '【名】 （Reserve）勒塞尔夫（人名）'}]}}}
        definition = sync.render_dictionary(data, 'reserve')['Definition']
        self.assertIn('一；二；三；四</div>', definition)
        self.assertNotIn('人名', definition)
        forms = sync.render_dictionary({'ec': {'word': {'trs': [{'tran': '保留'}], 'wfs': [
            {'wf': {'name': '复数', 'value': 'decks'}}, {'wf': {'name': '过去式', 'value': 'decked'}}]}}}, 'deck')['Forms']
        self.assertEqual(forms, '<span class="translation">复数</span> decks · <span class="translation">过去式</span> decked')

    def test_family_lists_stem_and_related_words(self):
        data = {'ec': {'word': {'trs': [{'pos': 'n.', 'tran': '仪式'}]}},
                'rel_word': {'stem': 'rite', 'rels': [{'rel': {'pos': 'adv.', 'words': [
                    {'word': 'ritually', 'tran': '仪式上地；依据仪式上地'}]}}]}}
        family = sync.render_dictionary(data, 'ritual')['Family']
        self.assertTrue(family.startswith('词干：rite<br>'))
        self.assertIn('ritually <span class="translation">仪式上地</span>', family)
        self.assertNotIn('依据', family)



class DependencyLogTests(unittest.TestCase):
    def test_persistent_problem_is_logged_once_and_recovery_noted(self):
        sync._reported.clear()
        with self.assertLogs(level='INFO') as logs:
            sync.report('LLM settings', 'missing')
            sync.report('LLM settings', 'missing')
            sync.report('LLM settings', None)
        self.assertEqual([r.getMessage() for r in logs.records], ['missing', 'LLM settings recovered'])

    def test_errors_name_the_changed_interface(self):
        with self.assertRaisesRegex(ValueError, 'no "ec" entry.*keys: input, meta'):
            sync.render_dictionary({'input': 'x', 'meta': {}}, 'x')
        with self.assertRaisesRegex(ValueError, 'invalid JSON: {bad'):
            sync.parse_memory('{bad}', 'x')

    def test_http_errors_keep_service_and_reason(self):
        error = urllib.error.HTTPError('https://llm', 401, 'Unauthorized', {}, io.BytesIO(b'{"error":"invalid key"}'))
        with patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaisesRegex(RuntimeError, 'LLM HTTP 401: {"error":"invalid key"}'):
                sync.fetch_json('LLM', None, 1)

    def test_history_format_change_is_explicit(self):
        changed = plistlib.dumps(['{"text": "deck"}'])
        def run(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, changed, b'')
        with patch('subprocess.run', side_effect=run):
            with self.assertRaisesRegex(RuntimeError, "history format changed.*found \\['text'\\]"):
                sync.read_history()


if __name__ == '__main__':
    unittest.main()
