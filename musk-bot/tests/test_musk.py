"""Run: python -m unittest discover -s tests -v   (no API key or network needed)"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from musk import handle_activity, make_activity  # noqa: E402
from musk.ado import AdoClient  # noqa: E402
from musk.agent import ClaudeBrain, OfflineBrain, route  # noqa: E402

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "activity_mention.json"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ado = AdoClient(live=False, out_dir=Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def ask(self, text, brain=None, **kw):
        return handle_activity(make_activity(text, **kw), brain=brain or OfflineBrain(),
                               ctx_kwargs={"ado": self.ado})


class Routing(Base):
    def test_intents(self):
        self.assertEqual(route("what's the takeaway from this meeting"), "summarize")
        self.assertEqual(route("give me the MoM"), "summarize")
        self.assertEqual(route("create a few ADO items for these topics"), "ado")
        self.assertEqual(route("add a wiki page to cover these ideas"), "wiki")
        self.assertEqual(route("hello"), "help")

    def test_quiet_without_mention(self):
        self.assertIsNone(self.ask("what's the takeaway from this meeting"))

    def test_real_teams_activity_shape(self):
        reply = handle_activity(json.loads(SAMPLE.read_text()), brain=OfflineBrain(),
                                ctx_kwargs={"ado": self.ado})
        self.assertIn("Decisions", reply["text"])
        self.assertEqual(reply["recipient"]["name"], "Priya Nair")


class Offline(Base):
    def test_summary(self):
        text = self.ask("@musk what's the takeaway from this meeting")["text"]
        self.assertIn("range selector", text)
        self.assertIn("Action items", text)

    def test_ado_from_chat_ideas_is_dry_run(self):
        text = self.ask("@musk, create a few ADO items for these topics")["text"]
        self.assertIn("3 work items", text)
        self.assertIn("Dry run", text)
        files = sorted(Path(self.tmp.name).glob("*-workitem-*.json"))
        self.assertEqual(len(files), 3)
        req = json.loads(files[0].read_text())
        self.assertIn("_apis/wit/workitems/$User%20Story", req["url"])
        self.assertIn("milestone-devops/Asgard", req["url"])

    def test_ado_with_inline_topics(self):
        text = self.ask("@musk create tasks for crawler retries, GA4 nightly import and alert thresholds")["text"]
        self.assertIn("Task: Crawler retries", text)
        self.assertIn("3 work items", text)

    def test_wiki(self):
        text = self.ask("@musk add a wiki page to cover these ideas")["text"]
        self.assertIn("/Ideas/", text)
        md = next(Path(self.tmp.name).glob("*.md")).read_text()
        self.assertIn("booking-funnel health score", md)


def tool_use(id_, name, input_):
    return NS(type="tool_use", id=id_, name=name, input=input_)


class FakeClient:
    """Scripted stand-in for anthropic.Anthropic() to test the tool loop offline."""

    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.scripted.pop(0)


class ClaudeLoop(Base):
    def test_tool_loop_creates_items(self):
        client = FakeClient([
            NS(stop_reason="tool_use", content=[tool_use("t1", "get_recent_chat", {"limit": 10})]),
            NS(stop_reason="tool_use", content=[tool_use("t2", "create_ado_work_items", {"items": [
                {"type": "User Story", "title": "Self-serve SEO report downloads", "description": "x",
                 "acceptance_criteria": "- downloadable PDF", "tags": ["musk"]}]})]),
            NS(stop_reason="end_turn", content=[NS(type="text", text="Created 1 item (dry run).")]),
        ])
        brain = ClaudeBrain.__new__(ClaudeBrain)
        brain.client, brain.max_turns = client, 8
        reply = self.ask("@musk create ADO items for these topics", brain=brain)
        self.assertEqual(reply["text"], "Created 1 item (dry run).")
        self.assertEqual(client.calls[0]["model"], "claude-opus-5-5")
        msgs = client.calls[-1]["messages"]  # the loop appends to one list
        tool_result = next(c for m in msgs if m["role"] == "user" and isinstance(m["content"], list)
                           for c in m["content"] if c.get("tool_use_id") == "t1")
        self.assertIn("client portal", tool_result["content"])
        self.assertEqual(len(list(Path(self.tmp.name).glob("*-workitem-*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
