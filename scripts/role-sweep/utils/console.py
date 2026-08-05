"""Captures browser console errors + page errors so each user-story fails loud."""
from __future__ import annotations


class ConsoleErrorCollector:
    """Attach to a Playwright `page` via `collector.attach(page)`.

    Each user-story runs between `collector.begin_story(name)` and
    `collector.end_story(name, allowlist)`. The collector stores every
    console.error and every uncaught pageerror.

    allowlist: iterable of regex patterns; error messages matching any
    pattern are recorded as "allowed" rather than failing the story.
    """

    def __init__(self) -> None:
        self._stories: dict[str, list[dict]] = {}
        self._current: list[dict] | None = None
        self._current_name: str | None = None

    def attach(self, page) -> None:
        page.on(
            "console",
            lambda msg: self._on_console(msg.type, msg.text) if msg.type == "error" else None,
        )
        page.on("pageerror", lambda exc: self._on_console("pageerror", str(exc)))

    def _on_console(self, kind: str, text: str) -> None:
        if self._current is None:
            # Outside a story window — treat as global.
            self._stories.setdefault("<global>", []).append({"kind": kind, "text": text})
            return
        self._current.append({"kind": kind, "text": text})

    def begin_story(self, name: str) -> None:
        # End any previous open story first.
        if self._current is not None and self._current_name is not None:
            self.end_story(self._current_name)
        self._current_name = name
        self._current = []

    def end_story(self, name: str, allowlist=()) -> list[dict]:
        if self._current_name != name:
            # Defensive — flush by best effort
            name = self._current_name or name
        if self._current is None:
            return []
        captured = self._current
        self._stories[name] = captured
        self._current = None
        self._current_name = None
        return self.filtered(captured, allowlist)

    @staticmethod
    def filtered(errors: list[dict], allowlist) -> tuple[dict, ...]:
        import re

        offenders = []
        allowed = []
        for err in errors:
            if any(re.search(p, err["text"]) for p in allowlist):
                allowed.append(err)
            else:
                offenders.append(err)
        return tuple(offenders)

    @property
    def all(self) -> dict:
        return dict(self._stories)
