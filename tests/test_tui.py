from aistart.tui import TUI_THEMES, build_tui_app


def test_tui_has_keyboard_bindings():
    app_class = build_tui_app()

    bindings = {(binding[0], binding[1]) for binding in app_class.BINDINGS}
    assert ("down", "focus_next") in bindings
    assert ("up", "focus_previous") in bindings
    assert ("s", "start_selected") in bindings
    assert ("t", "select_theme") in bindings
    assert ("x", "toggle_focused_checkbox") in bindings


def test_tui_app_instantiates():
    app_class = build_tui_app()

    app = app_class()

    assert app.selected_theme == "dark"


def test_tui_app_accepts_initial_theme():
    app_class = build_tui_app("light")

    app = app_class()

    assert app.selected_theme == "light"


def test_tui_themes_include_light_dark_and_amber():
    assert TUI_THEMES == ("dark", "light", "amber")
