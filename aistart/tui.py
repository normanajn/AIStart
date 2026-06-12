from __future__ import annotations

from pathlib import Path

from .agents import resolve_agents
from .config import load_config
from .launchers import LAUNCH_ENVS, launch_agents
from .usage import collect_all_usage


def build_tui_app():
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical
        from textual.widgets import Button, Checkbox, Footer, Header, Select, Static
    except ImportError as exc:
        raise RuntimeError(f"Textual is required for the TUI: {exc}") from exc

    class AIStartApp(App):
        CSS = """
        Screen {
            padding: 1 2;
        }
        #agents {
            width: 100%;
            height: auto;
            border: solid $primary;
            padding: 1;
        }
        .agent-row {
            height: auto;
            margin-bottom: 1;
        }
        #messages {
            height: 8;
            border: solid $secondary;
            padding: 1;
        }
        """

        BINDINGS = [
            ("q", "quit", "Quit"),
            ("r", "refresh", "Refresh"),
            ("s", "start_selected", "Start"),
            ("x", "toggle_focused_checkbox", "Toggle"),
            ("down", "focus_next", "Next"),
            ("up", "focus_previous", "Previous"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self.config = load_config()
            self.runtimes = resolve_agents(self.config)
            self.usage = collect_all_usage(self.runtimes, self.config)
            self.checkboxes: dict[str, Checkbox] = {}
            self.env_select: Select | None = None
            self.messages: Static | None = None

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Static("Select agents to launch", id="title")
            with Vertical(id="agents"):
                for name, runtime in self.runtimes.items():
                    stats = self.usage[name]
                    status = "installed" if runtime.installed else "missing"
                    if not runtime.enabled:
                        status = "disabled"
                    label = (
                        f"{runtime.definition.label} ({status}) | "
                        f"5h {stats.limit_5h} reset {stats.reset_5h} | "
                        f"weekly {stats.limit_weekly} reset {stats.reset_weekly} | "
                        f"{stats.session_usage}"
                    )
                    checkbox = Checkbox(label, value=False, id=f"agent-{name}")
                    self.checkboxes[name] = checkbox
                    yield checkbox
            self.env_select = Select(
                [(env, env) for env in LAUNCH_ENVS],
                value=self.config.default_env,
                id="env",
            )
            yield self.env_select
            with Horizontal():
                yield Button("Start", id="start", variant="success")
            self.messages = Static("", id="messages")
            yield self.messages
            yield Footer()

        def action_refresh(self) -> None:
            self.runtimes = resolve_agents(self.config)
            self.usage = collect_all_usage(self.runtimes, self.config)
            self._message("Usage refreshed. Restart the TUI to redraw agent rows.")

        def action_start_selected(self) -> None:
            self._start_selected()

        def action_toggle_focused_checkbox(self) -> None:
            focused = self.focused
            if isinstance(focused, Checkbox):
                focused.value = not focused.value

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "start":
                self._start_selected()

        def _start_selected(self) -> None:
            selected = [
                self.runtimes[name]
                for name, checkbox in self.checkboxes.items()
                if checkbox.value
            ]
            if not selected:
                self._message("Select at least one agent.")
                return
            env = str(self.env_select.value if self.env_select else self.config.default_env)
            results = launch_agents(selected, env, Path.cwd(), self.config)
            lines = []
            for result in results:
                marker = "OK" if result.ok else "ERROR"
                lines.append(f"{marker} {result.agent}: {result.message}")
                if result.attach_command:
                    lines.append(f"  attach: {result.attach_command}")
            self._message("\n".join(lines))

        def _message(self, text: str) -> None:
            if self.messages:
                self.messages.update(text)

    return AIStartApp


def run_tui() -> int:
    try:
        app_class = build_tui_app()
    except RuntimeError as exc:
        print(exc)
        return 1
    app_class().run()
    return 0
