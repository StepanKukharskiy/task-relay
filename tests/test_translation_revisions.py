"""Small synthetic receipts for source-name revision of a selected parts pilot."""

from contextlib import closing
import json
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from zipfile import ZipFile
from types import SimpleNamespace
import uuid

from openpyxl import Workbook, load_workbook

from orchestrator.runtime import Runtime
from task_relay.bridge import State
from task_relay import (production_control as pc, reviewed_links, revision_review,
                        translation_revisions as translations, workflow_files)


def hd(path, first='CLAMP', duplicate=False):
    book = Workbook()
    sheet = book.active
    sheet.title = 'Лист1'
    sheet.append(['Артикул детали', 'Наименование детали', 'Стоимость детали'])
    sheet.append([10014, first, '1.00'])
    sheet.append(['10038A', 'CLAMP FUEL CROSSOVER HOSE', '1.00'])
    if duplicate:
        sheet.append([10014, 'SECOND NAME', '1.00'])
    book.save(path)
    book.close()


def pilot(path):
    book = Workbook()
    sheet = book.active
    sheet.title = translations.SHEET
    sheet.append([None] * 22)
    for row, brand, number, name, russian, url, status, raw, title in (
        (2, 'Harley-Davidson', '10014', 'CLAMP', 'Хомут шланга',
         'https://example.org/part-10014', translations.SUPPORTED,
         {'A': '10014', 'B': 'CLAMP', 'C': '1.00'}, 'Clamp, Hose'),
        (3, 'Harley-Davidson', '10038A', 'CLAMP FUEL CROSSOVER HOSE', 'Хомут шланга',
         'https://example.org/part-10038A', translations.SUPPORTED,
         {'A': '10038A', 'B': 'CLAMP FUEL CROSSOVER HOSE', 'C': '1.00'}, 'Clamp, Hose'),
        (4, 'Yamaha', '002-15381-00-00', 'PLATE,BRNG COVER', None, None,
         translations.UNRESOLVED,
         'YA002-15381-00-00;002-15381-00-00;YA;002153810000;PLATE,BRNG COVER;000;EA;0;;;0.16;0.25;YA002153810000;N', None)):
        source_row = 1 if brand == 'Yamaha' else row
        values = {'A': source_row, 'B': brand, 'C': number, 'D': name, 'F': russian,
                  'G': url, 'H': status,
                  'K': ('YAMAHA.txt; строка ' + str(source_row) if brand == 'Yamaha'
                        else 'HD_price.xlsx; Лист1; строка ' + str(source_row)),
                  'O': 'Original verification note',
                  'P': raw if isinstance(raw,str) else json.dumps(raw),
                  'Q': title, 'T': 'Saved review locator'}
        for column, value in values.items():
            sheet[f'{column}{row}'] = value
        if row == 2:
            sheet['I2'] = ''
        if url:
            sheet[f'G{row}'].hyperlink = url
    book.save(path)
    book.close()


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.state = State(self.root / 'data/state.sqlite')
        self.paths = SimpleNamespace(state=self.root / 'data/state.sqlite',
                                     generated=self.root / 'data/generated')
        self.rt = Runtime(pc.root(self.state), connection=self.state.db)
        self.job = 'job-' + 'b' * 24
        self.state.db.execute('''INSERT INTO relay_pipelines
            (id,request_id,request,title,spec,channel,provider,model,status,created)
            VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (self.job, 1, 'Revise exact pilot translations after a source change.',
             'Translation revision fixture', '{}', 'telegram', 'fixture', 'fixture',
             'active', 1))
        self.state.db.commit()
        hd(self.root/'HD_price.xlsx')
        hd(self.root/'HD_changed.xlsx', first='BOLT')
        (self.root/'YAMAHA.txt').write_text(
            'YA002-15381-00-00;002-15381-00-00;YA;002153810000;PLATE,BRNG COVER;000;EA;0;;;0.16;0.25;YA002153810000;N\n',
            encoding='utf-8')
        pilot(self.root/'pilot_translations.xlsx')
        (self.root/'verification_report.md').write_text('Selected independent verification fixture.')
        self.old = self.rt.register(self.root/'HD_price.xlsx', 'Original HD source')
        self.new = self.rt.register(self.root/'HD_changed.xlsx', 'Controlled changed HD source')
        self.yamaha = self.rt.register(self.root/'YAMAHA.txt', 'Original Yamaha source')
        self.output = self.rt.register(self.root/'pilot_translations.xlsx', 'Selected pilot')
        self.report = self.rt.register(self.root/'verification_report.md', 'Selected review report')

    def tearDown(self):
        self.state.db.close()
        self.temp.cleanup()

    def link_all(self):
        for row, source, kind in ((2,self.old,'hd_xlsx'),(3,self.old,'hd_xlsx'),
                                  (4,self.yamaha,'yamaha_txt')):
            translations.record_link(self.state.db, job=self.job, source_artifact=source,
                source_kind=kind, output_artifact=self.output, output_row=row,
                review_report_artifact=self.report,
                review_receipt='Exact selected pilot and report in controlled fixture.')

    def plan(self, replacement=None):
        return translations.plan_impact(self.state.db, job=self.job, old_source=self.old,
            replacement_source=replacement or self.new, baseline_artifact=self.output)

    def test_name_change_requires_review_and_preserves_other_rows(self):
        self.link_all()
        before = self.state.db.total_changes
        plan = self.plan()
        self.assertEqual(self.state.db.total_changes, before)
        self.assertEqual([x['part_number'] for x in plan['affected']], ['10014'])
        self.assertEqual([x['part_number'] for x in plan['unaffected']], ['10038A'])
        self.assertEqual([x['part_number'] for x in plan['unknown']], ['002-15381-00-00'])
        candidate = translations.create_candidate(self.rt, plan=plan)
        with Path(self.rt.artifact(candidate)['blob']).open('rb') as stream:
            book = load_workbook(stream)
        sheet = book[translations.SHEET]
        self.assertEqual(sheet['D2'].value, 'BOLT')
        self.assertIsNone(sheet['F2'].value)
        self.assertIsNone(sheet['G2'].value)
        self.assertIsNone(sheet['G2'].hyperlink)
        self.assertEqual(sheet['H2'].value, translations.UNRESOLVED)
        self.assertEqual(sheet['K2'].value, 'HD_changed.xlsx; Лист1; строка 2')
        self.assertEqual(sheet['K3'].value, 'HD_changed.xlsx; Лист1; строка 3')
        self.assertEqual(sheet['F3'].value, 'Хомут шланга')
        self.assertIsNone(sheet['F4'].value)
        book.close()
        ns = {'m': translations.MAIN_NS}
        with ZipFile(self.root/'pilot_translations.xlsx') as original, ZipFile(self.rt.artifact(candidate)['blob']) as revised:
            original_sheet = ET.fromstring(original.read('xl/worksheets/sheet1.xml'))
            revised_sheet = ET.fromstring(revised.read('xl/worksheets/sheet1.xml'))
            for address in ('I2', 'F3'):
                query = f'.//m:c[@r="{address}"]'
                self.assertEqual(ET.tostring(original_sheet.find(query, ns)),
                                 ET.tostring(revised_sheet.find(query, ns)))
            self.assertIsNone(revised_sheet.find('.//m:c[@r="F4"]', ns))
            for name in original.namelist():
                if name not in ('xl/worksheets/sheet1.xml',
                                'xl/worksheets/_rels/sheet1.xml.rels'):
                    self.assertEqual(original.read(name), revised.read(name))
        root = workflow_files.sync(self.state, self.job)
        manifest = json.loads((root/'manifest.json').read_text())
        self.assertFalse(next(a['selected'] for a in manifest['artifacts'] if a['id']==candidate))
        with closing(sqlite3.connect(root/'.relay/job.sqlite')) as view:
            self.assertEqual(view.execute('SELECT count(*) FROM translation_links').fetchone()[0], 3)
            self.assertEqual(view.execute('SELECT count(*) FROM translation_revisions').fetchone()[0], 1)

    def test_shared_link_contract_tracks_txt_and_xlsx_and_rejects_unreviewed_reuse(self):
        self.link_all()
        plan = self.plan()
        shared = plan['reviewed_impact']
        self.assertEqual(shared['schema'], reviewed_links.IMPACT_SCHEMA)
        self.assertEqual([item['status'] for item in shared['outcomes']],
                         ['affected', 'unaffected', 'unknown'])
        model = reviewed_links.records(self.state.db, self.job)
        self.assertEqual({link['source']['locator']['type'] for link in model['links']},
                         {'xlsx_cell', 'txt_field'})
        self.assertEqual(next(link['review']['state'] for link in model['links']
                              if link['entity']['key'] == '002-15381-00-00'), 'pending')
        forged = {**plan, 'unaffected': [*plan['unaffected'],
                  {**plan['unknown'][0], 'reason': 'Forged reuse.'}], 'unknown': []}
        with self.assertRaisesRegex(ValueError, 'complete reviewed'):
            reviewed_links.impact_record(model, kind='parts_translation', plan=forged,
                source_sha256=shared['old_source_sha256'],
                replacement_sha256=shared['replacement_sha256'])
        candidate = translations.create_candidate(self.rt, plan=plan)
        root = workflow_files.sync(self.state, self.job)
        with closing(sqlite3.connect(root/'.relay/job.sqlite')) as view:
            self.assertEqual(view.execute('SELECT count(*) FROM reviewed_links').fetchone()[0], 3)
            saved = view.execute('SELECT record FROM reviewed_impacts WHERE candidate_artifact=?',
                                 (candidate,)).fetchone()[0]
            self.assertEqual(json.loads(saved), shared)

    def test_earlier_candidate_digest_stays_reviewable_and_new_impact_is_checked(self):
        self.link_all()
        plan = self.plan()
        original = {key: value for key, value in plan.items()
                    if key not in ('digest', 'reviewed_impact')}
        self.assertEqual(plan['digest'], hashlib.sha256(json.dumps(
            original, sort_keys=True, ensure_ascii=False).encode()).hexdigest())
        candidate = translations.create_candidate(self.rt, plan=plan)
        self.state.db.execute('UPDATE relay_reviewed_impacts SET record=? WHERE candidate_artifact=?',
                              ('{}', candidate))
        self.state.db.commit()
        with self.assertRaisesRegex(ValueError, 'Saved reviewed impact changed'):
            translations.verified_candidate(self.state.db, candidate)
        self.state.db.execute('DELETE FROM relay_reviewed_impacts WHERE candidate_artifact=?',
                              (candidate,))
        self.state.db.commit()
        self.assertEqual(translations.verified_candidate(self.state.db, candidate)[0]['plan_digest'],
                         plan['digest'])

    def test_duplicate_key_and_changed_review_bytes_remain_unknown(self):
        self.link_all()
        hd(self.root/'duplicate.xlsx', first='BOLT', duplicate=True)
        duplicate = self.rt.register(self.root/'duplicate.xlsx', 'Ambiguous source')
        plan = self.plan(duplicate)
        self.assertIn('10014', [x['part_number'] for x in plan['unknown']])
        path = Path(self.rt.artifact(self.report)['blob'])
        path.chmod(0o600)
        path.write_text('Changed review report.')
        plan = self.plan()
        self.assertEqual([x['part_number'] for x in plan['unknown']],
                         ['10014', '10038A', '002-15381-00-00'])

    def test_other_source_field_change_cannot_be_called_supported_unchanged(self):
        self.link_all()
        changed = self.root / 'HD_price_changed_price.xlsx'
        hd(changed, first='BOLT')
        with closing(load_workbook(changed)) as book:
            book['Лист1']['C3'] = '2.00'
            book.save(changed)
        replacement = self.rt.register(changed, 'Name and price changed source')
        plan = self.plan(replacement)
        self.assertEqual([r['part_number'] for r in plan['affected']], ['10014'])
        self.assertEqual([r['part_number'] for r in plan['unknown']],
                         ['10038A', '002-15381-00-00'])
        self.assertEqual(plan['unaffected'], [])

    def test_reordered_replacement_rows_rebind_both_source_row_fields(self):
        self.link_all()
        changed = self.root / 'HD_reordered.xlsx'
        hd(changed, first='BOLT')
        with closing(load_workbook(changed)) as book:
            sheet = book['Лист1']
            first = [sheet.cell(2, column).value for column in range(1, 4)]
            second = [sheet.cell(3, column).value for column in range(1, 4)]
            for column in range(1, 4):
                sheet.cell(2, column).value = second[column - 1]
                sheet.cell(3, column).value = first[column - 1]
            book.save(changed)
        replacement = self.rt.register(changed, 'Reordered changed source')
        plan = self.plan(replacement)
        self.assertEqual(plan['affected'][0]['new_source_row'], 3)
        self.assertEqual(plan['unaffected'][0]['new_source_row'], 2)
        candidate = translations.create_candidate(self.rt, plan=plan)
        with Path(self.rt.artifact(candidate)['blob']).open('rb') as stream, closing(load_workbook(stream)) as book:
            sheet = book[translations.SHEET]
            self.assertEqual((sheet['A2'].value, sheet['K2'].value),
                             (3, 'HD_reordered.xlsx; Лист1; строка 3'))
            self.assertEqual((sheet['A3'].value, sheet['K3'].value),
                             (2, 'HD_reordered.xlsx; Лист1; строка 2'))
            self.assertEqual(sheet['F3'].value, 'Хомут шланга')

    def test_link_rejects_native_source_locator_that_disagrees_with_registered_file(self):
        altered = self.root / 'bad_pilot.xlsx'
        with closing(load_workbook(self.root / 'pilot_translations.xlsx')) as book:
            book[translations.SHEET]['K2'] = 'different.xlsx; Лист1; строка 2'
            book.save(altered)
        output = self.rt.register(altered, 'Pilot with wrong source locator')
        with self.assertRaisesRegex(ValueError, 'source locator differs'):
            translations.record_link(self.state.db, job=self.job, source_artifact=self.old,
                source_kind='hd_xlsx', output_artifact=output, output_row=2,
                review_report_artifact=self.report, review_receipt='Test review.')

    def test_generic_review_is_separate_from_exact_selection_and_retry_is_safe(self):
        self.link_all()
        candidate = translations.create_candidate(self.rt, plan=self.plan())
        workflow_files.sync(self.state, self.job)
        listed = revision_review.candidates(self.paths)['items']
        self.assertEqual([(item['kind'], item['status']) for item in listed],
                         [('parts_translation', 'awaiting_review')])
        view = revision_review.detail(candidate, self.paths)
        self.assertTrue(view['verified'])
        self.assertTrue(view['can_review'])
        self.assertFalse(view['can_select'])
        self.assertEqual(next(link['source_location'] for link in view['evidence_links']
                              if link['output_location'] == translations.SHEET + '!F4'),
                         'Yamaha TXT row 1 · name field')
        self.assertTrue(Path(view['candidate_path']).is_file())
        with self.assertRaisesRegex(ValueError, 'changed'):
            revision_review.decide(candidate_artifact=candidate, verb='accept',
                actor='Human reviewer', note='Compared the exact workbook.',
                expected_sha256='0'*64, expected_plan_digest=view['plan']['digest'],
                request_id=str(uuid.uuid4()), paths=self.paths)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_translation_reviews').fetchone()[0], 0)
        request_id = str(uuid.uuid4())
        decision = dict(candidate_artifact=candidate, verb='accept', actor='Human reviewer',
                        note='Compared the changed row and six preserved translations.',
                        expected_sha256=view['candidate_sha256'],
                        expected_plan_digest=view['plan']['digest'],
                        request_id=request_id, paths=self.paths)
        first = revision_review.decide(**decision)
        again = revision_review.decide(**decision)
        self.assertEqual(first['result_id'], again['result_id'])
        self.assertTrue(first['detail']['can_select'])
        self.assertIsNone(first['detail']['selection'])
        with self.assertRaisesRegex(ValueError, 'different content'):
            revision_review.decide(**{**decision, 'note': 'Different decision content.'})
        selected = revision_review.decide(candidate_artifact=candidate, verb='select',
            actor='Human reviewer', note='', expected_sha256=view['candidate_sha256'],
            expected_plan_digest=view['plan']['digest'], request_id=str(uuid.uuid4()),
            paths=self.paths)
        self.assertEqual(selected['detail']['selection']['candidate_artifact'], candidate)
        self.assertEqual(revision_review.candidates(self.paths)['items'][0]['status'], 'selected')
        folder = workflow_files.sync(self.state, self.job)
        manifest = json.loads((folder/'manifest.json').read_text())
        self.assertTrue(next(a['selected'] for a in manifest['artifacts'] if a['id']==candidate))
        with closing(sqlite3.connect(folder/'.relay/job.sqlite')) as projection:
            self.assertEqual(projection.execute('SELECT decision FROM translation_reviews').fetchone()[0], 'accept')
            self.assertEqual(projection.execute('SELECT candidate_artifact FROM translation_selections').fetchone()[0], candidate)
            self.assertEqual(projection.execute(
                'SELECT count(*) FROM translation_links WHERE output_artifact=?',
                (candidate,)).fetchone()[0], 3)

    def test_selected_candidate_carries_exact_links_for_a_second_source_change(self):
        self.link_all()
        candidate = translations.create_candidate(self.rt, plan=self.plan())
        translations.review_candidate(self.state.db, candidate_artifact=candidate,
            decision='accept', reviewer='Fixture reviewer',
            note='Accepted exact first candidate for controlled continuation.')
        selection = translations.select_candidate(self.state.db,
            candidate_artifact=candidate, selected_by='Fixture selector',
            receipt='Controlled selection of exact first candidate.')
        links = [link for link in translations.records(self.state.db, self.job)['links']
                 if link['output_artifact'] == candidate]
        self.assertEqual(len(links), 3)
        self.assertEqual({link['source_artifact'] for link in links
                          if link['part_number'] != '002-15381-00-00'}, {self.new})
        changed = next(link for link in links if link['part_number'] == '10014')
        self.assertEqual(changed['status'], translations.UNRESOLVED)
        self.assertIsNone(changed['russian_name'])
        self.assertIsNone(changed['evidence_url'])
        lineage = json.loads(changed['review_receipt'])
        self.assertEqual(lineage['selection_id'], selection)
        self.assertEqual(lineage['candidate_sha256'], self.rt.artifact(candidate)['sha256'])
        self.assertEqual(lineage['source_binding'], 'replacement')
        self.assertEqual(lineage['impact_status'], 'affected')

        self.state.db.close()
        self.state = State(self.paths.state)
        self.rt = Runtime(pc.root(self.state), connection=self.state.db)

        second_path = self.root / 'HD_second.xlsx'
        hd(second_path, first='BOLT')
        with closing(load_workbook(second_path)) as book:
            book['Лист1']['B3'] = 'FUEL LINE CLAMP'
            book.save(second_path)
        second_source = self.rt.register(second_path, 'Second controlled source version')
        second_plan = translations.plan_impact(self.state.db, job=self.job,
            old_source=self.new, replacement_source=second_source,
            baseline_artifact=candidate)
        self.assertEqual([item['part_number'] for item in second_plan['affected']],
                         ['10038A'])
        self.assertEqual({item['part_number'] for item in second_plan['unknown']},
                         {'10014', '002-15381-00-00'})
        second_candidate = translations.create_candidate(self.rt, plan=second_plan)
        with Path(self.rt.artifact(second_candidate)['blob']).open('rb') as stream, \
                closing(load_workbook(stream)) as book:
            sheet = book[translations.SHEET]
            self.assertIsNone(sheet['F2'].value)
            self.assertIsNone(sheet['F3'].value)
            self.assertEqual(sheet['D2'].value, 'BOLT')
            self.assertEqual(sheet['D3'].value, 'FUEL LINE CLAMP')
        self.assertFalse(self.state.db.execute(
            'SELECT 1 FROM relay_translation_selections WHERE candidate_artifact=?',
            (second_candidate,)).fetchone())

    def test_link_transfer_failure_rolls_back_selection_and_all_child_links(self):
        self.link_all()
        candidate = translations.create_candidate(self.rt, plan=self.plan())
        translations.review_candidate(self.state.db, candidate_artifact=candidate,
            decision='accept', reviewer='Fixture reviewer',
            note='Accepted exact candidate before forced transfer failure.')
        self.state.db.execute('''CREATE TEMP TRIGGER fail_link_transfer
            BEFORE INSERT ON relay_translation_links
            WHEN NEW.output_artifact = '%s' AND NEW.output_row = 3
            BEGIN SELECT RAISE(ABORT, 'forced child link failure'); END'''
            % candidate)
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'forced child link failure'):
            translations.select_candidate(self.state.db, candidate_artifact=candidate,
                selected_by='Fixture selector', receipt='Attempted exact selection.')
        self.assertEqual(self.state.db.execute(
            'SELECT count(*) FROM relay_translation_selections WHERE candidate_artifact=?',
            (candidate,)).fetchone()[0], 0)
        self.assertEqual(self.state.db.execute(
            'SELECT count(*) FROM relay_translation_links WHERE output_artifact=?',
            (candidate,)).fetchone()[0], 0)

    def test_selection_rejects_unresolved_replacement_for_supported_name(self):
        self.link_all()
        changed = self.root / 'HD_ambiguous.xlsx'
        hd(changed, first='BOLT')
        with closing(load_workbook(changed)) as book:
            book['Лист1'].append(['10038A', 'OTHER NAME', '1.00'])
            book.save(changed)
        replacement = self.rt.register(changed, 'Ambiguous replacement source')
        plan = self.plan(replacement)
        self.assertEqual([row['part_number'] for row in plan['affected']], ['10014'])
        self.assertIn('10038A', [row['part_number'] for row in plan['unknown']])
        candidate = translations.create_candidate(self.rt, plan=plan)
        translations.review_candidate(self.state.db, candidate_artifact=candidate,
            decision='accept', reviewer='Fixture reviewer',
            note='Controlled acceptance to exercise the selection guard.')
        with self.assertRaisesRegex(ValueError, 'unresolved replacement source row'):
            translations.select_candidate(self.state.db, candidate_artifact=candidate,
                selected_by='Fixture selector', receipt='Attempted selection.')
        self.assertEqual(self.state.db.execute(
            'SELECT count(*) FROM relay_translation_selections WHERE candidate_artifact=?',
            (candidate,)).fetchone()[0], 0)
        self.assertEqual(self.state.db.execute(
            'SELECT count(*) FROM relay_translation_links WHERE output_artifact=?',
            (candidate,)).fetchone()[0], 0)

    def test_failed_postcommit_export_retries_without_duplicate_selection_links(self):
        self.link_all()
        candidate = translations.create_candidate(self.rt, plan=self.plan())
        view = revision_review.detail(candidate, self.paths)
        revision_review.decide(candidate_artifact=candidate, verb='accept',
            actor='Fixture reviewer', note='Controlled exact review.',
            expected_sha256=view['candidate_sha256'],
            expected_plan_digest=view['plan']['digest'],
            request_id=str(uuid.uuid4()), paths=self.paths)
        request_id = str(uuid.uuid4())
        selection = dict(candidate_artifact=candidate, verb='select',
            actor='Fixture selector', note='', expected_sha256=view['candidate_sha256'],
            expected_plan_digest=view['plan']['digest'], request_id=request_id,
            paths=self.paths)
        with patch('task_relay.workflow_files.sync', side_effect=OSError('fixture export interrupted')):
            first = revision_review.decide(**selection)
        self.assertIn('fixture export interrupted', first['warning'])
        self.assertEqual(self.state.db.execute(
            'SELECT count(*) FROM relay_translation_selections WHERE candidate_artifact=?',
            (candidate,)).fetchone()[0], 1)
        self.assertEqual(self.state.db.execute(
            'SELECT count(*) FROM relay_translation_links WHERE output_artifact=?',
            (candidate,)).fetchone()[0], 3)
        retried = revision_review.decide(**selection)
        self.assertEqual(retried['result_id'], first['result_id'])
        self.assertIsNone(retried['warning'])
        self.assertEqual(self.state.db.execute(
            'SELECT count(*) FROM relay_translation_links WHERE output_artifact=?',
            (candidate,)).fetchone()[0], 3)
        with closing(sqlite3.connect(self.paths.generated / 'workflows' / self.job /
                                     '.relay' / 'job.sqlite')) as projection:
            self.assertEqual(projection.execute(
                'SELECT count(*) FROM translation_links WHERE output_artifact=?',
                (candidate,)).fetchone()[0], 3)

    def test_revision_request_cannot_select_a_rejected_candidate(self):
        self.link_all()
        candidate = translations.create_candidate(self.rt, plan=self.plan())
        view = revision_review.detail(candidate, self.paths)
        rejected = revision_review.decide(candidate_artifact=candidate, verb='revise',
            actor='Human reviewer', note='Source conflict needs a fresh catalog check.',
            expected_sha256=view['candidate_sha256'],
            expected_plan_digest=view['plan']['digest'], request_id=str(uuid.uuid4()),
            paths=self.paths)
        self.assertFalse(rejected['detail']['can_select'])
        with self.assertRaisesRegex(ValueError, 'accepted'):
            revision_review.decide(candidate_artifact=candidate, verb='select',
                actor='Human reviewer', note='', expected_sha256=view['candidate_sha256'],
                expected_plan_digest=view['plan']['digest'], request_id=str(uuid.uuid4()),
                paths=self.paths)

    def test_desktop_bridge_exposes_generic_candidate_without_deciding_it(self):
        self.link_all()
        candidate = translations.create_candidate(self.rt, plan=self.plan())
        workflow_files.sync(self.state, self.job)
        environment = {**os.environ,
            'TASK_RELAY_DATA_DIR': str(self.paths.state.parent),
            'TASK_RELAY_GENERATED_DIR': str(self.root/'generated'),
            'TASK_RELAY_WORKSPACE_DIR': str(self.root/'workspaces')}
        def bridge(action, payload):
            process = subprocess.run([sys.executable, '-m', 'task_relay.desktop_bridge', action],
                input=json.dumps(payload), text=True, capture_output=True,
                env=environment, timeout=15)
            self.assertTrue(process.stdout, process.stderr)
            return process, json.loads(process.stdout)
        process, listing = bridge('revision-candidates', {})
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(listing['value']['items'][0]['candidate_artifact'], candidate)
        process, detail = bridge('revision-detail', {'candidate_artifact': candidate})
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertTrue(detail['value']['verified'])
        self.assertEqual(len(detail['value']['plan']['affected']), 1)
        self.assertIsNone(detail['value']['review'])
        self.assertIsNone(detail['value']['selection'])

    def test_changed_review_report_blocks_the_saved_candidate_decision(self):
        self.link_all()
        candidate = translations.create_candidate(self.rt, plan=self.plan())
        valid = revision_review.detail(candidate, self.paths)
        saved_report = Path(self.rt.artifact(self.report)['blob'])
        saved_report.chmod(0o600)
        saved_report.write_text('Tampered review bytes.')
        stale = revision_review.detail(candidate, self.paths)
        self.assertFalse(stale['verified'])
        self.assertFalse(stale['can_review'])
        with self.assertRaisesRegex(ValueError, 'changed'):
            revision_review.decide(candidate_artifact=candidate, verb='accept',
                actor='Human reviewer', note='Incorrect stale acceptance.',
                expected_sha256=valid['candidate_sha256'],
                expected_plan_digest=valid['plan']['digest'],
                request_id=str(uuid.uuid4()), paths=self.paths)
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM relay_translation_reviews').fetchone()[0], 0)

    def test_candidate_remains_readable_before_new_decision_schema_is_initialized(self):
        self.link_all()
        candidate = translations.create_candidate(self.rt, plan=self.plan())
        self.state.db.execute('DROP TABLE relay_translation_reviews')
        self.state.db.commit()
        listed = revision_review.candidates(self.paths)['items'][0]
        self.assertEqual(listed['status'], 'requires_restart')
        view = revision_review.detail(candidate, self.paths)
        self.assertTrue(view['verified'])
        self.assertFalse(view['can_review'])
        self.assertIn('Restart Relay', view['decision_blocker'])


if __name__ == '__main__':
    unittest.main()
