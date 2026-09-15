"""The one window that explains why a source did not just work.

WHY A WINDOW AND NOT A LABEL

The panel used to carry two lines of standing text -- "Sign in to Facebook  Sign
in to X" and "Unavailable: My feeds (no feeds set), Reviews (needs a key)". They
were honest and they were always there, taking two rows of a window whose height
is its scarcest resource, to answer a question the user asks about twice.

So the answer moved to where the question is asked: **click the source.** A
source that cannot run says why at the moment you reach for it, offers the one
link that fixes it, and goes away again.
"""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from .theme import Size, Theme, stylesheet

#: What a source behind a login says. His words, and the reason they are his:
#: this is a program he runs on his own machine, and it talks to him the way he
#: talks to himself. Branch never sees the password either way -- the link opens
#: the service's own form, in Branch's own browser.
LOGIN_MESSAGE = (
    "This source requires an account.\n\n"
    "Make a burner. Here's the link, or log in, which you should have "
    "done... dumbass."
)


class SourceNotice(QDialog):
    """Why this source cannot run, and the one thing that would change it."""

    def __init__(self, theme: Theme, title: str, message: str,
                 link: str = "", link_label: str = "", parent=None) -> None:
        super().__init__(parent)
        self._link = link
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        self.setStyleSheet(stylesheet(theme))

        # The content sits inside a frame with its own ground. The window itself
        # is translucent so the corners can be round, which means whatever is
        # behind the app shows through anything that does not paint itself.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("notice")
        outer.addWidget(card)

        pad = theme.s(Size.pad * 2)
        box = QVBoxLayout(card)
        box.setContentsMargins(pad, pad, pad, pad)
        box.setSpacing(theme.s(Size.gap))

        heading = QLabel(title)
        heading.setObjectName("noticeTitle")
        box.addWidget(heading)

        body = QLabel(message)
        body.setObjectName("noticeBody")
        body.setWordWrap(True)
        body.setMinimumWidth(theme.s(300))
        box.addWidget(body)

        row = QHBoxLayout()
        row.setSpacing(theme.s(Size.gap))
        row.addStretch(1)
        if link:
            opener = QPushButton(link_label or "Open the sign-in page")
            opener.setObjectName("source")
            opener.setFixedHeight(theme.s(Size.pill_h))
            opener.setCursor(Qt.PointingHandCursor)
            opener.clicked.connect(self._open)
            row.addWidget(opener)
        close = QPushButton("Close")
        close.setObjectName("source")
        close.setFixedHeight(theme.s(Size.pill_h))
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.reject)
        row.addWidget(close)
        box.addLayout(row)

    def _open(self) -> None:
        """Accept with the link chosen. The caller decides where it opens --
        Branch's own browser for a sign-in, so the session is the one scans use,
        and only the system browser for anything else."""
        self.done(QDialog.Accepted)

    @property
    def link(self) -> str:
        return self._link


def open_externally(url: str) -> None:
    if url:
        webbrowser.open(url)
