"""Branch's look, loaded from theme.json.

House convention (keep/link, keep/gauge, keep/plinth): the theme is data, not
code. Change a value in theme.json and restart; nothing here needs editing.

Two rules carried over from the family and worth not rediscovering:
  - No red anywhere. No magenta or purple either -- the first draft of this
    window used both and they were wrong.
  - Never name a weight inside a font family; fontconfig substitutes silently.

SIZING. Every measurement is authored small -- the numbers below are the ones you
would type for a 13px window -- and multiplied by theme.json's `ui_scale` on the
way to the screen. That is gauge's page_scale mechanism and it means one value
resizes the whole window.

This is NOT the DPI story. Qt 6 already scales logical pixels for whatever monitor
the window is on, including fractional 125%/150% scaling and mixed-DPI setups, so
authoring in logical pixels is correct and portable. `ui_scale` sits on top of that
and is purely taste.
"""
from __future__ import annotations

from .. import resources
import json
from dataclasses import dataclass
from pathlib import Path

THEME_PATH = resources.package("ui", "theme.json")

DEFAULTS: dict = {
    "ground": "#0B111A",
    "panel": "#141C27",
    "edge": "#26313F",
    "accent": "#4C7399",
    "accent_hi": "#7BA3C9",
    "foreground": "#D3DCE6",
    "foreground_dim": "#8FA0B4",
    "warm": "#5C6B7A",
    "warm_hi": "#76889A",
    "corner_radius": 10,
    "strip_radius": 10,
    "row_radius": 8,
    "control_radius": 5,
    "font_family": '"Ubuntu Sans", "DejaVu Sans", system-ui, sans-serif',
    "font_size": 11,
    "motion_speed": 170,
    "ui_scale": 1.0,
    "tray": 0.07,
    "tray_hover": 0.13,
    "tray_active": 0.17,
    "tray_selected": 0.34,
    "slab_alpha": 0.16,
    "slab_alpha_idle": 0.085,
    "slab_tint": "#3C5878",
    "slab_bottom": "#1B2838",
    "top_glow": 0.10,
}


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def rgba(hex_colour: str, alpha: float) -> str:
    r, g, b = _hex_to_rgb(hex_colour)
    return f"rgba({r}, {g}, {b}, {max(0.0, min(1.0, alpha)):.3f})"


@dataclass(frozen=True)
class Theme:
    values: dict

    @classmethod
    def load(cls, path: Path | None = None) -> "Theme":
        merged = dict(DEFAULTS)
        try:
            raw = json.loads((path or THEME_PATH).read_text(encoding="utf-8"))
            merged.update({k: v for k, v in raw.items() if not k.startswith("_")})
        except FileNotFoundError:
            pass
        except Exception as exc:                 # a hand-edited theme must not be fatal
            print(f"warning: theme.json unreadable ({exc}); using defaults")
        return cls(merged)

    def __getattr__(self, name: str):
        try:
            return self.values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    # -- scaling -------------------------------------------------------------

    @property
    def scale(self) -> float:
        return float(self.values.get("ui_scale", 1.0) or 1.0)

    def s(self, n: float) -> int:
        """Scale one authored measurement."""
        return max(1, round(n * self.scale))


# -- authored measurements -------------------------------------------------
# All in logical pixels for a 13px window, before ui_scale. Kept together so the
# window's proportions are readable in one place rather than scattered.

class Size:
    window_w = 500
    window_h = 150       # a floor; the window hugs its content at startup
    results_h = 300      # how far the window grows when a scan returns
    pad = 9             # window inner padding
    gap = 6             # general gap
    tight = 4           # gap inside the source grid
    query_h = 22
    query_w = 110       # the width he drew, not the width of the window
    combo_h = 22
    pill_h = 20
    wbtn = 9            # minimise / close hit area
    wbtn_glyph = 5
    wbtn_inset = 5      # from the true top-right corner
    label_size = 8
    popup_row = 19      # completer row height
    resize_margin = 6
    column_gap = 14


