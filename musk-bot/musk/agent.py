"""The @musk brain.

ClaudeBrain: Claude decides what the user wants and calls tools (read transcript,
read chat, create ADO work items, create a wiki page). Needs ANTHROPIC_API_KEY
(or an `ant auth login` profile).

OfflineBrain: a keyword router with canned logic, so the prototype runs end to end
with no credentials at all. It shows the routing, not the intelligence.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from .ado import AdoClient
from .sources import SampleMeetingSource
from .teams import Mention

MODEL = os.getenv("MUSK_MODEL", "claude-opus-5-5")

SYSTEM_PROMPT = """You are @musk, a work assistant inside Microsoft Teams for Milestone Internet Marketing.
People @mention you in group chats and meeting chats. You can:
1. Summarize a meeting: read the transcript and give takeaways, minutes of meeting (MoM), decisions,
   action items (owner + due date when stated) and risks.
2. Create Azure DevOps work items in org {org}, project {project}.
3. Create a page in the {project} project wiki.

How to work:
- Use the tools to read the meeting transcript and recent chat before answering; "this meeting", "these topics"
  and "these ideas" refer to that context.
- For work items: one item per distinct topic, a crisp imperative title, a description that says why,
  acceptance criteria as a short list, tag "musk". Use "User Story" unless the user asks for Task or Bug.
- For wiki pages: a clear path such as /Ideas/<Short-Title>, a Markdown page with a one-line summary,
  sections, and a "Source" line naming the meeting or chat.
