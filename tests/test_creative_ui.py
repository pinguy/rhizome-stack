"""Run the actual MiniMax UI handlers against a tiny DOM fixture in Node."""
import importlib.util
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


@unittest.skipUnless(NODE, 'Node is required for creative JavaScript checks')
class CreativeUITest(unittest.TestCase):
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
  document: {querySelector: get, createElement: element},
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
  assert.ok(get('#status').textContent.includes(hostile));
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
