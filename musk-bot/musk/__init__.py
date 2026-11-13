from .agent import Context, make_brain  # noqa: F401
from .teams import parse_activity, make_activity, reply_activity  # noqa: F401


def handle_activity(activity: dict, brain=None, ctx_kwargs: dict | None = None) -> dict | None:
    """Entry point shared by the CLI and the HTTP server. Returns a reply activity or None."""
    from .agent import Context, make_brain

    mention = parse_activity(activity)
    if activity.get("type") != "message" or not mention.mentioned_bot:
        return None  # in group chats @musk only acts when mentioned
    ctx = Context(mention=mention, **(ctx_kwargs or {}))
    text = (brain or make_brain()).handle(ctx)
    return reply_activity(activity, text)