- Only state facts from the transcript or chat. If the transcript is empty, say so and offer to summarize the chat.
- Reply in Teams-friendly Markdown, short: headings, bullets, no tables wider than 4 columns.
- After creating anything, list what was created with its link, or say it was a dry run.
"""

TOOLS = [
    {
        "name": "get_meeting_transcript",
        "description": "Return the transcript of the Teams meeting this chat belongs to, as 'Speaker: text' lines. "
                       "Empty string if there is no transcript.",
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "get_recent_chat",
        "description": "Return the most recent messages in this Teams chat (oldest first) as JSON.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "How many messages, 1-50."}},
            "required": ["limit"], "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "create_ado_work_items",
        "description": "Create one or more Azure DevOps work items. Returns ids and links (or dry-run file paths).",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["User Story", "Task", "Bug", "Feature"]},
                            "title": {"type": "string"},
                            "description": {"type": "string", "description": "HTML or plain text."},
                            "acceptance_criteria": {"type": "string"},
                            "tags": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["type", "title", "description", "acceptance_criteria", "tags"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["items"], "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "create_wiki_page",
        "description": "Create a new page in the project wiki. Fails if the page already exists.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Wiki path, e.g. /Ideas/Client-Portal"},
                "content": {"type": "string", "description": "Full Markdown content of the page."},
            },
            "required": ["path", "content"], "additionalProperties": False,
        },
        "strict": True,
    },
]


@dataclass
class Context:
    mention: Mention
    source: SampleMeetingSource = field(default_factory=SampleMeetingSource)
    ado: AdoClient = field(default_factory=AdoClient)


def run_tool(name: str, args: dict, ctx: Context) -> str:
    if name == "get_meeting_transcript":
        return ctx.source.get_transcript(ctx.mention.meeting_id) or "(no transcript available)"
    if name == "get_recent_chat":
        return json.dumps(ctx.source.get_chat_history(ctx.mention.conversation_id, int(args.get("limit", 20))))
    if name == "create_ado_work_items":
        return json.dumps(ctx.ado.create_work_items(args["items"]))
    if name == "create_wiki_page":
        return json.dumps(ctx.ado.create_wiki_page(args["path"], args["content"]))
    raise ValueError(f"unknown tool {name}")


class ClaudeBrain:
    def __init__(self, client=None, max_turns: int = 8):
        import anthropic  # imported here so the offline mode needs no install

        self.anthropic = anthropic
        self.client = client or anthropic.Anthropic()
        self.max_turns = max_turns

    def handle(self, ctx: Context) -> str:
        system = SYSTEM_PROMPT.format(org=ctx.ado.org, project=ctx.ado.project)
        messages = [{"role": "user", "content": f"{ctx.mention.user_name} says: {ctx.mention.text}"}]
        for _ in range(self.max_turns):
            response = self.client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=system,
                tools=TOOLS,
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
                # If a safety classifier declines, the API retries on a fallback model in the same call.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=messages,
            )
            if response.stop_reason == "refusal":
                return "Sorry, I can't help with that one."
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "pause_turn":
                continue
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                return "\n".join(b.text for b in response.content if b.type == "text").strip()
            results = []
            for tu in tool_uses:
                try:
                    results.append({"type": "tool_result", "tool_use_id": tu.id,
                                    "content": run_tool(tu.name, tu.input, ctx)})
                except Exception as e:  # report tool failures back to Claude
                    results.append({"type": "tool_result", "tool_use_id": tu.id,
                                    "content": f"Error: {e}", "is_error": True})
            messages.append({"role": "user", "content": results})
        return "I ran out of steps on that one. Try a narrower ask."


# ---------------------------------------------------------------------------
# Offline brain: no API key needed. Deterministic, deliberately simple.
# ---------------------------------------------------------------------------
INTENTS = [
    ("wiki", re.compile(r"\bwiki\b|\bpage\b|\bdocument (this|these)\b", re.I)),
    ("ado", re.compile(r"\bado\b|work ?items?|\btickets?\b|\bstor(y|ies)\b|\btasks?\b|\bbugs?\b|backlog", re.I)),
    ("summarize", re.compile(r"takeaway|summar|minutes|\bmom\b|recap|notes|action items|what happened", re.I)),
]


def route(text: str) -> str:
    for name, pattern in INTENTS:
        if pattern.search(text):
            return name
    return "help"


class OfflineBrain:
    def handle(self, ctx: Context) -> str:
        intent = route(ctx.mention.text)
        return getattr(self, f"_{intent}")(ctx)

    def _lines(self, ctx):
        transcript = ctx.source.get_transcript(ctx.mention.meeting_id)
        return [l for l in transcript.splitlines() if l.strip()]

    def _summarize(self, ctx) -> str:
        lines = self._lines(ctx)
        if not lines:
            return "I couldn't find a transcript for this meeting. Turn on transcription and ask again."
        decisions = [l for l in lines if re.search(r"\b(decid|decision|agreed|let's park)", l, re.I)]
        actions = [l for l in lines if re.search(r"\b(I will|action item|can you own|I'll draft|will target)", l, re.I)]
        risks = [l for l in lines if re.search(r"\b(risk|must ship|dropped|times out)", l, re.I)]
        speakers = sorted({l.split(":", 1)[0] for l in lines})
        out = ["**Meeting takeaways** (offline mode: keyword extraction, not Claude)", "",
               f"Attendees heard: {', '.join(speakers)}", "", "**Decisions**"]
        out += [f"- {d}" for d in decisions] or ["- none detected"]
        out += ["", "**Action items**"] + ([f"- {a}" for a in actions] or ["- none detected"])
        out += ["", "**Risks / issues**"] + ([f"- {r}" for r in risks] or ["- none detected"])
        return "\n".join(out)

    def _topics(self, ctx) -> list[str]:
        text = ctx.mention.text
        # Topics typed in the message: "for X, Y and Z" or bullet lines
        m = re.search(r"\bfor (?:these topics:?|the following:?)?\s*(.+)$", text, re.I | re.S)
        if m and not re.fullmatch(r"\s*(these|those|the) (topics|ideas|items)\s*\??", m.group(1), re.I):
            parts = re.split(r"\n[-*]\s*|,\s*|\band\b|;", m.group(1))
            topics = [p.strip(" .?") for p in parts if len(p.strip(" .?")) > 3]
            if topics:
                return topics
        # Otherwise numbered ideas in recent chat, then action items in the transcript
        for msg in ctx.source.get_chat_history(ctx.mention.conversation_id):
            found = re.findall(r"\d\)\s*([^,0-9][^)]*?)(?=,\s*\d\)|\.$|$)", msg["text"])
            if found:
                return [f.strip(" .") for f in found]
        return [l.split(":", 1)[1].strip() for l in self._lines(ctx)
                if re.search(r"\b(I will|action item)", l, re.I)]

    def _ado(self, ctx) -> str:
        topics = self._topics(ctx)
        if not topics:
            return "Which topics should I turn into work items?"
        wtype = "Bug" if re.search(r"\bbugs?\b", ctx.mention.text, re.I) else (
            "Task" if re.search(r"\btasks?\b", ctx.mention.text, re.I) else "User Story")
        items = [{"type": wtype, "title": t[:1].upper() + t[1:], "tags": ["musk"],
                  "description": f"Raised by {ctx.mention.user_name} in Teams.", "acceptance_criteria": ""}
                 for t in topics]
        results = ctx.ado.create_work_items(items)
        mode = "Dry run, nothing sent to ADO" if results and results[0].get("dry_run") else "Created in ADO"
        lines = [f"**{len(results)} work items** ({mode}; {ctx.ado.org}/{ctx.ado.project})", ""]
        for r in results:
            where = r.get("url") or r.get("saved_to", "")
            lines.append(f"- {r['type']}: {r['title']}  \n  {where}")
        return "\n".join(lines)

    def _wiki(self, ctx) -> str:
        topics = self._topics(ctx)
        title = "Ideas from " + ("meeting" if ctx.mention.meeting_id else "chat")
        body = [f"# {title}", "", f"_Requested by {ctx.mention.user_name} via @musk._", "", "## Ideas", ""]
        body += [f"- {t}" for t in topics] or ["- (no ideas found)"]
        body += ["", "## Source", "", "Teams conversation " + ctx.mention.conversation_id]
        r = ctx.ado.create_wiki_page("/Ideas/" + re.sub(r"\W+", "-", title).strip("-"), "\n".join(body))
        mode = "Dry run, saved locally" if r.get("dry_run") else "Created"
        return f"**Wiki page {r['path']}** ({mode})\n{r.get('url') or r.get('saved_to')}"

    def _help(self, ctx) -> str:
        return ("Hi, I'm @musk. Try:\n- `@musk what's the takeaway from this meeting`\n"
                "- `@musk create ADO items for these topics`\n- `@musk add a wiki page to cover these ideas`")


def make_brain(mode: str | None = None):
    mode = mode or os.getenv("MUSK_BRAIN") or ("claude" if os.getenv("ANTHROPIC_API_KEY") else "offline")
    return ClaudeBrain() if mode == "claude" else OfflineBrain()
