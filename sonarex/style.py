"""Shared look: the button styling, the palette, the font.

Extracted from `window.py` so a dialog can match the main window's controls
without importing it — `window` opens the dialogs, so a dialog importing
`window` back would be a cycle. Nothing here imports from the rest of the
package, which is what keeps it at the bottom of the import graph.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QProxyStyle,
    QPushButton,
    QStyle,
)

from windowchrome import ChromeTheme, body_text_color, body_window_color

from . import UI_POINT_SIZE

# How far the window surface is lightened away from the panes sitting on it,
# as a QColor.lighter() percentage. Enough to read as a separate surface,
# not so much that the window starts competing with its own contents.
WINDOW_LIGHTEN = 140

# Below this much separation in lightness, two surfaces read as one.
MIN_SEPARATION = 6

# The two general-purpose button colors, named for the *role* rather than for
# any one button: PRIMARY is a muted, desaturated green that reads as the main
# action without turning into a traffic light (Search, Save), SECONDARY the
# neutral gray of anything sitting beside one (Cancel, Close). Light text works
# on both, so these are defined outright rather than derived from the palette
# the way the window surface is.
PRIMARY_BUTTON_BG = "#4a6f45"
SECONDARY_BUTTON_BG = "#5a5a5a"
BUTTON_FG = "#f0f2ef"

# The default padding of a button made by `action_button()`, and so the shape
# every full-size button in the app takes unless it asks for another. Wider
# than a stock QPushButton's on purpose — the labels want room around them.
ACTION_BUTTON_PADDING = "8px 24px"

# Match highlighting in the preview. Both halves are pinned rather than derived
# from the palette, and they have to be set together: the background has to stay
# recognisably a highlighter color in either theme, so the text on top of it
# cannot inherit the theme's foreground — on a dark theme that is near-white and
# would vanish against the amber.
MATCH_BG = "#ff9e3d"
MATCH_FG = "#1a1a1a"

# The one match Prev/Next is parked on. Brighter and lighter than MATCH_BG
# rather than a different hue entirely: it has to read as "this one of those",
# not as a second, unrelated kind of mark. MATCH_FG stays legible on it, which
# is why the current match needs no foreground of its own.
MATCH_CURRENT_BG = "#ffe066"

# Prev/Next. A muted steel blue, sitting at the same low saturation as the
# green Search button so the two do not compete: these step through what a
# search already found, they do not start one.
NAV_BUTTON_BG = "#41648c"

# The window's title bar, and with it the thin frame the decoration draws down
# the sides and along the bottom. `windowchrome` owns both — see
# `../windowchrome/README.md` for why they are reachable at all (Wayland only,
# by repurposing three palette roles) and why their *size* is not.
#
# The library ships neutral defaults and this is Sonar's override of them. The
# blue is seeded from the desktop's headerbar colors so the app sits in with
# everything else rather than announcing itself.
SONAREX_THEME = ChromeTheme(title_bg="#1369da")

# The Open button is tinted with the selection color instead of a constant of
# its own: it acts on the row highlighted in the results list, and sharing that
# color is what says so. Read from the palette rather than pinned to Yaru's
# orange so it keeps matching the list on any theme.
#
# Below this lightness the light BUTTON_FG still reads on it; a pale highlight
# is darkened until it does, which costs the exact match but keeps the label
# legible — a theme whose highlight is nearly white would otherwise give a
# button with invisible text.
MAX_SELECTION_LIGHTNESS = 150

# The widest label on a primary button, and so the one that sets the size the
# others are matched to. Kept here rather than read off the live button: the
# dialogs need the measurement before (and without) the main window.
ACTION_BUTTON_TEXT = "Search"

# The control bar under the preview is secondary to the header, so its
# button is padded more modestly than the Search button.
CONTROL_BAR_PADDING = "5px 16px"

# Inside the match-navigation group — the two arrows and the counter they
# move — in pixels. Tighter than the layout's own spacing between unrelated
# controls, which is what makes the three read as one thing sitting in the
# middle of the bar rather than three that happen to be adjacent.
NAV_GROUP_SPACING = 6

# How much of an icon button's side is *not* icon, in pixels: its border, and
# the ring of background that keeps the glyph from touching it. The rest is
# given to the icon, so the button reads as an icon with a frame around it
# rather than a small mark adrift in a large square.
ICON_BUTTON_INSET = 8

# The gutter down the left of the preview pane, in pixels: how far the file
# text and the Open button under it are held off the divider. It is a gutter
# rather than a margin — the pane itself stays flush with the splitter and
# the space is taken out of its inside, so it is the preview's own background
# and not a stripe of window surface masquerading as a second border beside
# the handle.
PANE_GAP = 10

# The grab area of the divider between the two panes. The desktop's own is a
# few pixels of nearly the surrounding color: hard to see and harder to hit.
SPLITTER_HANDLE_WIDTH = 10

# How far the handle's color is moved away from the window surface behind it,
# as a lighter()/darker() percentage.
SPLITTER_CONTRAST = 150

# Menu padding, in pixels: the space around the label of a menu-bar title and
# of an item inside a menu. Both are bigger targets than the desktop's default,
# which is sized for a mouse that never misses. The menus carry so few items
# that the extra height costs nothing.
MENU_BAR_ITEM_PADDING = "8px 16px"
MENU_ITEM_PADDING = "10px 32px"
MENU_BORDER = "1px solid #9a9a9a"

# How much bigger than the desktop's own a check box's indicator is drawn.
# Same reasoning as `windowchrome`'s scroll bars, which this used to sit
# beside: a bigger target is an easier one to hit.
CHECKBOX_SCALE = 2

# The space around a file name in the results list, in pixels. Qt packs list
# rows at the bare height of their text, which runs a long list of paths
# together into one block with no line between one name and the next. Four
# pixels above and below is enough to read them as separate rows without
# stretching the list into a menu; the horizontal half holds the names off the
# pane edge, so the first character is not flush against the border.
RESULT_ITEM_PADDING = "4px 6px"


def action_button_style(background: str, padding: str = "0px") -> str:
    """Qt stylesheet for a header button of the given background color.

    Styling a button at all opts it out of the native style's rendering —
    including its hover and pressed feedback — so those states have to be
    restated here or the button would look inert to click. Both are derived
    from `background`, so each button's color stays a single value.

    The border is explicit for the same reason: with a stylesheet applied,
    Fusion no longer draws its own frame, and without one the button reads as
    a flat colored rectangle rather than a control.

    `padding` defaults to none, for a button whose size is set explicitly;
    padding on top of a fixed size would only squeeze the content.
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


