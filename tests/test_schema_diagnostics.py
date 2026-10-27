"""Useful union diagnostics without narrowing acceptance or committing bad data."""
import copy
import unittest
from orchestrator import parameter_contracts as wire,operation_records
from tests import test_worker_tools as fixture


class Tests(unittest.TestCase):
    def test_registered_rejected_fragment_reports_its_own_fields_and_preserves_revision(self):
        case=fixture.Tests();case.setUp()
        try:
            frozen,control,_=case.admit()
            store=operation_records.Store(frozen,case.rt.db)
            record=dict(kind='page',slot=1,layout='content_cards',notes='',content=dict(
                title='Small fixture',per_page=2,items=[dict(image=None,link='',credit='')]))
            before=copy.deepcopy(store.progress())
            with self.assertRaises(ValueError) as caught:
                store.submit(dict(request_key='bad',revision=0,records=[record]),{})
            error=str(caught.exception)
            for part in ('missing label','missing body','expected one of [1, 3]','expected null'):
                self.assertIn(part,error)
            for unrelated in ('missing subtitle','missing left','missing rows','missing chart','missing fit'):
                self.assertNotIn(unrelated,error)
            self.assertEqual(store.progress(),before)
            record['content']['per_page']=1
            record['content']['items'][0].update(label='Evidence',body='Substantive synthetic finding.',link=None)
            store.submit(dict(request_key='corrected',revision=0,records=[record]),{})
            self.assertEqual(store.progress()['revision'],1)
        finally:case.tearDown()

    def test_diagnostic_tag_selection_never_changes_anyof_acceptance(self):
        tagged=dict(type='object',properties=dict(kind=dict(type='string',enum=['named']),n=dict(type='integer')),
                    required=['kind','n'],additionalProperties=False)
        general=dict(type='object',properties=dict(kind=dict(type='string'),n=dict(type='string')),
                     required=['kind','n'],additionalProperties=False)
        schema=dict(anyOf=[tagged,general])
        wire.validate(dict(kind='named',n='Valid under the other branch'),schema)
        with self.assertRaises(ValueError):wire.validate(dict(kind='named',n=None),schema)


if __name__=='__main__':unittest.main()
