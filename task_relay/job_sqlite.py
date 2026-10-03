"""Format-neutral, read-only SQLite projection of a committed Relay job."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile

SCHEMA = "task-relay.job-view"
VERSION = 12

def projection_bytes(report):
    """Build a disposable, queryable view from a committed workflow report."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'job.sqlite'
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            db.execute('CREATE TABLE artifacts(id TEXT PRIMARY KEY,sha256 TEXT,copy_path TEXT,copy_status TEXT)')
            db.execute('''CREATE TABLE fact_bindings(id TEXT PRIMARY KEY,entity_type TEXT,entity_key TEXT,
                predicate TEXT,value TEXT,source_artifact TEXT,source_sha256 TEXT,source_sheet TEXT,
                source_cell TEXT,evidence TEXT,review_state TEXT,reviewer TEXT,
                output_artifact TEXT,output_sha256 TEXT,output_sheet TEXT,output_cell TEXT,check_kind TEXT)''')
            db.execute('''CREATE TABLE coverage(output_artifact TEXT,output_sheet TEXT,output_cell TEXT,
                state TEXT,note TEXT,PRIMARY KEY(output_artifact,output_sheet,output_cell))''')
            db.execute('CREATE TABLE revisions(candidate_artifact TEXT PRIMARY KEY,baseline_artifact TEXT,plan_digest TEXT,patches TEXT)')
            db.execute('CREATE TABLE candidate_reviews(candidate_artifact TEXT PRIMARY KEY,candidate_sha256 TEXT,decision TEXT,reviewer TEXT,note TEXT,checks TEXT)')
            db.execute('CREATE TABLE selections(candidate_artifact TEXT PRIMARY KEY,candidate_sha256 TEXT,baseline_artifact TEXT,selected_by TEXT,receipt TEXT)')
            db.execute('''CREATE TABLE fact_external_submissions(id TEXT PRIMARY KEY,job TEXT,
                submission_key TEXT,handoff_id TEXT,candidate_artifact TEXT,
                candidate_sha256 TEXT,checks TEXT,submitted_by TEXT,created REAL)''')
            db.execute('''CREATE TABLE translation_links(id TEXT PRIMARY KEY,source_artifact TEXT,
                source_sha256 TEXT,source_kind TEXT,source_row INTEGER,part_number TEXT,
                source_name TEXT,output_artifact TEXT,output_sha256 TEXT,output_row INTEGER,
                russian_name TEXT,status TEXT,evidence_url TEXT,evidence_title TEXT,
                evidence_locator TEXT,review_report_artifact TEXT,review_report_sha256 TEXT,
                review_receipt TEXT)''')
            db.execute('''CREATE TABLE translation_revisions(candidate_artifact TEXT PRIMARY KEY,
                baseline_artifact TEXT,old_source TEXT,replacement_source TEXT,
                plan_digest TEXT,patches TEXT)''')
            db.execute('''CREATE TABLE translation_reviews(candidate_artifact TEXT PRIMARY KEY,
                candidate_sha256 TEXT,decision TEXT,reviewer TEXT,note TEXT,checks TEXT)''')
            db.execute('''CREATE TABLE translation_selections(candidate_artifact TEXT PRIMARY KEY,
                candidate_sha256 TEXT,baseline_artifact TEXT,selected_by TEXT,receipt TEXT)''')
            db.execute('''CREATE TABLE presentation_links(id TEXT PRIMARY KEY,
                source_artifact TEXT,source_sha256 TEXT,source_sheet TEXT,source_cell TEXT,
                entity_key TEXT,predicate TEXT,value TEXT,output_artifact TEXT,
                output_sha256 TEXT,slide INTEGER,shape_id INTEGER,evidence TEXT,review_state TEXT)''')
            db.execute('''CREATE TABLE presentation_coverage(output_artifact TEXT,
                slide INTEGER,shape_id INTEGER,state TEXT,note TEXT,
                PRIMARY KEY(output_artifact,slide,shape_id))''')
            db.execute('''CREATE TABLE presentation_revisions(candidate_artifact TEXT PRIMARY KEY,
                baseline_artifact TEXT,old_source TEXT,replacement_source TEXT,
                plan_digest TEXT,edits TEXT)''')
            db.execute('''CREATE TABLE presentation_reviews(candidate_artifact TEXT PRIMARY KEY,
                candidate_sha256 TEXT,decision TEXT,reviewer TEXT,note TEXT,checks TEXT)''')
            db.execute('''CREATE TABLE presentation_selections(candidate_artifact TEXT PRIMARY KEY,
                candidate_sha256 TEXT,baseline_artifact TEXT,selected_by TEXT,receipt TEXT)''')
            db.execute('''CREATE TABLE reviewed_links(id TEXT PRIMARY KEY,kind TEXT,
                source_artifact TEXT,source_sha256 TEXT,output_artifact TEXT,
                output_sha256 TEXT,output_location TEXT,review_state TEXT,record TEXT)''')
            db.execute('''CREATE TABLE reviewed_coverage(kind TEXT,output_artifact TEXT,
                output_location TEXT,state TEXT,reason TEXT,
                PRIMARY KEY(kind,output_artifact,output_location))''')
            db.execute('''CREATE TABLE reviewed_impacts(candidate_artifact TEXT PRIMARY KEY,
                plan_digest TEXT,record TEXT)''')
            db.execute('''CREATE TABLE impact_handoffs(id TEXT PRIMARY KEY,job TEXT NOT NULL,
                request_key TEXT NOT NULL,exact_request TEXT NOT NULL,kind TEXT NOT NULL,
                baseline_artifact TEXT NOT NULL,
                inputs TEXT NOT NULL,plan_digest TEXT NOT NULL,plan TEXT NOT NULL,
                actor TEXT NOT NULL,created REAL NOT NULL)''')
            db.execute('''CREATE TABLE agent_candidates(id TEXT PRIMARY KEY,job TEXT NOT NULL,
                submission_key TEXT NOT NULL,handoff_id TEXT NOT NULL,
                candidate_artifact TEXT NOT NULL,candidate_sha256 TEXT NOT NULL,
                manifest TEXT NOT NULL,submitted_by TEXT NOT NULL,checks TEXT NOT NULL,
                created REAL NOT NULL)''')
            db.execute('''CREATE TABLE agent_candidate_inputs(candidate_artifact TEXT NOT NULL,
                job TEXT NOT NULL,path TEXT NOT NULL,artifact TEXT NOT NULL,
                sha256 TEXT NOT NULL,PRIMARY KEY(candidate_artifact,path))''')
            db.execute('''CREATE TABLE agent_candidate_reviews(id TEXT PRIMARY KEY,
                candidate_artifact TEXT NOT NULL,candidate_sha256 TEXT NOT NULL,
                plan_digest TEXT NOT NULL,decision TEXT NOT NULL,reviewer TEXT NOT NULL,
                note TEXT NOT NULL,checks TEXT NOT NULL,created REAL NOT NULL)''')
            db.execute('''CREATE TABLE agent_candidate_feedback(id TEXT PRIMARY KEY,
                job TEXT NOT NULL,feedback_key TEXT NOT NULL,
                candidate_artifact TEXT NOT NULL,candidate_sha256 TEXT NOT NULL,
                plan_digest TEXT NOT NULL,scope TEXT NOT NULL,
                assessment TEXT NOT NULL,actor TEXT NOT NULL,
                exact_feedback TEXT NOT NULL,created REAL NOT NULL)''')
            db.execute('''CREATE TABLE agent_candidate_selections(candidate_artifact TEXT PRIMARY KEY,
                candidate_sha256 TEXT NOT NULL,plan_digest TEXT NOT NULL,
                selected_by TEXT NOT NULL,receipt TEXT NOT NULL,created REAL NOT NULL)''')
            db.execute('''CREATE TABLE revision_bundle_plans(id TEXT PRIMARY KEY,job TEXT,
                request_key TEXT,handoff_id TEXT,exact_request TEXT,plan_digest TEXT,
                plan TEXT,actor TEXT,created REAL)''')
            db.execute('''CREATE TABLE revision_bundles(id TEXT PRIMARY KEY,job TEXT,
                submission_key TEXT,plan_id TEXT,pptx_candidate TEXT,set_digest TEXT,
                checks TEXT,submitted_by TEXT,created REAL)''')
            db.execute('''CREATE TABLE revision_bundle_files(bundle_id TEXT,job TEXT,
                role TEXT,baseline_artifact TEXT,baseline_sha256 TEXT,
                candidate_artifact TEXT,candidate_sha256 TEXT,
                PRIMARY KEY(bundle_id,role))''')
            db.execute('''CREATE TABLE revision_bundle_reviews(id TEXT PRIMARY KEY,
                bundle_id TEXT,job TEXT,set_digest TEXT,decision TEXT,reviewer TEXT,
                exact_feedback TEXT,note TEXT,created REAL)''')
            db.execute('''CREATE TABLE revision_bundle_selections(bundle_id TEXT PRIMARY KEY,
                job TEXT,set_digest TEXT,selected_by TEXT,receipt TEXT,created REAL)''')
            db.execute('''CREATE TABLE bundle_continuation_plans(id TEXT PRIMARY KEY,
                job TEXT,request_key TEXT,parent_bundle TEXT,exact_request TEXT,
                plan_digest TEXT,plan TEXT,actor TEXT,created REAL)''')
            db.execute('''CREATE TABLE bundle_continuations(id TEXT PRIMARY KEY,
                job TEXT,submission_key TEXT,plan_id TEXT,pptx_artifact TEXT,
                pptx_sha256 TEXT,slides_artifact TEXT,slides_sha256 TEXT,
                photo_manifest_artifact TEXT,photo_manifest_sha256 TEXT,
                set_digest TEXT,checks TEXT,submitted_by TEXT,created REAL)''')
            db.execute('''CREATE TABLE bundle_continuation_reviews(id TEXT PRIMARY KEY,
                candidate_id TEXT,job TEXT,set_digest TEXT,decision TEXT,
                reviewer TEXT,note TEXT,created REAL)''')
            db.execute('''CREATE TABLE bundle_continuation_selections(candidate_id TEXT PRIMARY KEY,
                job TEXT,set_digest TEXT,selected_by TEXT,receipt TEXT,created REAL)''')
            for key, value in (('schema', SCHEMA), ('version', str(VERSION)), ('job', report['id']),
                               ('snapshot', report['snapshot']), ('authority', 'read-only projection')):
                db.execute('INSERT INTO meta VALUES (?,?)', (key, value))
            for a in report['artifacts']:
                db.execute('INSERT INTO artifacts VALUES (?,?,?,?)',
                           (a['id'], a['sha256'], a.get('copy_path'), a.get('copy_status')))
            facts = report.get('facts', {})
            for b in facts.get('bindings', []):
                db.execute('INSERT INTO fact_bindings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           tuple(b[k] for k in ('id','entity_type','entity_key','predicate','value',
                               'source_artifact','source_sha256','source_sheet','source_cell',
                               'evidence','review_state','reviewer','output_artifact','output_sha256',
                               'output_sheet','output_cell','check_kind')))
            for c in facts.get('coverage', []):
                db.execute('INSERT INTO coverage VALUES (?,?,?,?,?)',
                           tuple(c[k] for k in ('output_artifact','output_sheet','output_cell','state','note')))
            for r in facts.get('revisions', []):
                db.execute('INSERT INTO revisions VALUES (?,?,?,?)',
                           tuple(r[k] for k in ('candidate_artifact','baseline_artifact','plan_digest','patches')))
            for review in facts.get('candidate_reviews', []):
                db.execute('INSERT INTO candidate_reviews VALUES (?,?,?,?,?,?)',
                           tuple(review[k] for k in ('candidate_artifact','candidate_sha256',
                               'decision','reviewer','note','checks')))
            for selection in facts.get('selections', []):
                db.execute('INSERT INTO selections VALUES (?,?,?,?,?)',
                    tuple(selection[k] for k in ('candidate_artifact','candidate_sha256',
                               'baseline_artifact','selected_by','receipt')))
            for submission in facts.get('external_submissions', []):
                db.execute('INSERT INTO fact_external_submissions VALUES (?,?,?,?,?,?,?,?,?)',
                    tuple(submission[k] for k in ('id','job','submission_key','handoff_id',
                        'candidate_artifact','candidate_sha256','checks','submitted_by','created')))
            translations = report.get('translations', {})
            for link in translations.get('links', []):
                db.execute('INSERT INTO translation_links VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    tuple(link[k] for k in ('id','source_artifact','source_sha256','source_kind',
                        'source_row','part_number','source_name','output_artifact','output_sha256',
                        'output_row','russian_name','status','evidence_url','evidence_title',
                        'evidence_locator','review_report_artifact','review_report_sha256',
                        'review_receipt')))
            for revision in translations.get('revisions', []):
                db.execute('INSERT INTO translation_revisions VALUES (?,?,?,?,?,?)',
                    tuple(revision[k] for k in ('candidate_artifact','baseline_artifact',
                        'old_source','replacement_source','plan_digest','patches')))
            for review in translations.get('reviews', []):
                db.execute('INSERT INTO translation_reviews VALUES (?,?,?,?,?,?)',
                    tuple(review[k] for k in ('candidate_artifact','candidate_sha256',
                        'decision','reviewer','note','checks')))
            for selection in translations.get('selections', []):
                db.execute('INSERT INTO translation_selections VALUES (?,?,?,?,?)',
                    tuple(selection[k] for k in ('candidate_artifact','candidate_sha256',
                        'baseline_artifact','selected_by','receipt')))
            presentations = report.get('presentations', {})
            for link in presentations.get('links', []):
                db.execute('INSERT INTO presentation_links VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    tuple(link[k] for k in ('id','source_artifact','source_sha256',
                        'source_sheet','source_cell','entity_key','predicate','value',
                        'output_artifact','output_sha256','slide','shape_id','evidence','review_state')))
            for cover in presentations.get('coverage', []):
                db.execute('INSERT INTO presentation_coverage VALUES (?,?,?,?,?)',
                    tuple(cover[k] for k in ('output_artifact','slide','shape_id','state','note')))
            for revision in presentations.get('revisions', []):
                db.execute('INSERT INTO presentation_revisions VALUES (?,?,?,?,?,?)',
                    tuple(revision[k] for k in ('candidate_artifact','baseline_artifact',
                        'old_source','replacement_source','plan_digest','edits')))
            for review in presentations.get('reviews', []):
                db.execute('INSERT INTO presentation_reviews VALUES (?,?,?,?,?,?)',
                    tuple(review[k] for k in ('candidate_artifact','candidate_sha256',
                        'decision','reviewer','note','checks')))
            for selection in presentations.get('selections', []):
                db.execute('INSERT INTO presentation_selections VALUES (?,?,?,?,?)',
                    tuple(selection[k] for k in ('candidate_artifact','candidate_sha256',
                        'baseline_artifact','selected_by','receipt')))
            from . import reviewed_links
            model = report.get('reviewed_links') or reviewed_links.from_records(
                facts, translations, presentations, report.get('native_links', {}))
            for link in model['links']:
                db.execute('INSERT INTO reviewed_links VALUES (?,?,?,?,?,?,?,?,?)',
                    (link['id'], link['kind'], link['source']['artifact'],
                     link['source']['sha256'], link['output']['artifact'],
                     link['output']['sha256'], reviewed_links.location(
                         link['output']['locator'], exact_run=link['kind'] == 'native_subject'),
                     link['review']['state'], json.dumps(link, sort_keys=True, ensure_ascii=False)))
            for item in model['coverage']:
                db.execute('INSERT INTO reviewed_coverage VALUES (?,?,?,?,?)',
                    tuple(item[k] for k in ('kind','output_artifact','output_location',
                                             'state','reason')))
            for item in report.get('reviewed_impacts', []):
                db.execute('INSERT INTO reviewed_impacts VALUES (?,?,?)',
                    (item['candidate_artifact'], item['plan_digest'],
                     json.dumps(item['record'], sort_keys=True, ensure_ascii=False)))
            for item in report.get('impact_handoffs', []):
                db.execute('INSERT INTO impact_handoffs VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    tuple(item[key] for key in ('id','job','request_key','exact_request',
                        'kind','baseline_artifact','inputs','plan_digest','plan','actor','created')))
            agents = report.get('agent_candidates', {})
            for item in agents.get('candidates', []):
                db.execute('INSERT INTO agent_candidates VALUES (?,?,?,?,?,?,?,?,?,?)',
                    tuple(item[key] for key in ('id','job','submission_key','handoff_id',
                        'candidate_artifact','candidate_sha256','manifest','submitted_by',
                        'checks','created')))
            for item in agents.get('inputs', []):
                db.execute('INSERT INTO agent_candidate_inputs VALUES (?,?,?,?,?)',
                    tuple(item[key] for key in ('candidate_artifact','job','path','artifact','sha256')))
            for item in agents.get('reviews', []):
                db.execute('INSERT INTO agent_candidate_reviews VALUES (?,?,?,?,?,?,?,?,?)',
                    tuple(item[key] for key in ('id','candidate_artifact','candidate_sha256',
                        'plan_digest','decision','reviewer','note','checks','created')))
            for item in agents.get('feedback', []):
                db.execute('INSERT INTO agent_candidate_feedback VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    tuple(item[key] for key in ('id','job','feedback_key','candidate_artifact',
                        'candidate_sha256','plan_digest','scope','assessment','actor',
                        'exact_feedback','created')))
            for item in agents.get('selections', []):
                db.execute('INSERT INTO agent_candidate_selections VALUES (?,?,?,?,?,?)',
                    tuple(item[key] for key in ('candidate_artifact','candidate_sha256',
                        'plan_digest','selected_by','receipt','created')))
            bundles = report.get('revision_bundles', {})
            for item in bundles.get('plans', []):
                db.execute('INSERT INTO revision_bundle_plans VALUES (?,?,?,?,?,?,?,?,?)',
                    tuple(item[key] for key in ('id','job','request_key','handoff_id',
                        'exact_request','plan_digest','plan','actor','created')))
            for item in bundles.get('bundles', []):
                db.execute('INSERT INTO revision_bundles VALUES (?,?,?,?,?,?,?,?,?)',
                    tuple(item[key] for key in ('id','job','submission_key','plan_id',
                        'pptx_candidate','set_digest','checks','submitted_by','created')))
            for item in bundles.get('files', []):
                db.execute('INSERT INTO revision_bundle_files VALUES (?,?,?,?,?,?,?)',
                    tuple(item[key] for key in ('bundle_id','job','role',
                        'baseline_artifact','baseline_sha256','candidate_artifact',
                        'candidate_sha256')))
            for item in bundles.get('reviews', []):
                db.execute('INSERT INTO revision_bundle_reviews VALUES (?,?,?,?,?,?,?,?,?)',
                    tuple(item[key] for key in ('id','bundle_id','job','set_digest',
                        'decision','reviewer','exact_feedback','note','created')))
            for item in bundles.get('selections', []):
                db.execute('INSERT INTO revision_bundle_selections VALUES (?,?,?,?,?,?)',
                    tuple(item[key] for key in ('bundle_id','job','set_digest',
                        'selected_by','receipt','created')))
            followons = report.get('bundle_continuations', {})
            for item in followons.get('plans', []):
                db.execute('INSERT INTO bundle_continuation_plans VALUES (?,?,?,?,?,?,?,?,?)',
                    tuple(item[key] for key in ('id','job','request_key','parent_bundle',
                        'exact_request','plan_digest','plan','actor','created')))
            for item in followons.get('candidates', []):
                db.execute('INSERT INTO bundle_continuations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    tuple(item[key] for key in ('id','job','submission_key','plan_id',
                        'pptx_artifact','pptx_sha256','slides_artifact','slides_sha256',
                        'photo_manifest_artifact','photo_manifest_sha256','set_digest',
                        'checks','submitted_by','created')))
            for item in followons.get('reviews', []):
                db.execute('INSERT INTO bundle_continuation_reviews VALUES (?,?,?,?,?,?,?,?)',
                    tuple(item[key] for key in ('id','candidate_id','job','set_digest',
                        'decision','reviewer','note','created')))
            for item in followons.get('selections', []):
                db.execute('INSERT INTO bundle_continuation_selections VALUES (?,?,?,?,?,?)',
                    tuple(item[key] for key in ('candidate_id','job','set_digest',
                        'selected_by','receipt','created')))
            from . import job_record
            job_record.add_projection(db, report)
            db.commit()
        return path.read_bytes()