def selection_button_bg() -> str:
    """The results list's selection color, as a background for a button.

    Darkened if the theme's highlight is too pale to carry light text; see
    MAX_SELECTION_LIGHTNESS.
    """
    color = QApplication.palette().color(QPalette.ColorRole.Highlight)
    while color.lightness() > MAX_SELECTION_LIGHTNESS:
        darker = color.darker(115)
        if darker.lightness() >= color.lightness():
            break  # cannot move any further; take what we have
        color = darker
    return color.name()


def _text_button_size(padding: str) -> QSize:
    """The size a styled button carrying `ACTION_BUTTON_TEXT` would take.

    Measured off a throwaway button carrying that text, style and padding,
    rather than hardcoded: the result then follows the point size, the desktop
    font and the padding instead of drifting out of step with them. The probe
    is never shown and never parented, so it is destroyed with the last
    reference to it here.

    The background is left at the primary green because it changes nothing
    about the measurement — every `action_button_style()` draws the same 1px
    border and the same box, whatever color fills it.
    """
    probe = QPushButton(ACTION_BUTTON_TEXT)
    probe.setStyleSheet(action_button_style(PRIMARY_BUTTON_BG, padding))
    return probe.sizeHint()


def action_button_size() -> QSize:
    """The size of the header's Search button, for other buttons to match."""
    return _text_button_size(ACTION_BUTTON_PADDING)


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


def action_button(
    text: str,
    background: str = SECONDARY_BUTTON_BG,
    padding: str = ACTION_BUTTON_PADDING,
    *,
    uniform: bool = False,
) -> QPushButton:
    """A button wearing the app's look: the one place a button is made.

    Everything a button in this app needs is here rather than repeated at each
    call site — the stylesheet, and `setAutoDefault(False)` so Enter runs the
    window's or dialog's own default action instead of whichever button
    happens to hold focus. A new button is then a single call, and cannot
    quietly come out looking like Qt's default instead of like the rest.

    The defaults are the common case: the neutral secondary gray at the full
    header padding. Pass `background` for a button with a role of its own
    (`PRIMARY_BUTTON_BG`, `NAV_BUTTON_BG`, `selection_button_bg()`) and
    `padding` where a denser row wants it (`CONTROL_BAR_PADDING`).

    `uniform` additionally freezes the button to the shared action size, for
    a row where differing label widths would otherwise show — see
    `match_action_button()`. It is off by default because a fixed size is
    wrong for a button that has to grow with its layout.
    """
    button = QPushButton(text)
    button.setStyleSheet(action_button_style(background, padding))
    button.setAutoDefault(False)
    if uniform:
        match_action_button(button)
    return button


