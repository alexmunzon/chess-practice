#!/usr/bin/env python3
"""Offline exit-status regression; no model inference, images or hardware required."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPT = Path(__file__).with_name('recognition_whole.py')
RUN_REPORT = """
import importlib.util, json, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('whole_diagnostic', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.finish_report(json.load(sys.stdin), Path(sys.argv[2]))
"""


class NumericalGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('whole_diagnostic_test', SCRIPT)
        cls.diagnostic = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.diagnostic)

    def assert_report_exit(self, numerical, expected_code):
        # Photo scores can look good while the separate numerical gate fails.
        report = {'numericalValidation': numerical,
                  'results': [{'rawExactBoard': True, 'acceptedExactBoard': True}]}
        with tempfile.TemporaryDirectory(prefix='chess-numerical-gate-') as output:
            result = subprocess.run(
                [sys.executable, '-B', '-c', RUN_REPORT, str(SCRIPT), output],
                input=json.dumps(report), text=True, capture_output=True)
            self.assertEqual(result.returncode, expected_code, result.stderr)
            self.assertEqual(json.loads(result.stdout), report)
            self.assertEqual(json.loads((Path(output) / 'report.json').read_text()), report)

    def test_failed_numerical_gate_exits_one_and_keeps_diagnostic(self):
        self.assert_report_exit(
            {'passed': False, 'squaresMatched': 192, 'totalSquares': 192,
             'logitsOutsideTolerance': 1, 'totalLogits': 2496}, 1)

    def test_passed_numerical_gate_exits_zero(self):
        self.assert_report_exit(
            {'passed': True, 'squaresMatched': 192, 'totalSquares': 192,
             'logitsOutsideTolerance': 0, 'totalLogits': 2496}, 0)

    def test_truthy_nonboolean_is_not_a_pass(self):
        self.assert_report_exit({'passed': 'false'}, 1)

    def test_required_gpu_run_removes_inherited_cpu_diagnostic_flag(self):
        payload = {'computeUnits': 'CPU_AND_GPU', 'allowLowPrecisionAccumulationOnGPU': False,
                   'logits': [1, 2, 3]}
        with tempfile.TemporaryDirectory(prefix='chess-native-profile-') as directory:
            root = Path(directory)
            output = root / 'native.json'
            output.write_text(json.dumps(payload))
            cases = [(root / 'input.f32', output)]
            with mock.patch.dict(self.diagnostic.os.environ, {'CHESS_COREML_CPU_DIAGNOSTIC': '1'}):
                with mock.patch.object(self.diagnostic.subprocess, 'run') as run:
                    self.assertEqual(self.diagnostic.run_required_gpu(root, cases), [payload])
                    run.assert_called_once()
                    self.assertNotIn('CHESS_COREML_CPU_DIAGNOSTIC', run.call_args.kwargs['env'])
                    self.assertIs(run.call_args.kwargs['check'], True)
                    self.assertEqual(run.call_args.args[0][-2:], [str(cases[0][0]), str(output)])
                self.assertEqual(self.diagnostic.os.environ['CHESS_COREML_CPU_DIAGNOSTIC'], '1')

    def test_every_native_output_must_explicitly_match_required_profile(self):
        valid = {'computeUnits': 'CPU_AND_GPU', 'allowLowPrecisionAccumulationOnGPU': False}
        invalid = [
            {**valid, 'computeUnits': 'CPU_ONLY_DIAGNOSTIC'},
            {**valid, 'allowLowPrecisionAccumulationOnGPU': True},
            {**valid, 'allowLowPrecisionAccumulationOnGPU': 0},
            {'computeUnits': 'CPU_AND_GPU'},
            {'allowLowPrecisionAccumulationOnGPU': False},
        ]
        with tempfile.TemporaryDirectory(prefix='chess-native-profile-') as directory:
            root = Path(directory)
            first, second = root / 'first.json', root / 'second.json'
            first.write_text(json.dumps(valid))
            for payload in invalid:
                with self.subTest(payload=payload):
                    second.write_text(json.dumps(payload))
                    with mock.patch.object(self.diagnostic.subprocess, 'run'):
                        with self.assertRaisesRegex(ValueError, 'required CPU_AND_GPU profile: second.json'):
                            self.diagnostic.run_required_gpu(root, [(root/'first.f32', first), (root/'second.f32', second)])
                    self.assertFalse((root / 'report.json').exists())


if __name__ == '__main__':
    unittest.main()
