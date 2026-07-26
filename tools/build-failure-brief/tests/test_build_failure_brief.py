import json
import unittest

from build_failure_brief import parse_diagnostics, to_json_payload, to_markdown


SAMPLE_LOG = """src/main.cpp:14:9: error: use of undeclared identifier 'total'
FAILED tests/test_allocator.py::test_rejects_negative_weight - AssertionError: expected ValueError
test scheduler::handles_idle_gaps ... FAILED
thread 'scheduler::handles_idle_gaps' panicked at src/lib.rs:88: queue never drained
"""


class BuildFailureBriefTests(unittest.TestCase):
    def test_parses_compiler_and_test_failures(self) -> None:
        diagnostics = parse_diagnostics(SAMPLE_LOG)
        self.assertEqual(len(diagnostics), 4)
        self.assertEqual(diagnostics[0].subject, "src/main.cpp")
        self.assertEqual(diagnostics[0].line, 14)
        self.assertEqual(diagnostics[1].subject, "tests/test_allocator.py::test_rejects_negative_weight")
        self.assertEqual(diagnostics[3].severity, "panic")

    def test_markdown_mentions_hotspots(self) -> None:
        body = to_markdown(parse_diagnostics(SAMPLE_LOG))
        self.assertIn("# Build Failure Brief", body)
        self.assertIn("src/main.cpp", body)
        self.assertIn("scheduler::handles_idle_gaps", body)

    def test_json_payload_contains_summary(self) -> None:
        payload = json.loads(to_json_payload(parse_diagnostics(SAMPLE_LOG)))
        self.assertEqual(payload["summary"]["diagnosticCount"], 4)
        self.assertEqual(payload["summary"]["kindCounts"]["test"], 2)

    def test_parses_github_actions_annotation(self) -> None:
        log = "::error file=src/app.ts,line=18,col=7::Type mismatch in state reducer"
        diagnostics = parse_diagnostics(log)
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].subject, "src/app.ts")
        self.assertEqual(diagnostics[0].line, 18)
        self.assertEqual(diagnostics[0].column, 7)

    def test_parses_python_traceback(self) -> None:
        log = """Traceback (most recent call last):
  File "planner.py", line 88, in <module>
    main()
ValueError: invalid course weight
"""
        diagnostics = parse_diagnostics(log)
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0].kind, "exception")
        self.assertEqual(diagnostics[0].subject, "planner.py")
        self.assertEqual(diagnostics[0].severity, "ValueError")


if __name__ == "__main__":
    unittest.main()
