import copy,unittest
from orchestrator import spatial_contract as spatial,blender_host,prepared_schemas,rhino_document
from tests.test_blender_operations import scene_data
from tests.test_automatic_composition import native_document

class Tests(unittest.TestCase):
    def test_physical_conversion_and_legacy_are_explicit(self):
        value=dict(units='Inches',basis='estimated',note='Image inference; not fabrication dimensions')
        receipt=spatial.spatial_receipt(value,[[0,0,0],[10,20,30]])
        self.assertEqual(receipt['bounds_meters'],[[0,0,0],[.254,.508,.762]])
        legacy=scene_data();legacy.pop('spatial');before=copy.deepcopy(legacy)
        blender_host.scene(legacy);self.assertEqual(legacy,before)
        self.assertIsNone(spatial.spatial_receipt(None)['meters_per_unit'])
        for cap in ('blender.scene','blender.mesh_scene','rhino.document'):
            schema=prepared_schemas.document_schema(cap)
            self.assertIn('spatial',schema['required'])

    def test_invalid_or_contradictory_metadata_rejected_by_frozen_validator(self):
        ns={'__name__':'frozen'};exec(blender_host.validator_source(),ns)
        for bad in (dict(units=[],basis='estimated',note='Bad units'),dict(units='Pixels',basis='estimated',note='No real scale'),dict(units='Meters',basis='certain',note='Bad basis'),dict(units='Meters',basis='estimated',note=' ')):
            data=scene_data();data['spatial']=bad
            with self.subTest(bad=bad),self.assertRaises(ValueError):ns['scene'](data)
        data=native_document();data['spatial']['units']='Meters'
        with self.assertRaisesRegex(ValueError,'units differ'):rhino_document.validate(data)

    def test_rhino_reopen_rejects_changed_disclosure_without_rebuilding(self):
        import sys,types
        from unittest.mock import patch
        value=native_document();value['objects']=[]
        doc=types.SimpleNamespace(Objects=[])
        with patch.dict(sys.modules,{'rhinoscriptsyntax':types.SimpleNamespace(GetDocumentUserText=lambda key:'changed')}):
            self.assertIn('Spatial disclosure changed',rhino_document.verify(doc,value))
