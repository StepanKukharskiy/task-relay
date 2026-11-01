"""Read-only historical projection, with exact state and artifact identities."""
from unittest.mock import patch
from tests import test_same_canvas_rerun as fixtures
from task_relay import desktop_workspace as workspace,desktop_file_changes,desktop_node_files


class CanvasReadTests(fixtures.SameCanvas):
    def test_versions_do_not_build_unused_context_panels(self):
        command,_=self.command();new=fixtures.runs.start(command)['run']
        self.rt.tick(new);attempt=self.rt.task(new,'second')['latest'];self.factory.finish(attempt);self.rt.tick(new)
        state=workspace.ReadState(self.state.db,self.paths)
        before=[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts')]
        full=workspace._view(state,new,self.paths,project_canvas=False)
        with patch.object(desktop_file_changes,'bindings',wraps=desktop_file_changes.bindings) as bindings:
            summary=workspace._view(state,new,self.paths,project_canvas=False,summary=True)
            self.assertEqual(bindings.call_count,0)
            self.assertEqual(summary['tasks'],full['tasks'])
            self.assertEqual(summary['latest_outputs'],full['latest_outputs'])
            view=workspace.detail(self.run,self.paths)
            self.assertEqual(bindings.call_count,1,'Only the owning canvas needs attachment inspection')
        self.assertEqual(next(t for t in view['tasks'] if t['id']=='second')['versions'][-1]['attempt'],attempt)
        self.assertEqual(before,[tuple(r) for r in self.state.db.execute('SELECT * FROM production_attempts')])

    def test_selected_file_metadata_is_not_limited_to_recent_picker_entries(self):
        first=None
        for index in range(205):
            item=dict(artifact='fixture-'+str(index),name=str(index)+'.png',sha256='a'*64)
            if first is None:first=item
            self.rt.event(None,None,None,'node_file_selected',item)
        self.state.db.commit()
        self.assertNotIn(first,desktop_node_files.dispatch('node-files',{})['files'])
        self.assertEqual(desktop_node_files.dispatch('node-files',{'artifacts':[first['artifact']]})['files'],[first])
