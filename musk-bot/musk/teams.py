"""Minimal Teams Activity helpers.

In production the Microsoft 365 Agents SDK (or Teams SDK) parses and authenticates
activities for you. This module only does what the prototype needs: pull the
user's request out of an @mention message and shape a reply activity.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

AT_TAG = re.compile(r"<at>.*?</at>", re.IGNORECASE | re.DOTALL)
HTML_TAG = re.compile(r"<[^>]+>")


@dataclass
class Mention:
    text: str               # the request with the @musk mention removed
    user_name: str
    conversation_id: str
    conversation_type: str  # personal | groupChat | channel
    meeting_id: str | None  # set when the chat belongs to a Teams meeting
    mentioned_bot: bool


def parse_activity(activity: dict, bot_name: str = "musk") -> Mention:
    raw = activity.get("text", "") or ""
    mentioned = any(
        e.get("type") == "mention"
        and (e.get("mentioned", {}).get("name", "").lower() == bot_name.lower()
             or e.get("mentioned", {}).get("id") == activity.get("recipient", {}).get("id"))
        for e in activity.get("entities", []) or []
    )
    # Also accept a plain "@musk" typed text (handy for the CLI simulator).
    if re.search(rf"@{re.escape(bot_name)}\b", raw, re.IGNORECASE):
        mentioned = True
        raw = re.sub(rf"@{re.escape(bot_name)}\b[,:]?", "", raw, flags=re.IGNORECASE)
    text = HTML_TAG.sub("", AT_TAG.sub("", raw)).strip(" ,:\n\t")
    conv = activity.get("conversation", {}) or {}
    meeting = (activity.get("channelData", {}) or {}).get("meeting", {}) or {}
    return Mention(
        text=text,
        user_name=(activity.get("from", {}) or {}).get("name", "someone"),
        conversation_id=conv.get("id", "local-conversation"),
        conversation_type=conv.get("conversationType", "personal"),
        meeting_id=meeting.get("id"),
        mentioned_bot=mentioned or conv.get("conversationType", "personal") == "personal",
    )


def make_activity(text: str, user: str = "You", conversation_type: str = "groupChat",
                  meeting_id: str | None = "local-meeting") -> dict:
    """Build a Teams-shaped message activity, as Teams would send it to the bot."""
    body = re.sub(r"@musk\b", "<at>musk</at>", text, flags=re.IGNORECASE)
    activity = {
        "type": "message",
        "channelId": "msteams",
        "from": {"id": "29:local-user", "name": user},
        "recipient": {"id": "28:musk-bot-app-id", "name": "musk"},
        "conversation": {"id": "19:local@thread.v2", "conversationType": conversation_type},
        "text": body,
        "entities": [{"type": "mention", "text": "<at>musk</at>",
                      "mentioned": {"id": "28:musk-bot-app-id", "name": "musk"}}] if "<at>" in body else [],
        "channelData": {"meeting": {"id": meeting_id}} if meeting_id else {},
    }
    return activity


def reply_activity(incoming: dict, text: str) -> dict:
    """Shape a reply the way the Bot Connector expects (markdown text)."""
    return {
        "type": "message",
        "textFormat": "markdown",
        "text": text,
        "replyToId": incoming.get("id"),
        "conversation": incoming.get("conversation"),
        "from": incoming.get("recipient"),
        "recipient": incoming.get("from"),
    }