def _icon_size(icon: QIcon, limit: int) -> QSize:
    """How large to draw `icon` inside a box `limit` pixels square.

    The limit itself, unless the icon set has nothing that big. A themed icon
    is a set of fixed-size pixmaps and QIcon will answer any size asked of it
    by scaling the nearest one: scaling *down* from a larger pixmap is what
    fills the button and costs nothing visible, while scaling *up* past the
    largest pixmap the theme ships is a soft smear. So an icon whose sizes
    stop below the limit is drawn at its own largest instead.

    An icon reporting no sizes at all is SVG-backed, where every size is exact
    and there is no ceiling to respect; it gets the limit.
    """
    sizes = icon.availableSizes()
    if not sizes:
        return QSize(limit, limit)
    side = min(limit, max(size.width() for size in sizes))
    return QSize(side, side)


def icon_button(
    pixmap: QStyle.StandardPixmap,
    background: str = SECONDARY_BUTTON_BG,
    padding: str = ACTION_BUTTON_PADDING,
) -> QPushButton:
    """A square, icon-only button that stands as tall as the text ones beside it.

    `padding` is the padding of those *neighbors* — `CONTROL_BAR_PADDING` for
    the row under the preview — and is measured rather than applied: it is
    what makes the heights match, while putting 16px of it inside a square
    holding one glyph would only squeeze the glyph out. The button is then
    fixed to that height in both directions, which is what makes it a square.

    The icon is Qt's, drawn from the desktop's own theme, so the folder on the
    button is the folder the file manager itself uses. `_icon_size` decides
    how big it is drawn.
    """
    side = _text_button_size(padding).height()
    button = QPushButton()
    button.setStyleSheet(action_button_style(background))
    button.setAutoDefault(False)
    button.setFixedSize(side, side)
    icon = QApplication.style().standardIcon(pixmap)
    button.setIcon(icon)
    button.setIconSize(_icon_size(icon, side - ICON_BUTTON_INSET))
    return button


def splitter_style() -> str:
    """Qt stylesheet for a wider, visible splitter handle.

    The color is derived from the window surface rather than pinned, so the
    handle tracks the theme — and `tune_palette()`'s lightened surface, which
    is what the handle actually sits on. Which way it moves depends on where
    there is room, exactly as the scroll-bar handle does: lighter on a dark
    surface, darker on a light one, where lightening would only run into the
    white of the panes and vanish again.

    The width is set here *and* through `setHandleWidth()` in `window.py`:
    the stylesheet paints the handle, but the splitter's own layout is what
    reserves the space and decides where a drag starts.
    """
    window = body_window_color()
    handle = (
        window.lighter(SPLITTER_CONTRAST)
        if window.lightness() < 128
        else window.darker(SPLITTER_CONTRAST)
    )
    return f"""
        QSplitter::handle:horizontal {{
            background: {handle.name()};
            width: {SPLITTER_HANDLE_WIDTH}px;
        }}
    """



def results_list_style() -> str:
    """Qt stylesheet giving the results list room around each file name.

    Padding only, for the same reason `menu_style()` is: the list keeps the
    desktop's own colors and its font comes from `mono_font()`. And with the
    same catch — styling `::item` at all takes those rows out of the native
    style's painting, selection included, so the selected row's colors have to
    be restated here in `palette()` terms or the current file would stop
    looking current.
    """
    return f"""
        QListWidget::item {{
            padding: {RESULT_ITEM_PADDING};
        }}
        QListWidget::item:selected {{
            background: palette(highlight);
            color: palette(highlighted-text);
        }}
    """


class _LargeIndicatorStyle(QProxyStyle):
    """A style that reports check-box indicators at `CHECKBOX_SCALE` size.

    The indicator is sized by the style, not by the font or the widget, so a
    check box cannot simply be made bigger from the outside. A stylesheet can
    set the indicator's width and height, but styling that sub-control at all
    takes over its drawing, and the check mark — which no stylesheet can draw
    without shipping an image — goes with it, leaving a box that never looks
    ticked. Overriding the pixel metric instead keeps the native rendering and
    only changes the rectangle it is asked to fill.

    Default-constructed on purpose: with no base style it proxies whatever
    QApplication is using at the time, and, unlike the constructor that takes
    a style, it does not take ownership of the application's shared one.
    """

    def pixelMetric(self, metric, option=None, widget=None):  # noqa: N802 (Qt)
        size = super().pixelMetric(metric, option, widget)
        if metric in (
            QStyle.PixelMetric.PM_IndicatorWidth,
            QStyle.PixelMetric.PM_IndicatorHeight,
        ):
            return size * CHECKBOX_SCALE
        return size


def enlarge_checkbox(box: QCheckBox) -> None:
    """Draw `box`'s indicator larger, leaving its label at the normal size.

    The proxy is parented to the check box rather than installed on the
    application: it is one widget's affordance, not a change of theme. That
    parenting is also what keeps the style alive — `setStyle()` does not take
    ownership, and a style collected out from under a live widget crashes it.
    """
    style = _LargeIndicatorStyle()
    style.setParent(box)
    box.setStyle(style)


