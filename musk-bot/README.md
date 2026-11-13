# @musk: Teams @mention work bot (toy prototype)

Mention `@musk` in a Teams chat or meeting chat and it:

- summarizes the meeting (takeaways, MoM, decisions, action items, risks) from the transcript,
- creates Azure DevOps work items in `milestone-devops / Asgard`,
- adds a page to the Asgard wiki.

This prototype runs entirely on your laptop with a sample transcript and a fake Teams chat.
**ADO writes are dry-run by default**: each request is saved under `./dry_run_output/` instead of being sent.

## Run it (Python 3.10+)

```bash
pip install -r requirements.txt          # only needed for the Claude brain

# 1. No credentials: offline keyword brain (shows routing, not intelligence)
python cli.py "@musk what's the takeaway from this meeting"
python cli.py "@musk, create a few ADO items for these topics"
python cli.py "@musk add a wiki page to cover these ideas"
python cli.py --activity samples/activity_mention.json   # replay a real Teams activity shape

# 2. With Claude (claude-opus-5-5, tool use)
export ANTHROPIC_API_KEY=...             # brain switches to Claude automatically
python cli.py "@musk give me the MoM and create tasks for the action items"

# 3. Fake Teams chat in the browser
python server.py                         # then open http://localhost:3978

# Tests (no key, no network)
python -m unittest discover -s tests -v
```

## Going live against ADO (only when you're ready)

```bash
export ADO_PAT=...            # PAT with Work Items (Read & write) + Wiki (Read & write)
export MUSK_ADO_LIVE=1        # without this, nothing is sent
export ADO_ORG=milestone-devops ADO_PROJECT=Asgard ADO_WIKI=Asgard.wiki   # defaults shown
```

## Layout

| File | What it does |
| --- | --- |
| `musk/teams.py` | Parses a Teams activity (strips `<at>musk</at>`, finds meeting id), builds replies |
| `musk/agent.py` | `ClaudeBrain` (Claude + 4 tools, manual tool loop) and `OfflineBrain` (keyword router) |
| `musk/sources.py` | Sample transcript/chat reader; `GraphMeetingSource` sketches the real Graph calls |
| `musk/ado.py` | ADO REST: create work items (JSON Patch) and wiki pages; dry-run by default |
| `cli.py` / `server.py` | Terminal simulator and a local HTTP endpoint + fake chat page |
| `samples/` | Sample meeting transcript (VTT), chat history, Teams activity JSON |

## What's mocked vs real

- **Mocked:** Teams itself (no Bot Framework auth, replies are inline), the transcript and chat (local files).
- **Real:** the Claude tool loop and prompts, the exact ADO REST requests (URL, JSON Patch body).

To make it a real Teams bot: wrap `musk.handle_activity` in a Microsoft 365 Agents SDK app,
register an Azure Bot, add a Teams app manifest with RSC permissions, and swap in `GraphMeetingSource`.
See the architecture doc for the full path.

## Claude settings

`claude-opus-5-5`, adaptive thinking, effort `medium`, strict tool schemas, and server-side
refusal fallback (`fallbacks="default"`) so a rare safety decline is retried on a fallback model
instead of failing. Override the model with `MUSK_MODEL`.
