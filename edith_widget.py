import sys
import os
import threading
import time
import requests
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QTextBrowser, QLineEdit, QFrame, QLabel,
    QPushButton, QGraphicsDropShadowEffect, QSizeGrip,
    QStackedWidget, QListWidget, QListWidgetItem, QProgressBar,
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, QObject, QPropertyAnimation, QTimer,
    QMetaObject, Q_ARG,
)
from PyQt6.QtGui import QColor, QFont
from pynput import keyboard
from voice import MIC_IN_USE
import wake_listener

_BASE      = os.getenv("EDITH_BASE_URL", "http://127.0.0.1:8001")
API_URL    = f"{_BASE}/api/chat"
STREAM_URL = f"{_BASE}/api/chat/stream"
STATUS_URL = f"{_BASE}/api/status"

# ─── Neu Brutalism + Claymorphism Theme ───
BG          = "#0a0a0f"
SURFACE     = "#0a0a0f"
PANEL_BG    = "#12121a"
ACCENT      = "#00ff88"
ACCENT_DIM  = "#0a2018"
TEXT        = "#e0e0f0"
TEXT_DIM    = "#4a4a6a"
BORDER      = "#1e1e2e"
USER_BUBBLE = "#0a1a12"
BOT_BUBBLE  = "#12121a"
DANGER      = "#ff0055"
OK          = "#00ff88"
ACCENT2     = "#00d4ff"
ACCENT3     = "#ff00aa"


# ─── Hotkey Listener ───
class HotkeyListener(QObject):
    toggle_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.listener = None

    def start_listening(self):
        def on_activate():
            self.toggle_signal.emit()
        hotkey = keyboard.HotKey(keyboard.HotKey.parse("<ctrl>+<space>"), on_activate)
        def for_canonical(f):
            return lambda k: f(self.listener.canonical(k))
        self.listener = keyboard.Listener(
            on_press=for_canonical(hotkey.press),
            on_release=for_canonical(hotkey.release),
        )
        self.listener.start()


# ─── API Worker ───
class ApiWorker(QObject):
    response_signal = pyqtSignal(str, str)
    partial_signal  = pyqtSignal(str)
    loading_signal  = pyqtSignal(bool)

    def send_message(self, message):
        self.loading_signal.emit(True)
        try:
            with requests.post(STREAM_URL, json={"message": message}, stream=True, timeout=120) as res:
                if res.status_code == 200:
                    full_reply = ""
                    for line in res.iter_lines():
                        if line:
                            decoded = line.decode("utf-8")
                            if decoded.startswith("data: "):
                                content = decoded[6:]
                                if content == "[DONE]":
                                    break
                                elif content.startswith("[STREAM_ERROR]"):
                                    raise Exception(content)
                                else:
                                    full_reply += content
                                    self.partial_signal.emit(content)
                    self.response_signal.emit(full_reply, "chat")
                    return
            res = requests.post(API_URL, json={"message": message}, timeout=120)
            data = res.json()
            self.response_signal.emit(data.get("reply", "No reply."), data.get("intent", "chat"))
        except Exception as e:
            self.response_signal.emit(f"Connection Error: {e}", "error")
        finally:
            self.loading_signal.emit(False)


# ─── Voice Worker ───
class VoiceWorker(QObject):
    transcription_signal = pyqtSignal(str)
    status_signal        = pyqtSignal(str)

    def record_and_transcribe(self):
        MIC_IN_USE.set()
        wake_listener.pause()
        self.status_signal.emit("listening")
        try:
            from voice import listen, set_last_intent
            # FIX 1C: Set intent before listening
            set_last_intent("chat")
            text = listen()
            self.status_signal.emit("done")
            self.transcription_signal.emit((text or "").strip())
        except Exception as e:
            self.status_signal.emit("done")
            self.transcription_signal.emit(f"[Voice Error: {e}]")
        finally:
            MIC_IN_USE.clear()
            wake_listener.resume()


