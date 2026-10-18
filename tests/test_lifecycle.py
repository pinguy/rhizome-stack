"""Uninstall must be complete, ownership-checked and custom-root aware."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UninstallTest(unittest.TestCase):
    def fixture(self, root: Path):
        home = root / 'home'
        config_home = root / 'config'
        state_home = root / 'state'
        stack = root / 'custom stack'
        unit_root = config_home / 'systemd/user'
        config_root = config_home / 'rhizome-stack'
        for directory in (home, state_home, stack / 'systemd', stack / 'manifests',
                          unit_root, config_root):
            directory.mkdir(parents=True, exist_ok=True)
        (stack / 'VERSION').write_text('fixture\n')
        shutil.copy2(ROOT / 'manifests/components.json', stack / 'manifests/components.json')
        shutil.copy2(ROOT / 'manifests/systemd-units.json', stack / 'manifests/systemd-units.json')
        units = json.loads((ROOT / 'manifests/systemd-units.json').read_text())['units']
        for unit in units:
            template = (ROOT / 'systemd' / unit).read_text()
            shutil.copy2(ROOT / 'systemd' / unit, stack / 'systemd' / unit)
            rendered = template.replace('@@STACK_ROOT@@', str(stack)).replace('@@HOME@@', str(home))
            rendered = rendered.replace(str(home / '.config/rhizome-stack/stack.env'),
                                        str(config_root / 'stack.env'))
            (unit_root / unit).write_text(rendered)
        (config_root / 'stack.env').write_text('RHIZOME_STACK_ROOT=' + shlex.quote(str(stack)) + '\n')
        fake_bin = root / 'bin'
        fake_bin.mkdir()
        systemctl = fake_bin / 'systemctl'
        systemctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$SYSTEMCTL_LOG"\n')
        systemctl.chmod(0o755)
        env = os.environ.copy()
        env.update({
            'HOME': str(home), 'XDG_CONFIG_HOME': str(config_home),
            'XDG_STATE_HOME': str(state_home), 'PATH': str(fake_bin) + ':' + env['PATH'],
            'SYSTEMCTL_LOG': str(root / 'systemctl.log'),
        })
        env.pop('RHIZOME_STACK_ROOT', None)
        return env, stack, unit_root, config_root, state_home, units

    def test_dry_run_complete_uninstall_and_idempotent_repeat(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env, stack, unit_root, config_root, state_home, units = self.fixture(root)
            dry = subprocess.run([str(ROOT / 'uninstall.sh'), '--dry-run'], env=env,
                                 text=True, capture_output=True)
            self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
            self.assertIn(f'DRY RUN owned units ({len(units)})', dry.stdout)
            self.assertTrue(stack.is_dir())
            self.assertTrue(all((unit_root / unit).is_file() for unit in units))

            restored = 'open-webui.service'
            (unit_root / (restored + '.before-rhizome-stack')).write_text('owner unit\n')
            first = subprocess.run([str(ROOT / 'uninstall.sh')], env=env,
                                   text=True, capture_output=True)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertFalse(stack.exists())
            self.assertFalse(config_root.exists())
            self.assertEqual((unit_root / restored).read_text(), 'owner unit\n')
            self.assertTrue(all(not (unit_root / unit).exists() for unit in units if unit != restored))
            archives = list((state_home / 'rhizome-stack').glob('removed-*'))
            self.assertEqual(len(archives), 1)
            self.assertEqual(sorted(path.name for path in (archives[0] / 'units').iterdir()),
                             sorted(units))

            first_systemctl_log = (root / 'systemctl.log').read_text()
            second = subprocess.run([str(ROOT / 'uninstall.sh')], env=env,
                                    text=True, capture_output=True)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual((unit_root / restored).read_text(), 'owner unit\n')
            self.assertIn('already uninstalled', second.stdout)
            self.assertEqual(list((state_home / 'rhizome-stack').glob('removed-*')), archives)
            self.assertEqual((root / 'systemctl.log').read_text(), first_systemctl_log)

    def test_modified_unit_blocks_every_uninstall_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env, stack, unit_root, config_root, state_home, units = self.fixture(root)
            modified = unit_root / 'wan-video-desk.service'
            modified.write_text('owner changed this unit\n')
            result = subprocess.run([str(ROOT / 'uninstall.sh')], env=env,
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(str(modified), result.stderr)
            self.assertTrue(stack.is_dir())
            self.assertTrue(config_root.is_dir())
            self.assertFalse((state_home / 'rhizome-stack').exists())
            self.assertTrue(all((unit_root / unit).is_file() for unit in units))


if __name__ == '__main__':
    unittest.main()
