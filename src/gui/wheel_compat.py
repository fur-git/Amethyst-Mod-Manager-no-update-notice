"""
Mouse wheel event compatibility between Tk 8.6 and Tk 9.0 on Linux.

Tk 8.6 (AppImage): X11 wheel notches arrive as <Button-4>/<Button-5> only.
Tk 9.0 (Flatpak):  TIP 474 translates Button-4/5 into <MouseWheel> with
                   event.delta of +/-120 per notch, but bindings on the
                   literal <Button-4>/<Button-5> still fire. Without a guard
                   every notch scrolls twice.

Usage: wrap <Button-4>/<Button-5> handlers with ``skip_if_mousewheel`` (or
check ``LEGACY_WHEEL_REDUNDANT`` directly) so they no-op on Tk >= 8.7.
"""

from __future__ import annotations

import sys
import tkinter as tk
from typing import Callable

LEGACY_WHEEL_REDUNDANT: bool = float(tk.TkVersion) >= 8.7


def skip_if_mousewheel(fn: Callable) -> Callable:
    """Make a <Button-4>/<Button-5> handler no-op when Tk also fires <MouseWheel>.

    On Tk >= 8.7 the equivalent <MouseWheel> event already runs this widget's
    wheel logic for the same notch, so firing the Button-4/5 handler too would
    double-scroll. Return ``None`` (not ``"break"``) so other unrelated
    Button-4/5 bindings on the widget still run normally.
    """
    if not LEGACY_WHEEL_REDUNDANT:
        return fn

    def _wrapped(*_args, **_kwargs):
        return None

    return _wrapped


def bind_scrollable_wheel(scrollable) -> None:
    """Make Linux X11 wheel notches (Button-4/5) scroll a CTkScrollableFrame.

    On Tk 8.6 the bundled CTkScrollableFrame only listens for <MouseWheel>,
    which X11 never fires; users have to drag the scrollbar. This helper
    binds Button-4/5 on the frame itself, its inner canvas, and every
    descendant — and re-binds whenever new children appear, so dynamically
    rebuilt step pages keep working.

    No-op on Tk >= 8.7 where TIP 474 already delivers <MouseWheel>.
    """
    if LEGACY_WHEEL_REDUNDANT:
        return

    try:
        canvas = scrollable._parent_canvas
    except Exception:
        return

    def _up(_e):
        try:
            canvas.yview_scroll(-3, "units")
        except Exception:
            pass
        return "break"

    def _down(_e):
        try:
            canvas.yview_scroll(3, "units")
        except Exception:
            pass
        return "break"

    # Track which widgets already carry our Button-4/5 handlers so repeated
    # tree walks (the <Enter> rebind below) stay idempotent. Without this,
    # every pointer-enter stacked another add="+" handler on each widget, so a
    # notch scrolled 3 units × (times the frame had been entered) — i.e. the
    # speed grew over the session and differed per widget depending on how many
    # rebinds happened while it existed.
    bound: set[str] = set()

    def _bind_tree(widget):
        try:
            key = str(widget)
            if key not in bound:
                widget.bind("<Button-4>", _up, add="+")
                widget.bind("<Button-5>", _down, add="+")
                bound.add(key)
        except Exception:
            return
        for child in widget.winfo_children():
            _bind_tree(child)

    _bind_tree(scrollable)
    try:
        _bind_tree(canvas)
    except Exception:
        pass

    # Re-walk descendants when the pointer enters the scroller — cheap, and
    # covers rows added after the initial bind (multi-step wizard pages).
    # Only widgets not already in ``bound`` get a handler, so this never
    # double-binds existing rows.
    def _on_enter(_e=None):
        _bind_tree(scrollable)
        try:
            _bind_tree(canvas)
        except Exception:
            pass

    try:
        scrollable.bind("<Enter>", _on_enter, add="+")
    except Exception:
        pass


def patch_ctk_scrollable_frame() -> None:
    """Patch CTkScrollableFrame's Linux wheel handler to scale event.delta.

    The bundled customtkinter calls ``yview_scroll(-event.delta, "units")`` on
    Linux, which was fine on Tk 8.6 (delta was +/-1). On Tk 9.0 TIP 474 makes
    delta +/-120 per notch, so a single wheel tick scrolls 120 units and
    instantly flings the content to the end. Reduce it to +/-3 units per notch
    to match the rest of the app.
    """
    try:
        import customtkinter as ctk
        ScrollableFrame = ctk.CTkScrollableFrame
    except Exception:
        return

    def _patched_mouse_wheel_all(self, event):
        if not self.check_if_master_is_canvas(event.widget):
            return
        delta = getattr(event, "delta", 0) or 0
        if delta == 0:
            return
        if sys.platform.startswith("win"):
            units = -int(delta / 6)
        elif sys.platform == "darwin":
            units = -delta
        else:
            units = -3 if delta > 0 else 3
        if self._shift_pressed:
            if self._parent_canvas.xview() != (0.0, 1.0):
                self._parent_canvas.xview("scroll", units, "units")
        else:
            if self._parent_canvas.yview() != (0.0, 1.0):
                self._parent_canvas.yview("scroll", units, "units")

    ScrollableFrame._mouse_wheel_all = _patched_mouse_wheel_all
