"""Transparent GTK splash screen — launched as a subprocess by gui.py.

Usage:  python splash_gtk.py <image_path> [<x> <y>]

Exits cleanly when terminated (SIGTERM from parent).
Falls back silently if GTK / pycairo is unavailable.
"""
import sys
import os


def main():
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk, Gdk, GdkPixbuf
        import cairo
    except Exception:
        sys.exit(1)

    image_path = sys.argv[1] if len(sys.argv) > 1 else None
    x = int(sys.argv[2]) if len(sys.argv) > 2 else None
    y = int(sys.argv[3]) if len(sys.argv) > 3 else None

    # POPUP type is never managed by the window manager — no title bar,
    # no borders, no decorations, guaranteed.
    win = Gtk.Window(type=Gtk.WindowType.POPUP)
    win.set_keep_above(True)
    win.set_app_paintable(True)
    win.connect('destroy', Gtk.main_quit)

    # Enable RGBA visual for per-pixel transparency (requires a compositor)
    screen = win.get_screen()
    visual = screen.get_rgba_visual()
    if visual and screen.is_composited():
        win.set_visual(visual)

    pixbuf = None
    if image_path and os.path.isfile(image_path):
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path)
            win.set_default_size(pixbuf.get_width(), pixbuf.get_height())
        except Exception:
            pass

    if pixbuf is None:
        win.set_default_size(300, 80)

    def on_draw(widget, cr):
        # Paint transparent background first (clears any default window bg)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.paint()
        # Composite the PNG with full alpha intact
        if pixbuf:
            cr.set_operator(cairo.OPERATOR_OVER)
            Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
            cr.paint()
        return False

    win.connect('draw', on_draw)
    # GDK_BACKEND=x11 is set by the parent process, so Gtk.WindowType.POPUP
    # maps directly to an X11 override_redirect window — bypasses KWin entirely.
    win.show_all()

    if x is not None and y is not None:
        win.move(x, y)
    else:
        win.set_position(Gtk.WindowPosition.CENTER)

    Gtk.main()


if __name__ == '__main__':
    main()