def menu_style() -> str:
    """Qt stylesheet for the window's menu bar and its drop-downs.

    Padding only — the font is left alone, so the menus grow as targets
    without the rest of the window changing size around them.

    Styling `::item` at all opts those items out of the native style's
    rendering, hover included, so the selected state has to be restated here
    or a menu would highlight nothing under the pointer. It is written in
    `palette()` terms rather than pinned colors so it still follows the
    desktop theme, the way the unstyled menu did.

    The drop-downs also carry `MENU_BORDER`: the pop-up takes the same
    surface color as the window behind it, so without an edge a menu has no
    visible boundary at all. The gray is pinned rather than derived because
    it has to read against both a light and a dark surface, and giving
    `QMenu` a border means giving it an explicit background too: a styled
    frame stops the native style painting the pop-up and Qt fills it from
    the `Window` role instead — which windowchrome has repurposed for the
    title bar, so leaving it out paints the menu title-bar blue rather than
    the gray it had before. `body_window_color()` is that gray, and is why
    this one color is interpolated rather than written as `palette(window)`.
    """
    body = body_window_color().name()
    return f"""
        QMenuBar::item {{
            padding: {MENU_BAR_ITEM_PADDING};
            background: transparent;
        }}
        QMenuBar::item:selected, QMenuBar::item:pressed {{
            background: palette(highlight);
            color: palette(highlighted-text);
        }}
        QMenu {{
            padding: 6px;
            background: {body};
            border: {MENU_BORDER};
        }}
        QMenu::item {{ padding: {MENU_ITEM_PADDING}; }}
        QMenu::item:selected {{
            background: palette(highlight);
            color: palette(highlighted-text);
        }}
    """


# The status bar's busy colors. Pinned rather than derived, and pinned as a
# *pair* for the same reason the match highlight is: the green has to read as
# green on a light desktop and on a dark one, so the text on top of it cannot
# be left to inherit a theme foreground that may be near-black or near-white.
# A muted green in the same family as PRIMARY_BUTTON_BG — the bar is saying
# "the thing the green button started is still running", not raising an alarm.
STATUS_BUSY_BG = "#3f6b39"
STATUS_BUSY_FG = "#f0f2ef"

# Room around the status line, as left/top/right/bottom for
# `setContentsMargins`. Not a stylesheet `padding`, which is the obvious way
# to write it and does **nothing** here: measured, a QStatusBar with
# `padding: 6px 10px` is the same 22px tall as one without it, because the bar
# lays its widgets out itself rather than through the box model. The margins
# do work (22px -> 34px) and survive both a resize and the stylesheet swap
# `_set_busy` does on every search, which is the other half of what was
# checked.
STATUS_BAR_MARGINS = (10, 6, 10, 6)

# The line separating the bar from the window above it. Pinned, and the same
# gray as MENU_BORDER, for the same reason that one is: it has to read against
# a light desktop surface and a dark one, and here also against the busy green,
# so it can be derived from neither the palette nor the bar's own background.
# Top only — the other three edges are the window's frame, which the decoration
# already draws.
STATUS_BAR_BORDER = "1px solid #9a9a9a"


def status_style(busy: bool) -> str:
    """Qt stylesheet for the status bar, in its idle or its searching state.

    Colors and the border only — the room around the text is
    `STATUS_BAR_MARGINS`, applied as contents margins, because a stylesheet
    `padding` on a QStatusBar is silently ignored. See the note on that
    constant.

    Idle takes `body_window_color()` rather than `palette(window)`: windowchrome
    has repurposed the Window role for the title bar, so naming the role here
    would paint the bar title-bar blue — the same trap `menu_style()` documents.

    Both states carry the same top border: the bar is a strip of the window
    rather than a widget sitting on it, so without a line it runs straight into
    the pane above — visibly so when idle, where its background *is* the window
    color. Being the one thing that does not change between the two states, it
    also keeps the bar's outline steady as the green comes and goes.

    Busy takes the green, background and foreground together, and the labels
    are named explicitly because a stylesheet set on the bar reaches its
    children: without the QLabel rule the spinner and the message would keep
    whatever foreground the palette last handed them, which on a light theme
    is near-black on the green.
    """
    if busy:
        background, foreground = STATUS_BUSY_BG, STATUS_BUSY_FG
    else:
        background = body_window_color().name()
        foreground = body_text_color().name()
    return f"""
        QStatusBar {{
            background: {background};
            border-top: {STATUS_BAR_BORDER};
        }}
        QStatusBar::item {{ border: none; }}
        QStatusBar QLabel {{
            background: transparent;
            color: {foreground};
        }}
    """


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
