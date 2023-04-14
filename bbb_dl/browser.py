# Original Source: https://doc.qt.io/qtforpython-6/examples/example_webenginewidgets_widgetsnanobrowser.html
# Copyright (C) 2022 The Qt Company Ltd.

import argparse
import os
import sys
from http.cookiejar import Cookie

# pylint: disable = no-name-in-module
from PySide6.QtCore import QLoggingCategory, QUrl, Slot
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QStyle,
    QToolBar,
)

import bbb_dl.main as bbb_dl
from bbb_dl.utils import BBBDLCookieJar
from bbb_dl.utils import PathTools as PT
from bbb_dl.utils import load_mozilla_cookies_into_qt_cookie_store


class BrowserWindow(QMainWindow):
    def __init__(self, args):
        super().__init__()
        self.working_dir = bbb_dl.BBBDL.get_working_dir(args.working_dir)
        self.cookies_path = PT.make_path(self.working_dir, "cookies.txt")
        self.cookie_jar = BBBDLCookieJar(self.cookies_path)
        self.setWindowTitle('BBB Browser')

        if args.verbose is None or not args.verbose:
            web_engine_context_log = QLoggingCategory("qt.webenginecontext")
            web_engine_context_log.setFilterRules("*.info=false")

        self.toolBar = QToolBar()
        self.addToolBar(self.toolBar)
        self.backButton = QPushButton()
        self.backButton.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        self.backButton.clicked.connect(self.back)
        self.toolBar.addWidget(self.backButton)
        self.forwardButton = QPushButton()
        self.forwardButton.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        self.forwardButton.clicked.connect(self.forward)
        self.toolBar.addWidget(self.forwardButton)

        self.addressLineEdit = QLineEdit()
        self.addressLineEdit.returnPressed.connect(self.load)
        self.toolBar.addWidget(self.addressLineEdit)

        self.webEngineView = QWebEngineView()

        # We use the off-the-record mode to not use persistent storage
        self.profile = QWebEngineProfile(self.webEngineView)
        self.cookie_store = self.profile.cookieStore()
        if os.path.isfile(self.cookies_path):
            self.cookie_jar.load(ignore_discard=True, ignore_expires=True)
            load_mozilla_cookies_into_qt_cookie_store(self.cookie_jar, self.cookie_store)

        self.cookie_store.cookieAdded.connect(self.handle_cookie_added)
        self.profile.settings().setAttribute(QWebEngineSettings.JavascriptEnabled, True)

        webpage = QWebEnginePage(self.profile, self)
        self.webEngineView.setPage(webpage)

        self.setCentralWidget(self.webEngineView)
        initialUrl = 'https://www.startpage.com/'
        self.addressLineEdit.setText(initialUrl)
        self.webEngineView.load(QUrl(initialUrl))
        self.webEngineView.page().titleChanged.connect(self.setWindowTitle)
        self.webEngineView.page().urlChanged.connect(self.urlChanged)

    def closeEvent(self, event):
        self.cookie_jar.save(ignore_discard=True, ignore_expires=True)

    def handle_cookie_added(self, qt_cookie: QNetworkCookie):
        # print("added {name} : {value}".format(name=qt_cookie.name(), value=qt_cookie.value()))
        exp = qt_cookie.expirationDate().toSecsSinceEpoch()
        if exp <= 0:
            exp = 2147483647
        new_cookie = Cookie(
            version=None,
            name=qt_cookie.name().data().decode('utf-8'),
            value=qt_cookie.value().data().decode('utf-8'),
            port=None,
            port_specified=False,
            domain=qt_cookie.domain(),
            domain_specified=True,
            domain_initial_dot=qt_cookie.domain().startswith("."),  # should be always true
            path=qt_cookie.path(),
            path_specified=True,
            secure=qt_cookie.isSecure(),
            expires=exp,
            discard=False,
            comment=None,
            comment_url=None,
            rest=None,
            rfc2109=False,
        )
        self.cookie_jar.set_cookie(new_cookie)

    @Slot()
    def load(self):
        url = QUrl.fromUserInput(self.addressLineEdit.text())
        if url.isValid():
            self.webEngineView.load(url)

    @Slot()
    def back(self):
        self.webEngineView.page().triggerAction(QWebEnginePage.Back)

    @Slot()
    def forward(self):
        self.webEngineView.page().triggerAction(QWebEnginePage.Forward)

    @Slot(QUrl)
    def urlChanged(self, url):
        self.addressLineEdit.setText(url.toString())


def get_parser():
    parser = argparse.ArgumentParser(description=('Browser for BBB-DL'))
    parser.add_argument(
        '-wd',
        '--working-dir',
        type=str,
        default=None,
        help='Optional output directory for all temporary directories/files',
    )

    parser.add_argument(
        '-v',
        '--verbose',
        action='store_true',
        help=('Print more verbose debug information'),
    )
    return parser


# --- called at the program invocation: -------------------------------------
def main(args=None):
    args, _ = get_parser().parse_known_args(args)
    app = QApplication(sys.argv)
    mainWin = BrowserWindow(args)
    availableGeometry = mainWin.screen().availableGeometry()
    mainWin.resize(availableGeometry.width() * 2 / 3, availableGeometry.height() * 2 / 3)
    mainWin.show()
    app.exec()

    sys.exit()
