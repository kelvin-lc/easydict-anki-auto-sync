import pathlib
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
                sync.sync(db, 100, anki)
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
            self.assertEqual(db.execute('SELECT enriched,audio_done,retry_at,audio_retry_at FROM words').fetchone(),
                             (0, 0, 0, 0))

if __name__ == '__main__':
    unittest.main()
