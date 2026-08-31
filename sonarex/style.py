"""Shared look: the button styling, the scroll bars, the palette, the font.

Extracted from `window.py` so a dialog can match the main window's controls
without importing it — `window` opens the dialogs, so a dialog importing
`window` back would be a cycle. Nothing here imports from the rest of the
package, which is what keeps it at the bottom of the import graph.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt6.QtWidgets import QApplication, QPushButton, QStyle

from . import UI_POINT_SIZE

# How far the window surface is lightened away from the panes sitting on it,
# as a QColor.lighter() percentage. Enough to read as a separate surface,
# not so much that the window starts competing with its own contents.
WINDOW_LIGHTEN = 140

# Below this much separation in lightness, two surfaces read as one.
MIN_SEPARATION = 6

# Header button colors. Search is a muted, desaturated green that reads as the
# primary action without turning into a traffic light; Help is a neutral gray
# so it sits beside it as secondary. Light text works on both, so these are
# defined outright rather than derived from the palette the way the window
# surface is.
SEARCH_BUTTON_BG = "#4a6f45"
HELP_BUTTON_BG = "#5a5a5a"
BUTTON_FG = "#f0f2ef"
SEARCH_BUTTON_PADDING = "8px 24px"

# The widest label on a primary button, and so the one that sets the size the
# others are matched to. Kept here rather than read off the live button: the
# dialogs need the measurement before (and without) the main window.
ACTION_BUTTON_TEXT = "Search"

# The icon inside a square header button, as a fraction of the button. A
# QPushButton draws icons at 16px by default whatever its own size, which in a
# button this tall leaves the glyph marooned in the middle and unreadable.
ICON_BUTTON_RATIO = 0.68

# The control bar under the preview is secondary to the header, so its
# button is padded more modestly than the Search button.
CONTROL_BAR_PADDING = "5px 16px"

# Scroll bars are drawn at this multiple of the desktop's own thickness —
# wider bars are easier to grab with the mouse.
SCROLLBAR_SCALE = 2

# A floor for the doubling, in case a style reports an implausibly small
# extent (or none at all) and the result would be a bar too thin to hit.
MIN_SCROLLBAR_EXTENT = 12


def action_button_style(background: str, padding: str = "0px") -> str:
    """Qt stylesheet for a header button of the given background color.

    Styling a button at all opts it out of the native style's rendering —
    including its hover and pressed feedback — so those states have to be
    restated here or the button would look inert to click. Both are derived
    from `background`, so each button's color stays a single value.

    The border is explicit for the same reason: with a stylesheet applied,
    Fusion no longer draws its own frame, and without one the button reads as
    a flat colored rectangle rather than a control.

    `padding` defaults to none, for a button whose size is set explicitly (the
    square icon buttons); padding on top of a fixed size would only squeeze
    the content.
    """
    base = QColor(background)
    return f"""
        QPushButton {{
            background-color: {background};
            color: {BUTTON_FG};
            border: 1px solid {base.darker(125).name()};
            border-radius: 4px;
            padding: {padding};
            font-weight: bold;
        }}
        QPushButton:hover {{ background-color: {base.lighter(115).name()}; }}
        QPushButton:pressed {{ background-color: {base.darker(115).name()}; }}
        QPushButton:disabled {{
            background-color: {base.darker(150).name()};
            color: {QColor(BUTTON_FG).darker(180).name()};
            border-color: {base.darker(160).name()};
        }}
    """


def action_button_size() -> QSize:
    """The size of the header's Search button, for other buttons to match.

    Measured off a throwaway button carrying the same text, style and padding,
    rather than hardcoded: the result then follows the point size, the
    desktop font and `SEARCH_BUTTON_PADDING` instead of drifting out of step
    with them. The probe is never shown and never parented, so it is destroyed
    with the last reference to it here.
    """
    probe = QPushButton(ACTION_BUTTON_TEXT)
    probe.setStyleSheet(action_button_style(SEARCH_BUTTON_BG, SEARCH_BUTTON_PADDING))
    return probe.sizeHint()


def match_action_button(button: QPushButton) -> None:
    """Size `button` like the Search button, so a row of them is uniform.

    Left to themselves, styled buttons size to their own text: "Save" would
    come out visibly narrower than "Cancel", and both narrower than the
    Search button they sit under in the same app. The width is the larger of
    the two hints so a label longer than "Search" is never clipped.
    """
    reference = action_button_size()
    button.setFixedSize(
        max(reference.width(), button.sizeHint().width()), reference.height()
    )


def scrollbar_style() -> str:
    """Qt stylesheet making a scroll bar about twice the usual thickness.

    Applied to the individual scroll bars of a pane rather than to the pane
    itself, so the widget keeps its native rendering and only the bars change.

    The base thickness is read from the active style's own PM_ScrollBarExtent
    rather than assumed, so this doubles whatever the desktop would have
    drawn instead of jumping to a fixed pixel count that happens to be double
    on one theme.

    As with the buttons, styling a scroll bar at all opts it out of native
    drawing — so the groove, the handle and the two stepper buttons all have
    to be described here. The steppers are explicitly collapsed to zero:
    left undescribed they would render as blank boxes at each end.
    """
    extent = QApplication.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
    thickness = max(extent, MIN_SCROLLBAR_EXTENT) * SCROLLBAR_SCALE

    palette = QApplication.palette()
    base = palette.color(QPalette.ColorRole.Base)
    # The handle has to contrast with the pane behind it, and which direction
    # that is depends on the theme: lighten on a dark pane, darken on a light
    # one. Derived from the palette so the bars follow the desktop rather than
    # pinning a gray that only suits one of the two.
    handle = base.lighter(230) if base.lightness() < 128 else base.darker(140)
    hover = handle.lighter(120) if base.lightness() < 128 else handle.darker(115)
    margin = 2
    radius = (thickness - 2 * margin) // 2

    return f"""
        QScrollBar:vertical   {{ background: {base.name()}; width: {thickness}px;
                                 margin: 0; border: none; }}
        QScrollBar:horizontal {{ background: {base.name()}; height: {thickness}px;
                                 margin: 0; border: none; }}
        QScrollBar::handle:vertical   {{ min-height: {thickness * 2}px; }}
        QScrollBar::handle:horizontal {{ min-width: {thickness * 2}px; }}
        QScrollBar::handle {{
            background: {handle.name()};
            border-radius: {radius}px;
            margin: {margin}px;
        }}
        QScrollBar::handle:hover {{ background: {hover.name()}; }}
        /* No stepper arrows: the extra width is for grabbing the handle, and
           zero-sized steppers give the handle the whole length of the bar. */
        QScrollBar::add-line, QScrollBar::sub-line {{
            width: 0; height: 0; border: none; background: none;
        }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
    """


def apply_scrollbars(area) -> None:
    """Give a scroll area's own bars the wider styling."""
    bars = scrollbar_style()
    area.verticalScrollBar().setStyleSheet(bars)
    area.horizontalScrollBar().setStyleSheet(bars)


def tune_palette(app: QApplication) -> None:
    """Lighten the window surface so the list and preview stand out on it.

    Some themes hand Qt the same color for `Window` (the surface behind the
    layout) and `Base` (the background of the list, the preview and the text
    fields). Yaru-dark through the Fusion style is one: both arrive as
    #2a2a2a, so the panes have no edge at all and the whole window reads as
    one flat slab.

    Lightening `Window` — rather than darkening the panes — keeps the panes
    at exactly the color the theme intended for content, and the surround
    becomes the thing that moved.

    Deliberately conditional. In a light theme `Window` is already a gray
    below a white `Base`, and lightening it there would push it *toward*
    white and flatten the very contrast this is meant to create. So the
    change is applied only when it actually increases the separation between
    the two, which also makes it a no-op on a theme that already spaces them
    properly, and on a pure-black palette where `lighter()` cannot move at
    all.
    """
    palette = app.palette()
    window = palette.color(QPalette.ColorRole.Window)
    base = palette.color(QPalette.ColorRole.Base)

    before = abs(window.lightness() - base.lightness())
    if before >= MIN_SEPARATION:
        return  # the theme already distinguishes them; leave it alone

    lightened = window.lighter(WINDOW_LIGHTEN)
    if abs(lightened.lightness() - base.lightness()) <= before:
        return  # lightening would not help (light theme, or a black surface)

    palette.setColor(QPalette.ColorRole.Window, lightened)
    # Buttons keep the theme's own color: against a lightened surround they
    # now read as raised components, which is the point of the change.
    app.setPalette(palette)


def mono_font() -> QFont:
    """The system's fixed-width font at the app's point size.

    Both panes use it: the preview because most of what turns up there is
    source or config, where alignment carries meaning, and the results list
    because a column of paths is far easier to scan when the segments line up
    between rows. The pattern fields in the settings dialog use it for the
    same reason — a glob is punctuation, and punctuation is easier to read
    monospaced.

    Taken from QFontDatabase rather than named outright, so this follows
    whatever the desktop is configured to use for monospace. The style hint is
    still set as a fallback, for the case where that lookup hands back
    something proportional.
    """
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSize(UI_POINT_SIZE)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font
