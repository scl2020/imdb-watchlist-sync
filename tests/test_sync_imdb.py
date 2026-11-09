import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("sync_imdb", Path(__file__).parents[1] / "scripts" / "sync_imdb.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def item(n):
    return {"id": f"tt{n:07d}", "titleText": {"text": f"Film {n}"}, "titleType": {"text": "Movie"}}


class SyncTest(unittest.TestCase):
    def test_normalize_title(self):
        self.assertEqual(sync.normalize_title(item(4))["imdb_id"], "tt0000004")
        self.assertEqual(sync.normalize_title(item(4))["genres"], [])

    def test_pagination(self):
        def fake_graph(query, vars):
            n = 0 if vars["after"] is None else 2
            return {"predefinedList": {"titleListItemSearch": {
                "total": 3,
                "edges": [{"listItem": item(x)} for x in ([1,2] if n == 0 else [3])],
                "pageInfo": {"hasNextPage": n == 0, "endCursor": "next" if n == 0 else None},
            }}}
        with patch.object(sync, "graph", side_effect=fake_graph):
            self.assertEqual(len(sync.get_watchlist("ur1234")), 3)

    def test_incomplete_does_not_pass(self):
        with patch.object(sync, "graph", return_value={"predefinedList": {"titleListItemSearch": {
            "total": 5, "edges": [{"listItem": item(1)}],
            "pageInfo": {"hasNextPage": False, "endCursor": None}
        }}}):
            with self.assertRaisesRegex(RuntimeError, "Incomplete"):
                sync.get_watchlist("ur1234")

    def test_safety_floor(self):
        with self.assertRaisesRegex(RuntimeError, "safety floor"):
            sync.check_safety([{}] * 999, None)

    def test_drop_protection(self):
        with self.assertRaisesRegex(RuntimeError, "Suspicious drop"):
            sync.check_safety([{}] * 1010, {"items": [{}] * 1380})


if __name__ == "__main__":
    unittest.main()
