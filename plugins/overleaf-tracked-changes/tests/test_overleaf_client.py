import importlib.util
import pathlib
import unittest


CLIENT_PATH = (
    pathlib.Path(__file__).parents[1]
    / "skills/overleaf-tracked-changes/scripts/overleaf_client.py"
)
SPEC = importlib.util.spec_from_file_location("overleaf_client", CLIENT_PATH)
CLIENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLIENT)


class RenderReviewTests(unittest.TestCase):
    def setUp(self):
        self.long_old = "old wording " + "x" * 100
        self.long_new = "new wording " + "y" * 100
        self.text = "line one\nline two\n" + self.long_new + "\nline four\nline five"
        position = self.text.index(self.long_new)
        self.thread_id = "a" * 24
        self.document = {
            "text": self.text,
            "version": 42,
            "ranges": {
                "changes": [
                    {
                        "id": "insert-id",
                        "op": {"p": position, "i": self.long_new},
                        "metadata": {"user_id": "user-1"},
                    },
                    {
                        "id": "delete-id",
                        "op": {"p": position, "d": self.long_old},
                        "metadata": {"user_id": "user-1"},
                    },
                    {
                        "id": "other-line",
                        "op": {"p": 0, "i": "unrelated"},
                        "metadata": {"user_id": "user-2"},
                    },
                ],
                "comments": [
                    {
                        "id": self.thread_id,
                        "op": {"p": position, "c": "selected paragraph", "t": self.thread_id},
                        "metadata": {"user_id": "user-1"},
                    }
                ],
            },
        }
        self.threads = {
            self.thread_id: {
                "messages": [
                    {
                        "user_id": "user-1",
                        "user": {"first_name": "Nicholas", "last_name": "Hallman"},
                        "content": "What are we trying to say?",
                    },
                    {
                        "user_id": "user-2",
                        "user": {"first_name": "Nathan", "last_name": "Barrymore"},
                        "content": "The raw file preserves disclosure timing.",
                    },
                ]
            }
        }

    def test_line_review_contains_full_changes_context_and_thread(self):
        output = CLIENT.render_review(
            "main.tex", self.document, self.threads, target_line=3, context=1
        )

        self.assertIn(self.long_old, output)
        self.assertIn(self.long_new, output)
        self.assertIn("Nicholas Hallman", output)
        self.assertIn("Nathan Barrymore", output)
        self.assertIn("The raw file preserves disclosure timing.", output)
        self.assertIn(">     3 |", output)
        self.assertNotIn("unrelated", output)

    def test_default_review_shows_each_change_line_and_matching_comments(self):
        output = CLIENT.render_review(
            "main.tex", self.document, self.threads, context=0
        )

        self.assertIn("=== line 1 ===", output)
        self.assertIn("=== line 3 ===", output)
        self.assertIn("COMMENT THREAD", output)

    def test_target_line_without_ranges_still_shows_source(self):
        output = CLIENT.render_review(
            "main.tex", self.document, self.threads, target_line=5, context=0
        )

        self.assertIn("0 tracked change(s), 0 comment thread(s)", output)
        self.assertIn(">     5 | line five", output)

    def test_rejects_invalid_line_and_context(self):
        with self.assertRaises(ValueError):
            CLIENT.render_review("main.tex", self.document, self.threads, target_line=0)
        with self.assertRaises(ValueError):
            CLIENT.render_review("main.tex", self.document, self.threads, context=-1)


if __name__ == "__main__":
    unittest.main()