def stylesheet(t: Theme) -> str:
    """No outlines anywhere.

    A control is a *tray*: a slightly darker, slightly transparent slab the text
    sits on. Hover makes it less transparent instead of drawing a border, and a
    selected source uses the accent tint -- still with no edge. Borders were what
    made the first draft look like a form; trays make it look like the family.
    """
    s = t.s
    fg, dim = t.foreground, t.foreground_dim
    tray = rgba(t.foreground, float(t.tray))
    tray_hover = rgba(t.foreground, float(t.tray_hover))
    tray_active = rgba(t.foreground, float(t.tray_active))
    selected = rgba(t.accent, float(t.tray_selected))
    radius = s(t.control_radius)

    return f"""
    QWidget {{
        color: {fg};
        font-family: {t.font_family};
        font-size: {s(t.font_size)}px;
    }}

    QLineEdit#query, QLineEdit#location {{
        background: {tray};
        border: none;
        border-radius: {radius}px;
        padding: 0px {s(9)}px;
        color: {fg};
        selection-background-color: {rgba(t.accent, 0.55)};
        selection-color: {fg};
    }}
    QLineEdit#query:hover, QLineEdit#location:hover {{ background: {tray_hover}; }}
    QLineEdit#query:focus, QLineEdit#location:focus {{ background: {tray_active}; }}

    /* The panel groups the controls; it is not a box, so it has no edge. */
    QFrame#panel {{
        background: {rgba(t.foreground, 0.035)};
        border: none;
        border-radius: {s(t.row_radius)}px;
    }}

    QLabel#fieldLabel {{
        color: {dim};
        font-size: {s(Size.label_size)}px;
        letter-spacing: 0.04em;
    }}

    QComboBox {{
        background: {tray};
        border: none;
        border-radius: {radius}px;
        padding: 0px {s(8)}px;
        color: {fg};
    }}
    QComboBox:hover {{ background: {tray_hover}; }}
    QComboBox:focus {{ background: {tray_active}; }}
    QComboBox QLineEdit {{
        background: transparent;
        border: none;
        padding: 0px;
        color: {fg};
        selection-background-color: {rgba(t.accent, 0.55)};
        selection-color: {fg};
    }}
    QComboBox::drop-down {{ border: none; width: {s(16)}px; }}
    QComboBox::down-arrow {{ image: none; width: 0px; height: 0px; }}
    QComboBox QAbstractItemView, QListView#completer {{
        background: {t.panel};
        border: none;
        border-radius: {radius}px;
        padding: {s(3)}px;
        outline: none;
        color: {fg};
        selection-background-color: {selected};
        selection-color: {fg};
    }}

    QPushButton#source {{
        background: {tray};
        border: none;
        border-radius: {radius}px;
        /* Asymmetric on purpose: the extra right padding is the lane the
           status mark is painted into. Without it a long label such as
           "Craigslist" runs straight through the tick. */
        padding: 0px {s(17)}px 0px {s(8)}px;
        color: {dim};
    }}
    QPushButton#source:hover {{ background: {tray_hover}; color: {fg}; }}
    QPushButton#source:checked {{ background: {selected}; color: {fg}; }}
    QPushButton#source:disabled {{ color: {rgba(t.foreground_dim, 0.35)}; }}

    /* The notice window. Unlike #panel it needs a ground of its own: it floats
       over whatever is behind the app, not over the app's own dark slab, so a
       3.5% white wash would leave it transparent. */
    QFrame#notice {{
        background: {t.panel};
        border: none;
        border-radius: {s(t.corner_radius)}px;
    }}
    QLabel#noticeTitle {{ color: {fg}; font-size: {s(Size.label_size + 3)}px; }}
    QLabel#noticeBody  {{ color: {rgba(t.foreground, 0.80)}; }}

    /* The sign-in link. Text only, like "Go, go, go." at a smaller size --
       it is an offer to fix something, not a control competing with the
       toggles above it. */
    QPushButton#signin {{
        background: transparent;
        border: none;
        padding: 0px;
        text-align: left;
        color: {dim};
        font-size: {s(Size.label_size)}px;
    }}
    QPushButton#signin:hover {{ color: {t.accent_hi}; }}
    QPushButton#signin:pressed {{ color: {fg}; }}

    /* "Go, go, go." -- the text and nothing else. No tray, no border, no fill. */
    QPushButton#go {{
        background: transparent;
        border: none;
        padding: 0px {s(9)}px;
        color: {dim};
    }}
    QPushButton#go:hover {{ color: {t.accent_hi}; }}
    QPushButton#go:pressed {{ color: {fg}; }}
    QPushButton#go:disabled {{ color: {rgba(t.foreground_dim, 0.35)}; }}

    /* ---- results ------------------------------------------------------ */

    QPushButton#tab {{
        background: transparent;
        border: none;
        padding: {s(2)}px {s(6)}px;
        color: {dim};
    }}
    QPushButton#tab:hover {{ color: {fg}; }}
    QPushButton#tab:checked {{ color: {t.accent_hi}; }}

    QLabel#note, QLabel#empty {{ color: {dim}; font-size: {s(Size.label_size)}px; }}

    QFrame#card, QFrame#discard {{
        background: {tray};
        border: none;
        border-radius: {radius}px;
    }}
    QFrame#card:hover {{ background: {tray_hover}; }}

    QLabel#cardTitle {{ color: {fg}; }}
    QLabel#cardMeta, QLabel#cardScore, QLabel#discardReason {{
        color: {dim};
        font-size: {s(Size.label_size)}px;
    }}
    QLabel#cardBody {{ color: {rgba(t.foreground, 0.72)}; }}
    QLabel#discardTitle {{ color: {rgba(t.foreground, 0.6)}; }}

    QPushButton#cardOpen {{
        background: transparent;
        border: none;
        padding: 0px {s(4)}px;
        color: {t.accent_hi};
    }}
    QPushButton#cardOpen:hover {{ color: {fg}; }}

    /* A matched phrase. Clicking it excludes it, so it has to look pressable. */
    QPushButton#chip {{
        background: {rgba(t.accent, 0.22)};
        border: none;
        border-radius: {s(3)}px;
        padding: {s(1)}px {s(5)}px;
        color: {rgba(t.foreground, 0.8)};
        font-size: {s(Size.label_size)}px;
    }}
    QPushButton#chip:hover {{
        background: {rgba(t.accent, 0.45)};
        color: {fg};
    }}

    QScrollArea#scroll {{ background: transparent; border: none; }}
    QScrollArea#scroll > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{
        background: transparent;
        width: {s(4)}px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: {rgba(t.foreground, 0.18)};
        border-radius: {s(2)}px;
        min-height: {s(20)}px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

    QToolTip {{
        background: {t.panel};
        color: {fg};
        border: none;
        padding: {s(4)}px {s(6)}px;
    }}
    """


def popup_stylesheet(t: Theme) -> str:
    """The completer and combo popups.

    These are separate top-level windows, so the main window's stylesheet never
    reaches them -- which is why the first version of the location field dropped a
    plain white list box over the page. They also need a near-opaque background of
    their own: nothing blurs behind a popup, so a low alpha here reads as a smear
    rather than as glass.
    """
    s = t.s
    return f"""
    QAbstractItemView {{
        background: {rgba(t.panel, 0.97)};
        border: none;
        border-radius: {s(t.control_radius)}px;
        padding: {s(3)}px;
        outline: none;
        color: {t.foreground};
        font-family: {t.font_family};
        font-size: {s(t.font_size)}px;
        selection-background-color: {rgba(t.accent, 0.45)};
        selection-color: {t.foreground};
    }}
    QAbstractItemView::item {{
        min-height: {s(Size.popup_row)}px;
        padding: 0px {s(6)}px;
        border-radius: {s(t.control_radius)}px;
        color: {t.foreground_dim};
    }}
    QAbstractItemView::item:selected {{
        background: {rgba(t.accent, 0.45)};
        color: {t.foreground};
    }}
    QScrollBar:vertical {{ width: 0px; background: transparent; }}
    """
