from aistart.tui import build_tui_app


def test_tui_has_keyboard_bindings():
    app_class = build_tui_app()

    bindings = {(binding[0], binding[1]) for binding in app_class.BINDINGS}
    assert ("down", "focus_next") in bindings
    assert ("up", "focus_previous") in bindings
    assert ("s", "start_selected") in bindings
    assert ("x", "toggle_focused_checkbox") in bindings