# ─── Main Widget ───
class EdithWidget(QWidget):
    # Signals for cross-thread UI updates
    dashboard_ready_sig = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool,
        )

        screen = QApplication.primaryScreen().availableGeometry()
        w, h = 500, 740
        self.setGeometry(screen.width() - w - 40, screen.height() // 2 - h // 2, w, h)

        self.is_visible = False
        self._drag_pos  = None

        # Thread-safe flags
        self._listening_event = threading.Event()   # SET = mic recording
        self._streaming_event = threading.Event()   # SET = tokens flowing

        self._last_reply = ""
        self._last_trace_id = ""

        self._build_ui()
        self._apply_style()

        # Fade animation
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(150)
        self.setWindowOpacity(0.0)

        # Hotkey
        self.hotkey_listener = HotkeyListener()
        self.hotkey_listener.toggle_signal.connect(self.toggle_visibility)
        threading.Thread(target=self.hotkey_listener.start_listening, daemon=True).start()

        # Workers
        self.api_worker = ApiWorker()
        self.api_worker.response_signal.connect(self._on_api_response)
        self.api_worker.partial_signal.connect(self._on_partial)
        self.api_worker.loading_signal.connect(self._on_loading)

        self.voice_worker = VoiceWorker()
        self.voice_worker.transcription_signal.connect(self._on_voice_result)
        self.voice_worker.status_signal.connect(self._on_voice_status)

        # Spinner
        self.spinner_timer = QTimer(self)
        self.spinner_timer.timeout.connect(self._tick_spinner)
        self._spinner_dots = 0

        # Dashboard 5s refresh
        self.dash_timer = QTimer(self)
        self.dash_timer.setInterval(5000)
        self.dash_timer.timeout.connect(self._refresh_dashboard)
        self.dashboard_ready_sig.connect(self._update_dashboard_ui)

        self.tts_thread = None

    # ─── UI Build ─────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(0)

        self.frame = QFrame(self)
        self.frame.setObjectName("MainFrame")

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        c = QColor(0, 255, 136)
        c.setAlpha(30)
        shadow.setColor(c)
        shadow.setOffset(4, 4)
        self.frame.setGraphicsEffect(shadow)

        fl = QVBoxLayout(self.frame)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(0)

        fl.addWidget(self._build_header())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_chat_page())    # index 0
        self.stack.addWidget(self._build_dashboard_page())  # index 1
        fl.addWidget(self.stack)

        root.addWidget(self.frame)

        self.sizegrip = QSizeGrip(self)
        self.sizegrip.setStyleSheet("width:12px;height:12px;background:transparent;")

    def _build_header(self):
        hdr = QFrame()
        hdr.setObjectName("Header")
        hdr.setFixedHeight(56)
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(16, 0, 12, 0)
        hl.setSpacing(10)

        dot = QLabel("●")
        dot.setStyleSheet(f"color:{OK};font-size:9px;padding-top:1px;"
                          f"background:transparent;")
        hl.addWidget(dot)

        title = QLabel("E.D.I.T.H")
        title.setFont(QFont("Space Grotesk", 14, QFont.Weight.Bold))
        title.setStyleSheet(
            f"color:{ACCENT};letter-spacing:4px;"
            f"background:transparent;"
        )
        hl.addWidget(title)
        hl.addStretch()

        self.mode_btn = QPushButton("📊")
        self.mode_btn.setObjectName("ModeBtn")
        self.mode_btn.setFixedSize(34, 34)
        self.mode_btn.setToolTip("Toggle Chat / Dashboard")
        self.mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_btn.clicked.connect(self._toggle_mode)
        hl.addWidget(self.mode_btn)

        close_btn = QPushButton("✕")
        close_btn.setObjectName("CloseBtn")
        close_btn.setFixedSize(34, 34)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.toggle_visibility)
        hl.addWidget(close_btn)

        return hdr

    def _build_chat_page(self):
        page = QFrame()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)

        self.chat_display = QTextBrowser()
        self.chat_display.setObjectName("ChatDisplay")
        self.chat_display.setOpenExternalLinks(True)
        pl.addWidget(self.chat_display)

        # Feedback bar (hidden until response)
        self.feedback_bar = QFrame()
        self.feedback_bar.setObjectName("FeedbackBar")
        self.feedback_bar.setFixedHeight(36)
        self.feedback_bar.hide()
        fb_l = QHBoxLayout(self.feedback_bar)
        fb_l.setContentsMargins(12, 0, 12, 0)
        fb_l.setSpacing(6)

        self.thumb_up = QPushButton("👍")
        self.thumb_up.setObjectName("FeedbackBtn")
        self.thumb_up.setFixedSize(30, 30)
        self.thumb_up.clicked.connect(lambda: self._send_feedback("thumbs_up"))
        fb_l.addWidget(self.thumb_up)

        self.thumb_down = QPushButton("👎")
        self.thumb_down.setObjectName("FeedbackBtn")
        self.thumb_down.setFixedSize(30, 30)
        self.thumb_down.clicked.connect(lambda: self._send_feedback("thumbs_down"))
        fb_l.addWidget(self.thumb_down)

        self.footer_label = QLabel("")
        self.footer_label.setStyleSheet(f"color:{TEXT_DIM};font-size:10px;")
        fb_l.addWidget(self.footer_label)
        fb_l.addStretch()
        pl.addWidget(self.feedback_bar)

        # Input area
        input_f = QFrame()
        input_f.setObjectName("InputArea")
        input_f.setFixedHeight(60)
        il = QHBoxLayout(input_f)
        il.setContentsMargins(10, 8, 10, 8)
        il.setSpacing(8)

        self.voice_btn = QPushButton("🎙")
        self.voice_btn.setObjectName("IconBtn")
        self.voice_btn.setFixedSize(38, 38)
        self.voice_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.voice_btn.clicked.connect(self._toggle_voice)
        il.addWidget(self.voice_btn)

        self.input_box = QLineEdit()
        self.input_box.setObjectName("InputBox")
        self.input_box.setPlaceholderText("Message E.D.I.T.H...")
        self.input_box.returnPressed.connect(self.send_message)
        self.input_box.setFont(QFont("Monospace", 11))
        il.addWidget(self.input_box)

        self.spinner_label = QLabel("")
        self.spinner_label.setFixedWidth(20)
        self.spinner_label.setStyleSheet(f"color:{ACCENT};font-size:14px;font-weight:bold;")
        il.addWidget(self.spinner_label)

        send_btn = QPushButton("↑")
        send_btn.setObjectName("SendBtn")
        send_btn.setFixedSize(38, 38)
        send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        send_btn.clicked.connect(self.send_message)
        il.addWidget(send_btn)

        pl.addWidget(input_f)
        return page

    def _build_dashboard_page(self):
        page = QFrame()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(12, 12, 12, 12)
        pl.setSpacing(10)

        # Providers panel
        prov_frame = QFrame()
        prov_frame.setObjectName("Panel")
        prov_l = QVBoxLayout(prov_frame)
        prov_l.setContentsMargins(10, 8, 10, 8)
        prov_l.setSpacing(4)
        prov_l.addWidget(self._section_label("Providers"))
        self.provider_labels = {}
        for p in ["groq", "gemini", "nvidia", "openrouter"]:
            row = QHBoxLayout()
            name_l = QLabel(p.capitalize())
            name_l.setStyleSheet(f"color:{TEXT};font-size:11px;")
            name_l.setFixedWidth(90)
            status_l = QLabel("○")
            status_l.setStyleSheet(f"color:{TEXT_DIM};font-size:11px;")
            calls_l = QLabel("")
            calls_l.setStyleSheet(f"color:{TEXT_DIM};font-size:10px;")
            row.addWidget(name_l)
            row.addWidget(status_l)
            row.addWidget(calls_l)
            row.addStretch()
            prov_l.addLayout(row)
            self.provider_labels[p] = (status_l, calls_l)
        pl.addWidget(prov_frame)

        # System panel
        sys_frame = QFrame()
        sys_frame.setObjectName("Panel")
        sys_l = QVBoxLayout(sys_frame)
        sys_l.setContentsMargins(10, 8, 10, 8)
        sys_l.setSpacing(6)
        sys_l.addWidget(self._section_label("System"))
        self.ram_bar = self._progress_row("RAM", sys_l)
        self.cpu_bar = self._progress_row("CPU", sys_l)
        pl.addWidget(sys_frame)

        # Recent traces
        traces_frame = QFrame()
        traces_frame.setObjectName("Panel")
        tr_l = QVBoxLayout(traces_frame)
        tr_l.setContentsMargins(10, 8, 10, 8)
        tr_l.setSpacing(4)
        tr_l.addWidget(self._section_label("API Usage (Today)"))
        self.traces_list = QListWidget()
        self.traces_list.setMaximumHeight(120)
        self.traces_list.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: none;
                color: {TEXT_DIM};
                font-size: 10px;
            }}
        """)
        tr_l.addWidget(self.traces_list)
        pl.addWidget(traces_frame)

        pl.addStretch()

        self.dash_status_label = QLabel("Refreshing...")
        self.dash_status_label.setStyleSheet(f"color:{TEXT_DIM};font-size:9px;")
        pl.addWidget(self.dash_status_label)

        return page

    def _section_label(self, text):
        lbl = QLabel(text.upper())
        lbl.setStyleSheet(f"color:{ACCENT};font-size:9px;letter-spacing:2px;font-weight:bold;")
        return lbl

    def _progress_row(self, label, layout):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(36)
        lbl.setStyleSheet(f"color:{TEXT};font-size:11px;")
        bar = QProgressBar()
        bar.setFixedHeight(8)
        bar.setTextVisible(False)
        bar.setStyleSheet(f"""
            QProgressBar {{
                background:{PANEL_BG};
                border:1px solid {BORDER};
                border-radius:4px;
            }}
            QProgressBar::chunk {{
                background:{ACCENT};
                border-radius:4px;
            }}
        """)
        val_lbl = QLabel("0%")
        val_lbl.setFixedWidth(36)
        val_lbl.setStyleSheet(f"color:{TEXT_DIM};font-size:10px;")
        row.addWidget(lbl)
        row.addWidget(bar)
        row.addWidget(val_lbl)
        layout.addLayout(row)
        return bar, val_lbl

    # ─── Style ────────────────────────────────────
    def _apply_style(self):
        self.setStyleSheet(f"""
            * {{
                font-family: "Space Grotesk", "Ubuntu", sans-serif;
            }}
            QWidget {{
                background: {BG};
                color: {TEXT};
            }}

            /* ── Main frame: claymorphism ── */
            QFrame#MainFrame {{
                background: {BG};
                border-radius: 20px;
                border: 2px solid {BORDER};
            }}

            /* ── Header: neu brutalism hard border ── */
            QFrame#Header {{
                background: #0d0d18;
                border-bottom: 2px solid {ACCENT};
                border-top-left-radius: 18px;
                border-top-right-radius: 18px;
            }}

            /* ── Chat display ── */
            QTextBrowser#ChatDisplay {{
                background: {BG};
                border: none;
                color: {TEXT};
                font-size: 13px;
                padding: 8px 12px;
                selection-background-color: {ACCENT_DIM};
            }}

            /* ── Scrollbar ── */
            QScrollBar:vertical {{
                background: transparent;
                width: 4px;
                border-radius: 2px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(0, 255, 136, 0.2);
                border-radius: 2px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: rgba(0, 255, 136, 0.4);
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0;
            }}

            /* ── Feedback bar ── */
            QFrame#FeedbackBar {{
                background: #0d0d18;
                border-top: 1px solid {BORDER};
            }}

            /* ── Input area: clay pill ── */
            QFrame#InputArea {{
                background: #0d0d18;
                border-top: 2px solid {BORDER};
                border-bottom-left-radius: 18px;
                border-bottom-right-radius: 18px;
            }}

            /* ── Input box ── */
            QLineEdit#InputBox {{
                background: #12121a;
                color: {TEXT};
                border: 2px solid {BORDER};
                border-radius: 18px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 500;
            }}
            QLineEdit#InputBox:focus {{
                border: 2px solid {ACCENT};
                background: #0e1a12;
            }}

            /* ── Send button: acid green clay ── */
            QPushButton#SendBtn {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #00ff88, stop:1 #00d4cc);
                color: #0a0a0f;
                border: none;
                border-radius: 10px;
                font-size: 18px;
                font-weight: bold;
            }}
            QPushButton#SendBtn:hover {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                    stop:0 #33ffaa, stop:1 #00f0e0);
            }}
            QPushButton#SendBtn:pressed {{
                background: #00cc66;
            }}

            /* ── Icon buttons ── */
            QPushButton#IconBtn {{
                background: #12121a;
                color: {TEXT_DIM};
                border: 2px solid {BORDER};
                border-radius: 10px;
                font-size: 16px;
            }}
            QPushButton#IconBtn:hover {{
                background: rgba(0, 255, 136, 0.06);
                border: 2px solid rgba(0, 255, 136, 0.25);
                color: {ACCENT};
            }}

            /* ── Mode/Dashboard button ── */
            QPushButton#ModeBtn {{
                background: #12121a;
                color: {TEXT_DIM};
                border: 2px solid {BORDER};
                border-radius: 10px;
                font-size: 14px;
            }}
            QPushButton#ModeBtn:hover {{
                background: rgba(0, 212, 255, 0.06);
                border: 2px solid rgba(0, 212, 255, 0.25);
                color: {ACCENT2};
            }}

            /* ── Close button ── */
            QPushButton#CloseBtn {{
                background: transparent;
                color: {TEXT_DIM};
                border: none;
                font-size: 13px;
                border-radius: 8px;
                padding: 4px 8px;
            }}
            QPushButton#CloseBtn:hover {{
                background: rgba(255, 0, 85, 0.12);
                color: {DANGER};
                border: 1px solid rgba(255, 0, 85, 0.3);
            }}

            /* ── Feedback buttons ── */
            QPushButton#FeedbackBtn {{
                background: transparent;
                border: none;
                font-size: 15px;
                border-radius: 6px;
                padding: 2px 4px;
            }}
            QPushButton#FeedbackBtn:hover {{
                background: rgba(0, 255, 136, 0.08);
            }}

            /* ── Dashboard panels: brutal card ── */
            QFrame#Panel {{
                background: #12121a;
                border: 2px solid {BORDER};
                border-radius: 12px;
            }}

            QListWidget {{
                background: transparent;
                border: none;
                color: {TEXT_DIM};
                font-size: 11px;
            }}

            QProgressBar {{
                background: #0a0a14;
                border: 1px solid {BORDER};
                border-radius: 4px;
                height: 8px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {ACCENT}, stop:1 {ACCENT2});
                border-radius: 4px;
            }}
        """)

    # ─── Toggle Mode ──────────────────────────────
    def _toggle_mode(self):
        if self.stack.currentIndex() == 0:
            self.stack.setCurrentIndex(1)
            self.mode_btn.setText("💬")
            self.mode_btn.setToolTip("Switch to Chat")
            self.dash_timer.start()
            self._refresh_dashboard()
        else:
            self.stack.setCurrentIndex(0)
            self.mode_btn.setText("📊")
            self.mode_btn.setToolTip("Switch to Dashboard")
            self.dash_timer.stop()

    # ─── Dashboard Refresh ────────────────────────
    def _refresh_dashboard(self):
        threading.Thread(target=self._fetch_dashboard_data, daemon=True).start()

    def _fetch_dashboard_data(self):
        try:
            data = requests.get(STATUS_URL, timeout=4).json()
            self.dashboard_ready_sig.emit(data)
        except Exception as e:
            self.dashboard_ready_sig.emit({"error": str(e)})

    def _update_dashboard_ui(self, data):
        if "error" in data:
            self.dash_status_label.setText(f"⚠ {data['error'][:60]}")
            return

        providers = data.get("providers", {})
        for p, (status_lbl, calls_lbl) in self.provider_labels.items():
            info = providers.get(p, {})
            if not info.get("has_key"):
                status_lbl.setText("○")
                status_lbl.setStyleSheet(f"color:{TEXT_DIM};font-size:11px;")
            elif not info.get("cooled") or not info.get("under_limit"):
                status_lbl.setText("⚠")
                status_lbl.setStyleSheet(f"color:#ffaa00;font-size:11px;")
            else:
                status_lbl.setText("●")
                status_lbl.setStyleSheet(f"color:{OK};font-size:11px;")
            calls = info.get("daily_calls", 0)
            limit = info.get("daily_limit", "∞")
            calls_lbl.setText(f"{calls}/{limit}")

        sys_data = data.get("system", {})
        ram = sys_data.get("ram", {})
        if ram:
            pct = int(ram.get("percent", 0))
            bar, lbl = self.ram_bar
            bar.setValue(pct)
            lbl.setText(f"{pct}%")

        cpu = sys_data.get("cpu", {})
        if cpu:
            pct = int(cpu.get("percent", 0))
            bar, lbl = self.cpu_bar
            bar.setValue(pct)
            lbl.setText(f"{pct}%")

        ts = data.get("timestamp", "")[:19].replace("T", " ")
        self.dash_status_label.setText(f"Updated {ts}")

    # ─── Visibility ───────────────────────────────
    def toggle_visibility(self):
        if self.is_visible:
            self.anim.setStartValue(1.0)
            self.anim.setEndValue(0.0)
            try:
                self.anim.finished.disconnect(self.hide)
            except TypeError:
                pass
            self.anim.finished.connect(self.hide)
            self.is_visible = False
            self.dash_timer.stop()
            wake_listener.resume()
        else:
            self.show()
            self.raise_()
            self.activateWindow()
            self.input_box.setFocus()
            try:
                self.anim.finished.disconnect(self.hide)
            except TypeError:
                pass
            self.anim.setStartValue(0.0)
            self.anim.setEndValue(1.0)
            self.is_visible = True
            if self.chat_display.toPlainText() == "":
                self._append_bot("Systems online. How can I help, Boss?")
        self.anim.start()

    # ─── Drag ─────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if not isinstance(self.childAt(event.pos()), QPushButton):
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.sizegrip.move(self.width() - 18, self.height() - 18)

    # ─── Chat ─────────────────────────────────────
    def _append_user(self, text):
        safe = text.replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        html = (
            f'<table width="100%" style="margin:6px 0;">'
            f'<tr><td width="18%"></td>'
            f'<td width="82%" align="right">'
            f'<div style="background:{USER_BUBBLE};'
            f'border:1px solid rgba(0,255,136,0.25);'
            f'border-radius:16px 4px 16px 16px;'
            f'padding:10px 14px;color:rgba(200,255,220,0.9);'
            f'font-size:12px;line-height:1.6;">{safe}</div>'
            f'</td></tr></table>'
        )
        self.chat_display.append(html)
        self._scroll_bottom()

    def _append_bot(self, text, intent="", provider="", latency=""):
        safe = text.replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        footer = ""
        if intent or provider or latency:
            parts = [x for x in [intent, provider, latency] if x]
            footer = (f'<br><span style="color:rgba(0,255,136,0.3);'
                      f'font-size:9px;letter-spacing:1px;">'
                      f'{" · ".join(parts)}</span>')
        html = (
            f'<table width="100%" style="margin:6px 0;">'
            f'<tr><td width="82%" align="left">'
            f'<div style="background:{BOT_BUBBLE};'
            f'border:1px solid rgba(0,255,136,0.1);'
            f'border-radius:4px 16px 16px 16px;'
            f'padding:10px 14px;color:{TEXT};font-size:12px;line-height:1.6;">'
            f'<span style="color:{ACCENT};font-size:9px;font-weight:bold;'
            f'letter-spacing:2px;">E.D.I.T.H.</span><br>'
            f'{safe}{footer}</div>'
            f'</td><td width="18%"></td></tr></table>'
        )
        self.chat_display.append(html)
        self._scroll_bottom()

    def _scroll_bottom(self):
        sb = self.chat_display.verticalScrollBar()
        sb.setValue(sb.maximum())

    def send_message(self):
        text = self.input_box.text().strip()
        if not text:
            return
        self._append_user(text)
        self.input_box.clear()
        self.feedback_bar.hide()
        self._streaming_event.clear()
        self._streaming_buffer = ""
        self._t_start = time.time()
        self.input_box.setPlaceholderText("Thinking...")
        threading.Thread(target=self.api_worker.send_message, args=(text,), daemon=True).start()

    # ─── API Response Handlers ────────────────────
    def _on_loading(self, loading):
        if loading:
            self._spinner_dots = 1
            self.spinner_label.setText(".")
            self.spinner_timer.start(300)
        else:
            self.spinner_timer.stop()
            self.spinner_label.setText("")

    def _on_partial(self, token):
        # Accumulate tokens — render complete reply only once done.
        # QTextBrowser HTML tables can't be updated in-place after append().
        self._streaming_event.set()
        self._streaming_buffer += token

    def _on_api_response(self, reply, intent):
        self._streaming_event.clear()
        # Use buffered tokens if stream delivered content, else use reply directly
        final = self._streaming_buffer.strip() if self._streaming_buffer.strip() else reply
        self._streaming_buffer = ""
        self._last_reply = final
        self._last_trace_id = f"trace_{int(time.time())}"
        latency = f"{time.time() - getattr(self, '_t_start', time.time()):.1f}s"

        self._append_bot(final, intent=intent, latency=latency)
        self.input_box.setPlaceholderText("Message E.D.I.T.H...")
        self.footer_label.setText(f"intent:{intent} · {latency}")
        self.feedback_bar.show()

        # TTS (non-blocking, first 2 sentences)
        if reply and not reply.startswith("Connection Error"):
            def _tts(t):
                import re as _re
                import logging as _log
                _wlog = _log.getLogger("edith.widget")
                sentences = _re.split(r"(?<=[.!?]) +", t)
                snippet = " ".join(sentences[:2])[:300]
                try:
                    from voice import speak
                    speak(snippet)
                except Exception as _e:
                    _wlog.warning(f"Widget TTS error: {_e}")
            # FIX 1D: Only launch TTS if not already active
            from voice import _tts_active
            if not _tts_active.is_set():
                if not (self.tts_thread and self.tts_thread.is_alive()):
                    self.tts_thread = threading.Thread(target=_tts, args=(reply,), daemon=True)
                    self.tts_thread.start()

    def _send_feedback(self, fb):
        trace_id = self._last_trace_id
        def _post():
            try:
                requests.post(
                    f"{_BASE}/api/feedback",
                    json={"trace_id": trace_id, "feedback": fb},
                    timeout=4,
                )
            except Exception:
                pass
        threading.Thread(target=_post, daemon=True).start()
        self.thumb_up.setEnabled(False)
        self.thumb_down.setEnabled(False)
        icon = "✅" if fb == "thumbs_up" else "❌"
        self.footer_label.setText(f"{self.footer_label.text()} · {icon}")

    # ─── Spinner ──────────────────────────────────
    def _tick_spinner(self):
        self._spinner_dots = (self._spinner_dots % 3) + 1
        self.spinner_label.setText("." * self._spinner_dots)

    # ─── Voice ────────────────────────────────────
    def _toggle_voice(self):
        if self._listening_event.is_set():
            return
        self._listening_event.set()
        self.voice_btn.setText("🔴")
        self.voice_btn.setStyleSheet("background:#7f1d1d;color:#ff4444;border-radius:8px;")
        self.input_box.setPlaceholderText("Listening...")
        # Warmup Chatterbox on mic-activate — absorbs 70s cold-start before TTS needed
        def _warmup_cb():
            try:
                from config import USE_CHATTERBOX
                if USE_CHATTERBOX:
                    from voice import _get_chatterbox_worker
                    _get_chatterbox_worker()
            except Exception:
                pass
        threading.Thread(target=_warmup_cb, daemon=True, name="chatterbox-warmup-widget").start()
        threading.Thread(target=self.voice_worker.record_and_transcribe, daemon=True).start()

    def _on_voice_status(self, status):
        if status != "listening":
            self._listening_event.clear()
            self.voice_btn.setText("🎙")
            self.voice_btn.setStyleSheet("")
            self.input_box.setPlaceholderText("Message E.D.I.T.H...")

    def _on_voice_result(self, text):
        if text and not text.startswith("[Voice Error"):
            self.input_box.setText(text)
            self.send_message()
        elif text.startswith("[Voice Error"):
            self._append_bot(text)

    # ─── Cleanup ──────────────────────────────────
    def hideEvent(self, event):
        MIC_IN_USE.clear()
        wake_listener.resume()
        super().hideEvent(event)

    def closeEvent(self, event):
        MIC_IN_USE.clear()
        wake_listener.resume()
        self.dash_timer.stop()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    widget = EdithWidget()
    sys.exit(app.exec())
