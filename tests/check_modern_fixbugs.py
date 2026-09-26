"""Assemble an isolated fixBugs=1 negative control; requires make rom first."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.mdplus_builder.common import BUILD
from tools.mdplus_builder.modern import PREPARED_MODERN_DIR


class FixBugsRejectionTests(unittest.TestCase):
    def test_actual_assembler_rejects_unsupported_layout(self):
        with tempfile.TemporaryDirectory(prefix='reject-fixbugs-', dir=BUILD) as directory:
            work = Path(directory) / 'source'
            shutil.copytree(PREPARED_MODERN_DIR, work, ignore=shutil.ignore_patterns('.git'))
            path = work / 's2.asm'
            text = path.read_text()
            self.assertEqual(text.count('fixBugs = 0'), 1)
            path.write_text(text.replace('fixBugs = 0', 'fixBugs = 1'))
            result = subprocess.run(['lua', 'modern_build.lua'], cwd=work, capture_output=True, text=True)
            log = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, log)
            self.assertIn('Unexpected sndDriverInput footprint', log)
            print(f'fixBugs=1 rejected: assembler exit {result.returncode}; '
                  'Unexpected sndDriverInput footprint')


if __name__ == '__main__':
    unittest.main(verbosity=2)
