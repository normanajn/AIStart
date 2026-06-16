from __future__ import annotations

from pathlib import Path

from .agents import resolve_agents
from .config import load_config
from .launchers import LAUNCH_ENVS, launch_agents
from .usage import collect_all_usage, format_usage_bar


TUI_THEMES = ("dark", "light", "amber")


def build_tui_app(initial_theme: str = "dark"):
    try:
        from textual.app import App, ComposeResult
        from textual.containers import Horizontal, Vertical
        from textual.screen import Screen
        from textual.widgets import Button, Checkbox, Footer, Header, Select, Static
    except ImportError as exc:
        raise RuntimeError(f"Textual is required for the TUI: {exc}") from exc

    class ThemeScreen(Screen[str | None]):
        CSS = """
        ThemeScreen {
            align: center middle;
            padding: 1 2;
        }
        ThemeScreen.theme-light {
            background: #f7f8fa;
            color: #1f2328;
        }
        ThemeScreen.theme-light #theme-page {
            background: #ffffff;
            color: #1f2328;
            border: solid #0969da;
        }
        ThemeScreen.theme-light Button {
            background: #e7f0fb;
            color: #1f2328;
        }
        #theme-page {
            width: 40;
            height: auto;
            border: solid $primary;
            padding: 1 2;
        }
        #theme-page Button {
            width: 100%;
            margin-top: 1;
        }
        """

        BINDINGS = [("escape", "back", "Back"), ("q", "back", "Back")]

        def __init__(self, theme: str) -> None:
            super().__init__()
            self.initial_theme = theme

        def compose(self) -> ComposeResult:
            with Vertical(id="theme-page"):
                yield Static("Theme")
                for theme in TUI_THEMES:
                    yield Button(theme.title(), id=f"theme-{theme}")
                yield Button("Back", id="theme-back")

        def on_mount(self) -> None:
            self.add_class(f"theme-{self.initial_theme}")

        def action_back(self) -> None:
            self.dismiss(None)

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "theme-back":
                self.dismiss(None)
                return
            if event.button.id and event.button.id.startswith("theme-"):
                self.dismiss(event.button.id.removeprefix("theme-"))

    class AIStartApp(App):
        CSS = """
        Screen {
            padding: 1 2;
        }
        Screen.theme-dark {
            background: #101418;
            color: #e6edf3;
        }
        Screen.theme-dark #agents {
            border: solid #58a6ff;
        }
        Screen.theme-dark #messages {
            border: solid #8b949e;
        }
        Screen.theme-light {
            background: #f7f8fa;
            color: #1f2328;
        }
        Screen.theme-light Header,
        Screen.theme-light Footer {
            background: #dbeafe;
            color: #1f2328;
        }
        Screen.theme-light Footer * {
            background: #dbeafe;
            color: #1f2328;
        }
        Screen.theme-light #agents {
            background: #ffffff;
            color: #1f2328;
            border: solid #0969da;
        }
        Screen.theme-light #messages {
            background: #ffffff;
            color: #1f2328;
            border: solid #6e7781;
        }
        Screen.theme-light Static,
        Screen.theme-light Checkbox,
        Screen.theme-light Select {
            background: #f7f8fa;
            color: #1f2328;
        }
        Screen.theme-light #agents Checkbox {
            background: #ffffff;
            color: #1f2328;
        }
        Screen.theme-light Select {
            background: #ffffff;
            color: #1f2328;
            border: solid #0969da;
        }
        Screen.theme-light Select * {
            background: #ffffff;
            color: #1f2328;
        }
        Screen.theme-light Select:focus,
        Screen.theme-light Select:focus * {
            background: #e7f0fb;
            color: #1f2328;
        }
        Screen.theme-amber {
            background: #201400;
            color: #ffe8b3;
        }
        Screen.theme-amber #agents {
            border: solid #ffb000;
        }
        Screen.theme-amber #messages {
            border: solid #c98600;
        }
        #agents {
            width: 100%;
            height: auto;
            border: solid $primary;
            padding: 1;
        }
        #main-spacer {
            height: 1fr;
        }
        #status-row {
            width: 100%;
            height: 8;
            align: right middle;
        }
        .agent-row {
            height: auto;
            margin-bottom: 1;
        }
        #messages {
            width: 50%;
            min-width: 48;
            height: 8;
            border: solid $secondary;
            padding: 1;
        }
        """

        BINDINGS = [
            ("q", "quit", "Quit"),
            ("r", "refresh", "Refresh"),
            ("s", "start_selected", "Start"),
            ("t", "select_theme", "Theme"),
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
            self.selected_theme = initial_theme if initial_theme in TUI_THEMES else "dark"

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
                        f"5h {format_usage_bar(stats.percent_5h, stats.limit_5h)} "
                        f"reset {stats.reset_5h} | "
                        f"weekly {format_usage_bar(stats.percent_weekly, stats.limit_weekly)} "
                        f"reset {stats.reset_weekly} | "
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
            yield Static("", id="main-spacer")
            with Horizontal(id="status-row"):
                self.messages = Static("", id="messages")
                yield self.messages
            yield Footer()

        def on_mount(self) -> None:
            self._apply_theme(self.selected_theme)

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

        def action_select_theme(self) -> None:
            self.push_screen(ThemeScreen(self.selected_theme), self._theme_selected)

        def _theme_selected(self, theme: str | None) -> None:
            if theme:
                self._apply_theme(theme)

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

        def _apply_theme(self, theme: str) -> None:
            if theme not in TUI_THEMES:
                theme = "dark"
            for known_theme in TUI_THEMES:
                self.screen.remove_class(f"theme-{known_theme}")
            self.screen.add_class(f"theme-{theme}")
            self.selected_theme = theme

    return AIStartApp


def run_tui(theme: str = "dark") -> int:
    try:
        app_class = build_tui_app(theme)
    except RuntimeError as exc:
        print(exc)
        return 1
    app_class().run()
    return 0
