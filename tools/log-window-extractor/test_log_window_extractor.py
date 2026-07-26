from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

from log_window_extractor import collect_matches, resolve_window, summarize


class LogWindowExtractorTests(unittest.TestCase):
    def test_anchor_window_and_keyword_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            first_log = Path(tmp_dir) / "app.log"
            second_log = Path(tmp_dir) / "worker.log"
            first_log.write_text(
                "\n".join(
                    [
                        "2026-07-01T13:58:00Z INFO boot complete",
                        "2026-07-01T14:06:30Z ERROR checkout timeout for region us-east",
                        "2026-07-01T14:21:00Z INFO recovery confirmed",
                    ]
                ),
                encoding="utf-8",
            )
            second_log.write_text(
                "\n".join(
                    [
                        "2026-07-01T14:01:00Z WARN cache miss burst detected",
                        "2026-07-01T14:08:00Z INFO worker backlog drained",
                    ]
                ),
                encoding="utf-8",
            )

            args = argparse.Namespace(
                start=None,
                end=None,
                anchor="2026-07-01T14:05:00Z",
                before_minutes=10,
                after_minutes=10,
            )
            start, end = resolve_window(args)
            matches = collect_matches([first_log, second_log], start, end)
            summary = summarize(matches, start, end)

            self.assertEqual(len(matches), 4)
            self.assertEqual(matches[0].source, "app.log")
            self.assertEqual(summary["files_touched"], {"app.log": 2, "worker.log": 2})
            self.assertEqual(summary["keyword_counts"], {"error": 1, "timeout": 1, "warn": 1})
            self.assertEqual(summary["largest_gap_seconds"], 330)


if __name__ == "__main__":
    unittest.main()
