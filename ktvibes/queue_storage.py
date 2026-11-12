"""Queue persistence; playback and transport remain in State."""
import json
from pathlib import Path

def restore(state, path: Path, seed, themes):
    """Reload the saved queue; songs are prepared again (fast from cache) and the current one resumes."""
    state.path = path
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    # Before play history existed, fall back to whatever seed() knows (e.g. cache timestamps).
    state.played = saved["played"] if isinstance(saved.get("played"), dict) else seed()
    state.theme = saved.get("theme") if saved.get("theme") in themes else "default"
    state.room_ends = float(saved["room_ends"]) if state.theme == "classic" and isinstance(saved.get("room_ends"), (int, float)) else None
    entries = saved.get("upcoming", [])
    if saved.get("current"):
        entries = [saved["current"], *entries]
    for entry in entries:
        item = state.entry(entry["id"], entry["artist"], entry["title"], entry.get("requester"))
        if entry is saved.get("current"):
            item["resume"] = float(entry.get("position") or 0)
        state.upcoming.append(item)
    state.wake.set()


def save(state):
    if state.path is None:
        return
    brief = lambda i: {"id": i["id"], "artist": i["artist"], "title": i["title"], **({"requester": i["requester"]} if i.get("requester") else {})}
    data = {"current": state.current and {**brief(state.current), "position": state.position},
            "upcoming": [brief(i) for i in state.upcoming if i["status"] != "error"], "played": state.played,
            "theme": state.theme, "room_ends": state.room_ends}
    temporary = state.path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(state.path)
