from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch  # noqa: E402


FIXTURE = Path(__file__).parent / "fixtures" / "arxiv-results.json"


class FetchTests(unittest.TestCase):
    def test_normalizes_ids(self) -> None:
        self.assertEqual(
            fetch.normalize_arxiv_id("https://arxiv.org/pdf/cs/0112017v3.pdf"),
            ("cs/0112017v3", "cs/0112017", 3),
        )
        self.assertEqual(
            fetch.normalize_arxiv_id("arXiv:2402.00001v2"),
            ("2402.00001v2", "2402.00001", 2),
        )

    def test_deduplicates_sorts_and_hashes_stably(self) -> None:
        sources = fetch.load_fixture(FIXTURE)
        first = fetch.deduplicate_and_select(sources, limit=10)
        second = fetch.deduplicate_and_select(sources, limit=10)

        self.assertEqual([paper["arxiv_id"] for paper in first], ["2402.00001v2", "2401.00002v1", "cs/0112017v3"])
        self.assertEqual(first, second)
        for paper in first:
            without_hash = {key: value for key, value in paper.items() if key != "input_hash"}
            expected = hashlib.sha256(
                json.dumps(without_hash, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            self.assertEqual(paper["input_hash"], expected)

    def test_fixture_cli_writes_papers_and_upserts_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "papers.json"
            database = root / "triage.db"
            exit_code = fetch.main(
                ["fixture smoke", "--fixture", str(FIXTURE), "--output", str(output), "--db", str(database)]
            )
            self.assertEqual(exit_code, 0)
            papers = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(papers), 3)
            self.assertEqual(fetch.main(["fixture smoke", "--fixture", str(FIXTURE), "--output", str(output), "--db", str(database)]), 0)


if __name__ == "__main__":
    unittest.main()
