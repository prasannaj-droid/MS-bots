"""Where @musk reads meeting context from.

The prototype reads local sample files. `GraphMeetingSource` sketches the real
calls so the swap is obvious; it is not exercised by the prototype.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
VTT_CUE = re.compile(r"<v ([^>]+)>(.*)")


def vtt_to_text(vtt: str) -> str:
    """Turn a Teams WebVTT transcript into 'Speaker: line' text."""
    lines = []
    for line in vtt.splitlines():
        m = VTT_CUE.match(line.strip())
        if m:
            lines.append(f"{m.group(1)}: {m.group(2).strip()}")
    return "\n".join(lines)


class SampleMeetingSource:
    def __init__(self, transcript_path: Path | None = None, chat_path: Path | None = None):
        self.transcript_path = transcript_path or SAMPLES / "meeting_transcript.vtt"
        self.chat_path = chat_path or SAMPLES / "chat_history.json"

    def get_transcript(self, meeting_id: str | None) -> str:
        if not self.transcript_path.exists():
            return ""
        return vtt_to_text(self.transcript_path.read_text(encoding="utf-8"))

    def get_chat_history(self, conversation_id: str, limit: int = 20) -> list[dict]:
        if not self.chat_path.exists():
            return []
        return json.loads(self.chat_path.read_text(encoding="utf-8"))[-limit:]


class GraphMeetingSource:  # pragma: no cover - sketch for the real build
    """Real implementation outline (Microsoft Graph v1.0).

    Transcript:
      GET /users/{organizerId}/onlineMeetings/{meetingId}/transcripts
      GET /users/{organizerId}/onlineMeetings/{meetingId}/transcripts/{transcriptId}/content?$format=text/vtt
      Needs RSC OnlineMeetingTranscript.Read.Chat (app added to the meeting) or
      application permission OnlineMeetingTranscript.Read.All + an application access policy.
      The meeting id comes from the activity's channelData.meeting, resolved via
      TeamsInfo.getMeetingInfo / GET /chats/{chatId} -> onlineMeetingInfo.

    Chat history:
      GET /chats/{chatId}/messages   (RSC ChatMessage.Read.Chat)
    """

    def __init__(self, token_provider):
        self.token_provider = token_provider

    def get_transcript(self, meeting_id: str | None) -> str:
        raise NotImplementedError("Wire up Graph once admin consent is in place.")

    def get_chat_history(self, conversation_id: str, limit: int = 20) -> list[dict]:
        raise NotImplementedError
