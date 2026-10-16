"""Run the actual MiniMax UI handlers against a tiny DOM fixture in Node."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


@unittest.skipUnless(NODE, 'Node is required for creative JavaScript checks')
class CreativeUITest(unittest.TestCase):
    def test_minimax_lists_every_writer_and_exposes_per_track_delete(self):
        source = (ROOT / 'components/creative/minimax-music/app.py').read_text()
        self.assertIn("const available=[...new Set(ms)].map(writerEntry);", source)
        self.assertIn("['Recommended','Cloud','Local · uses VRAM']", source)
        self.assertIn("class=\"track-delete\"", source)
        self.assertIn("fetch('/api/delete'", source)
        self.assertIn('return self._delete(body.get("filename", ""))', source)

    def test_wan_frontend_syntax_and_independent_controls(self):
        module_dir = ROOT / 'components/creative/wan-video-desk'
        for name in ('app.js', 'sw.js'):
            result = subprocess.run([NODE, '--check', str(module_dir / 'static' / name)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        page = (module_dir / 'static/index.html').read_text()
        script = (module_dir / 'static/app.js').read_text()
        self.assertIn('name="videoMode"', page)
        self.assertIn('name="videoModel"', page)
        self.assertIn('video_model: videoModel, mode, reference_image_id: referenceId', script)

    def test_qwen_gallery_prunes_stale_records_and_deletes_via_trash(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            output = temporary / 'output'
            state = temporary / 'state'
            output.mkdir()
            image = output / 'kept.png'
            image.write_bytes(b'png')
            module_dir = ROOT / 'components/creative/qwen-image-desk'
            with patch.dict(os.environ, {
                'COMFY_OUTPUT': str(output),
                'QWEN_DESK_STATE': str(state),
                'RHIZOME_STACK_ROOT': str(temporary / 'stack'),
            }):
                sys.path.insert(0, str(module_dir))
                try:
                    spec = importlib.util.spec_from_file_location('qwen_gallery_test', module_dir / 'app.py')
                    qwen = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(qwen)
                finally:
                    sys.path.remove(str(module_dir))
            jobs = qwen.JobQueue(qwen.ComfyEngine())
            jobs.assets = [
                {'id': 'asset-kept', 'relative_path': 'kept.png'},
                {'id': 'asset-stale', 'relative_path': 'missing.png'},
            ]
            snapshot = jobs.snapshot()
            self.assertEqual([item['id'] for item in snapshot['assets']], ['asset-kept'])
            with patch.object(qwen.subprocess, 'run', return_value=subprocess.CompletedProcess(['gio'], 0, '', '')) as trashed:
                self.assertEqual(jobs.delete_asset('asset-kept'), {'deleted': True, 'id': 'asset-kept'})
            trashed.assert_called_once_with(['gio', 'trash', str(image)], capture_output=True,
                                            text=True, timeout=30, check=False)
            self.assertEqual(jobs.assets, [])
            jobs.assets = [{'id': 'asset-escape', 'relative_path': '../outside.png'}]
            with self.assertRaisesRegex(ValueError, 'outside the creative output directory'):
                jobs.delete_asset('asset-escape')
            script = (module_dir / 'static/app.js').read_text()
            self.assertIn('data-action="delete"', script)
            self.assertIn('/api/image-studio/delete', script)

    def test_titles_filenames_and_errors_are_rendered_as_text(self):
        spec = importlib.util.spec_from_file_location('music_ui_test', ROOT / 'components/creative/minimax-music/app.py')
        music = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(music)
        script = music.INDEX_HTML.split('<script>', 1)[1].split('</script>', 1)[0]
        harness = r'''
const vm = require('node:vm');
const assert = require('node:assert/strict');
const script = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
function element() {
  return {value: '60', textContent: '', innerHTML: '', children: [], style: {}, dataset: {},
    classList: {add(){}, remove(){}}, addEventListener(){}, focus(){},
    querySelector(){return element();}, querySelectorAll(){return [];},
    appendChild(child){this.children.push(child);}};
}
const elements = new Map();
const get = selector => {if (!elements.has(selector)) elements.set(selector, element()); return elements.get(selector);};
let payload = {};
const context = vm.createContext({
  document: {querySelector: get, querySelectorAll(){return [];}, createElement: element, addEventListener(){}},
  window: {scrollTo(){}}, navigator: {},
  setInterval(){return 1;}, clearInterval(){}, setTimeout(){}, alert(){}, confirm(){return false;},
  fetch: async url => ({ok: true, json: async () => url.startsWith('/api/status') ? payload : {models:[], items:[]}}),
});
vm.runInContext(script, context);
(async () => {
  await new Promise(resolve => setImmediate(resolve));
  const hostile = '<img src=x onerror="boom()"> & a "quote"';
  payload = {state:'done', elapsed:1, meta:{title:hostile, seed:42}, filename:hostile,
             path:hostile, audio_url:'/api/audio?filename=song.mp3'};
  await vm.runInContext('poll("synthetic")', context);
  const rendered = get('#status').innerHTML;
  assert.ok(rendered.includes('&lt;img'), rendered);
  assert.ok(!rendered.includes('<img'), rendered);
  assert.ok(!rendered.includes('data-copy="<'), rendered);
  payload = {state:'error', elapsed:2, error:hostile};
  await vm.runInContext('poll("synthetic")', context);
  const failed = get('#status').innerHTML;
  assert.ok(failed.includes('&lt;img'), failed);
  assert.ok(!failed.includes('<img'), failed);
  context.fetch = async () => ({ok:true, json:async()=>({items:[{
    filename:hostile, path:hostile, url:'/api/audio?filename=song.mp3', recipe:true
  }]})});
  await vm.runInContext('loadHist()', context);
  const row = get('#hist').children.at(-1).innerHTML;
  assert.ok(row.includes('&lt;img'), row);
  assert.ok(!row.includes('<img'), row);
})().catch(error => {console.error(error); process.exitCode=1;});
'''
        result = subprocess.run([NODE, '-e', harness], input=json.dumps(script), capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
