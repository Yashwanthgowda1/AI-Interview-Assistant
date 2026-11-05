"""
main.py — Interview Proxy Chatbot
==================================
Features:
  • Always-on-top, semi-transparent, compact overlay window
  • HIDDEN from screen-share / screen-capture (Zoom, Teams, Meet, OBS)
  • Type a question  OR  click 🎙 to dictate via voice
  • Click 📷 Analyse Screen to OCR the screen and auto-fill the question
  • Answers pulled from Groq / Ollama / Mistral / OpenAI
  • Web search (DuckDuckGo, no key needed) enriches every answer
  • Provider / model / API-key settings panel
  • Global hotkey  Ctrl+Shift+Space  to show/hide
"""
from __future__ import annotations
import sys, os, logging, threading, html, faulthandler
from typing import Optional
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=True)

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QComboBox, QFrame,
    QSizePolicy, QSplitter, QScrollArea, QDialog, QFormLayout,
    QDialogButtonBox, QCheckBox, QSpinBox, QTabWidget, QGroupBox,
    QToolButton, QStatusBar, QFileDialog, QMenu,
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize, QPoint,
)
from PyQt5.QtGui import (
    QFont, QColor, QPalette, QTextCursor, QKeySequence, QIcon,
)

from stealth import apply_stealth, remove_stealth
from ai_client import AIClient, GROQ_MODELS, OLLAMA_MODELS, MISTRAL_MODELS
from search_client import format_context
from voice_client import VoiceListener
from meeting_listener import MeetingListener
from image_client import capture_screen, pil_to_qpixmap
from resume_client import parse_resume, summarise_for_prompt

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
faulthandler.enable()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Worker thread — runs AI + web-search off the GUI thread
# ─────────────────────────────────────────────────────────────────────────────
_WEB_KEYWORDS = (
    "latest", "current", "today", "recent", "2024", "2025", "2026", "news",
    "who is", "when did", "how much", "price", "version", "release", "update",
)


def _needs_web(question: str) -> bool:
    """Only search the web for questions that need current/factual info.
    Coding, concept and behavioural interview answers don't need it — skipping
    the search removes seconds of latency."""
    q = question.lower()
    return any(kw in q for kw in _WEB_KEYWORDS)


class AnswerWorker(QThread):
    answer_ready  = pyqtSignal(str)
    status_update = pyqtSignal(str)
    error         = pyqtSignal(str)

    def __init__(self, question: str, ai: AIClient, use_web: bool,
                 resume: str = "", history: list = None):
        super().__init__()
        self.question = question
        self.ai       = ai
        self.use_web  = use_web
        self.resume   = resume
        self.history  = history or []

    def run(self):
        try:
            import concurrent.futures
            context = ""
            if self.use_web and _needs_web(self.question):
                self.status_update.emit("Searching + thinking…")
                try:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                        web_future = ex.submit(format_context, self.question)
                        context = web_future.result(timeout=2)
                except concurrent.futures.TimeoutError:
                    context = ""
            else:
                self.status_update.emit("Thinking…")
            answer = self.ai.chat(self.question, context=context,
                                  resume=self.resume, history=self.history)
            if answer.startswith(("Error:", "Groq API key not set.", "Mistral API key not set.",
                                  "OpenAI API key not set.", "Unknown provider selected.",
                                  "Model '")):
                self.error.emit(answer)
            else:
                self.answer_ready.emit(answer)
        except Exception as exc:
            self.error.emit(str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Worker thread — runs vision analysis off the GUI thread
# ─────────────────────────────────────────────────────────────────────────────
class ScreenAnalysisWorker(QThread):
    question_extracted = pyqtSignal(str)
    offline_text_extracted = pyqtSignal(str)
    error              = pyqtSignal(str)

    def __init__(self, image, provider: str, api_key: str, model: str, ollama_url: str):
        super().__init__()
        self.image = image
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.ollama_url = ollama_url

    def run(self):
        try:
            from image_client import extract_question_from_screen, extract_text_offline
            if self.provider != "ollama" and not self.api_key.strip():
                text = extract_text_offline(self.image)
                self.offline_text_extracted.emit(text)
                return

            text = extract_question_from_screen(
                self.image,
                self.provider,
                api_key=self.api_key,
                model=self.model,
                ollama_url=self.ollama_url,
            )
            self.question_extracted.emit(text)
        except Exception as exc:
            self.error.emit(str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# Worker — filters meeting audio: only answer if it's an interview question
# ─────────────────────────────────────────────────────────────────────────────
QUESTION_FILTER_PROMPT = """You are a filter. Decide if the text below is an interview question that needs an answer.

An interview question is: a technical question, a behavioural question, "tell me about", "explain", "describe",
"what is", "how do you", "have you worked on", "what would you do", "write code for", or asking about skills/experience.

NOT a question: greetings, filler words, "ok", "sure", "let me share", "can you hear me", "unmute",
background conversation, incomplete sentences under 5 words.

Reply with EXACTLY one word: YES or NO"""


class MeetingFilterWorker(QThread):
    is_question  = pyqtSignal(str)   # emits original text if it IS a question
    not_question = pyqtSignal(str)   # emits text if it is NOT a question
    error        = pyqtSignal(str)

    def __init__(self, text: str, ai: AIClient, resume: str, use_web: bool):
        super().__init__()
        self.text     = text
        self.ai       = ai
        self.resume   = resume
        self.use_web  = use_web

    def run(self):
        try:
            verdict = self.ai.chat(
                self.text,
                system=QUESTION_FILTER_PROMPT,
                resume=""
            ).strip()

            if not verdict:
                self.error.emit("AI question filter returned an empty response.")
                return

            if verdict.startswith(("Error:", "Groq API key not set.", "Mistral API key not set.",
                                   "OpenAI API key not set.", "Unknown provider selected.")):
                self.error.emit(verdict)
                return

            if verdict.upper().startswith("YES"):
                self.is_question.emit(self.text)
            else:
                self.not_question.emit(self.text)
        except Exception as exc:
            self.error.emit(f"Meeting question filter failed: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Qt signal bridge — lets the meeting listener thread emit into the GUI thread
# ─────────────────────────────────────────────────────────────────────────────
class _MeetingTextSignal(QThread):
    text_ready = pyqtSignal(str)
    error_ready = pyqtSignal(str)
    def run(self): pass


# ─────────────────────────────────────────────────────────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, ai: AIClient, parent=None):
        super().__init__(parent)
        self.ai = ai
        self.setWindowTitle("Settings")
        self.setMinimumWidth(440)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)

        # ── AI provider tab ──────────────────────────────────────
        ai_tab = QWidget()
        form = QFormLayout(ai_tab)

        self.provider_cb = QComboBox()
        self.provider_cb.addItems(["groq", "ollama", "mistral", "openai"])
        self.provider_cb.setCurrentText(self.ai.provider)
        self.provider_cb.currentTextChanged.connect(self._on_provider_change)
        form.addRow("Provider:", self.provider_cb)

        self.model_cb = QComboBox()
        self.model_cb.setEditable(True)
        self._populate_models(self.ai.provider)
        form.addRow("Model:", self.model_cb)

        self.api_key_le = QLineEdit()
        self.api_key_le.setEchoMode(QLineEdit.Password)
        self.api_key_le.setPlaceholderText("API key (leave blank to use .env)")
        self.api_key_le.setText(self.ai.api_key)
        form.addRow("API Key:", self.api_key_le)

        self.ollama_url_le = QLineEdit(self.ai.ollama_url)
        form.addRow("Ollama URL:", self.ollama_url_le)

        tabs.addTab(ai_tab, "AI Provider")

        # ── Buttons ──────────────────────────────────────────────
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _on_provider_change(self, provider: str):
        self._populate_models(provider)

    def _populate_models(self, provider: str):
        self.model_cb.clear()
        models = AIClient.models_for(provider)
        if models:
            self.model_cb.addItems(models)
        current = self.ai.model if self.ai.model else (models[0] if models else "")
        self.model_cb.setCurrentText(current)

    def get_values(self):
        return {
            "provider": self.provider_cb.currentText(),
            "model":    self.model_cb.currentText(),
            "api_key":  self.api_key_le.text(),
            "ollama_url": self.ollama_url_le.text(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Screenshot preview dialog
# ─────────────────────────────────────────────────────────────────────────────
class ScreenshotDialog(QDialog):
    def __init__(self, pixmap, ocr_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Screen Capture — OCR Result")
        self.setMinimumSize(700, 500)
        layout = QVBoxLayout(self)

        lbl = QLabel()
        lbl.setPixmap(pixmap.scaledToWidth(660, Qt.SmoothTransformation))
        lbl.setAlignment(Qt.AlignCenter)
        scroll = QScrollArea()
        scroll.setWidget(lbl)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll, 3)

        layout.addWidget(QLabel("Extracted Text (edit before sending):"))
        self.text_edit = QTextEdit(ocr_text)
        self.text_edit.setMinimumHeight(100)
        layout.addWidget(self.text_edit, 2)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def get_text(self) -> str:
        return self.text_edit.toPlainText().strip()


# ─────────────────────────────────────────────────────────────────────────────
# Main window
# ─────────────────────────────────────────────────────────────────────────────
DARK_STYLE = """
QMainWindow, QWidget {
    background-color: #1a1a2e;
    color: #e0e0e0;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}
QTextEdit, QLineEdit {
    background-color: #16213e;
    border: 1px solid #0f3460;
    border-radius: 6px;
    padding: 6px;
    color: #e0e0e0;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
}
QPushButton {
    background-color: #0f3460;
    color: #e0e0e0;
    border: none;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: bold;
}
QPushButton:hover   { background-color: #1a4a80; }
QPushButton:pressed { background-color: #0a2844; }
QPushButton#sendBtn {
    background-color: #e94560;
    font-size: 14px;
}
QPushButton#sendBtn:hover { background-color: #ff5577; }
QPushButton#voiceBtn {
    background-color: #157347;
    font-size: 16px;
    padding: 7px 12px;
}
QPushButton#voiceBtn[active="true"] {
    background-color: #c0392b;
}
QPushButton#meetingBtn {
    background-color: #6a0dad;
    font-size: 13px;
}
QPushButton#meetingBtn:hover { background-color: #8a2be2; }
QPushButton#meetingBtn[active="true"] {
    background-color: #c0392b;
}
QComboBox {
    background-color: #16213e;
    border: 1px solid #0f3460;
    border-radius: 4px;
    padding: 4px 8px;
    color: #e0e0e0;
}
QComboBox QAbstractItemView {
    background-color: #16213e;
    color: #e0e0e0;
}
QLabel#titleLabel {
    font-size: 15px;
    font-weight: bold;
    color: #e94560;
}
QFrame#divider {
    background-color: #0f3460;
    max-height: 1px;
}
QStatusBar {
    background-color: #0d0d1a;
    color: #888;
    font-size: 11px;
}
QScrollBar:vertical {
    background: #16213e;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #0f3460;
    border-radius: 4px;
}
"""


class MainWindow(QMainWindow):
    _visibility_toggle_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._visibility_toggle_requested.connect(self._toggle_visibility)
        _provider = os.getenv("AI_PROVIDER", "groq")
        _key_map = {
            "groq":    os.getenv("GROQ_API_KEY", ""),
            "mistral": os.getenv("MISTRAL_API_KEY", ""),
            "openai":  os.getenv("OPENAI_API_KEY", ""),
            "ollama":  "",
        }
        self.ai = AIClient(
            provider=_provider,
            model=os.getenv("AI_MODEL", ""),
            api_key=_key_map.get(_provider, ""),
        )
        self.voice_listener: Optional[VoiceListener] = None
        self.voice_active = False
        self.meeting_listener: Optional[MeetingListener] = None
        self.meeting_active = False
        self.worker: Optional[AnswerWorker] = None
        self._answer_workers: set[AnswerWorker] = set()
        self._screen_worker: Optional[ScreenAnalysisWorker] = None
        self._drag_pos: Optional[QPoint] = None
        self._stealth_on = True
        self._chat_history: list[tuple[str, str]] = []
        self._resume_text: str = ""
        self._last_answer: str = ""

        self._build_ui()
        self._setup_hotkey_timer()
        self._setup_voice_drain_timer()

    # ── UI construction ──────────────────────────────────────────
    def _build_ui(self):
        self.setWindowTitle("Interview Assistant — Proxy Mode")
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |
            Qt.FramelessWindowHint  |
            Qt.Tool
        )
        self.setWindowOpacity(0.95)
        self.setMinimumSize(700, 600)
        self.resize(900, 950)
        self.setStyleSheet(DARK_STYLE)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)
        root.setContentsMargins(10, 8, 10, 8)

        # ── title bar ────────────────────────────────────────────
        title_bar = QHBoxLayout()
        title_lbl = QLabel("🎯 Interview Assistant")
        title_lbl.setObjectName("titleLabel")
        title_bar.addWidget(title_lbl)
        title_bar.addStretch()

        self.stealth_btn = QPushButton("👁 Hidden")
        self.stealth_btn.setFixedWidth(90)
        self.stealth_btn.setToolTip("Toggle screen-capture hiding")
        self.stealth_btn.clicked.connect(self._toggle_stealth)
        title_bar.addWidget(self.stealth_btn)

        self.opacity_btn = QPushButton("🔅")
        self.opacity_btn.setFixedWidth(34)
        self.opacity_btn.setToolTip("Reduce opacity")
        self.opacity_btn.clicked.connect(self._cycle_opacity)
        title_bar.addWidget(self.opacity_btn)

        settings_btn = QPushButton("⚙")
        settings_btn.setFixedWidth(34)
        settings_btn.setToolTip("Settings")
        settings_btn.clicked.connect(self._open_settings)
        title_bar.addWidget(settings_btn)

        min_btn = QPushButton("─")
        min_btn.setFixedWidth(28)
        min_btn.clicked.connect(self.showMinimized)
        title_bar.addWidget(min_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedWidth(28)
        close_btn.setStyleSheet("QPushButton{background:#c0392b;} QPushButton:hover{background:#e74c3c;}")
        close_btn.clicked.connect(self.close)
        title_bar.addWidget(close_btn)

        root.addLayout(title_bar)

        div = QFrame(); div.setObjectName("divider"); div.setFrameShape(QFrame.HLine)
        root.addWidget(div)

        # ── provider quick-select row ─────────────────────────────
        prov_row = QHBoxLayout()
        prov_lbl = QLabel("Provider:")
        prov_lbl.setStyleSheet("font-weight:bold; font-size:13px;")
        prov_row.addWidget(prov_lbl)
        self.provider_cb = QComboBox()
        self.provider_cb.addItems(["groq", "ollama", "mistral", "openai"])
        self.provider_cb.setCurrentText(self.ai.provider)
        self.provider_cb.setFixedWidth(110)
        self.provider_cb.setStyleSheet("font-size:13px; padding:4px 8px;")
        self.provider_cb.currentTextChanged.connect(self._quick_provider_change)
        prov_row.addWidget(self.provider_cb)

        self.web_chk = QCheckBox("Web Search")
        self.web_chk.setChecked(True)
        self.web_chk.setToolTip("Enrich answer with DuckDuckGo search")
        self.web_chk.setStyleSheet("font-size:12px;")
        prov_row.addWidget(self.web_chk)
        root.addLayout(prov_row)

        # ── model selection row (prominent) ───────────────────────
        model_row = QHBoxLayout()
        model_lbl = QLabel("🤖  Model:")
        model_lbl.setStyleSheet("font-weight:bold; font-size:14px; color:#e94560;")
        model_row.addWidget(model_lbl)
        self.model_cb = QComboBox()
        self.model_cb.setEditable(True)
        self.model_cb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.model_cb.setMinimumHeight(32)
        self.model_cb.setStyleSheet(
            "QComboBox { font-size:14px; font-weight:bold; padding:4px 10px; "
            "border:2px solid #e94560; border-radius:6px; color:#e0e0e0; "
            "background:#16213e; }"
            "QComboBox QAbstractItemView { font-size:13px; }"
        )
        self._refresh_model_combo(self.ai.provider)
        self.model_cb.currentTextChanged.connect(self._quick_model_change)
        self._attach_model_completer()
        model_row.addWidget(self.model_cb, 1)
        root.addLayout(model_row)

        # ── API key + model name (editable directly in UI) ────────
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("API Key:"))
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setPlaceholderText("Paste API key here (Groq / Mistral / OpenAI)…")
        self.api_key_input.setText(self.ai.api_key)
        self.api_key_input.editingFinished.connect(self._on_api_key_changed)
        key_row.addWidget(self.api_key_input, 1)

        show_key_btn = QPushButton("👁")
        show_key_btn.setFixedWidth(32)
        show_key_btn.setToolTip("Show / hide key")
        show_key_btn.setCheckable(True)
        show_key_btn.toggled.connect(
            lambda on: self.api_key_input.setEchoMode(
                QLineEdit.Normal if on else QLineEdit.Password
            )
        )
        key_row.addWidget(show_key_btn)
        root.addLayout(key_row)

        # ── active provider indicator ─────────────────────────────
        self.provider_indicator = QLabel()
        self.provider_indicator.setStyleSheet(
            "color:#86efac; background:#14532d; font-size:11px; font-weight:bold;"
            "padding:3px 10px; border-radius:4px;"
        )
        self._update_provider_indicator()
        root.addWidget(self.provider_indicator)

        chat_actions = QHBoxLayout()
        chat_actions.addWidget(QLabel("Conversation"))
        chat_actions.addStretch()

        self.copy_answer_btn = QPushButton("Copy latest answer")
        self.copy_answer_btn.setToolTip("Copy the latest answer exactly, including code")
        self.copy_answer_btn.setEnabled(False)
        self.copy_answer_btn.clicked.connect(self._copy_latest_answer)
        chat_actions.addWidget(self.copy_answer_btn)

        copy_chat_btn = QPushButton("Copy conversation")
        copy_chat_btn.setToolTip("Copy all visible conversation text")
        copy_chat_btn.clicked.connect(self._copy_conversation)
        chat_actions.addWidget(copy_chat_btn)
        root.addLayout(chat_actions)

        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setMinimumHeight(380)
        self.chat_display.setPlaceholderText("Answers will appear here…")
        self.chat_display.setContextMenuPolicy(Qt.CustomContextMenu)
        self.chat_display.customContextMenuRequested.connect(self._show_chat_context_menu)
        root.addWidget(self.chat_display, 3)

        # ── input row ────────────────────────────────────────────
        input_row = QHBoxLayout()
        self.question_input = QLineEdit()
        self.question_input.setPlaceholderText("Type your interview question here…")
        self.question_input.returnPressed.connect(self._send)
        input_row.addWidget(self.question_input, 1)

        self.voice_btn = QPushButton("🎙")
        self.voice_btn.setObjectName("voiceBtn")
        self.voice_btn.setFixedWidth(42)
        self.voice_btn.setToolTip("Click to start/stop voice input")
        self.voice_btn.clicked.connect(self._toggle_voice)
        input_row.addWidget(self.voice_btn)

        root.addLayout(input_row)

        # ── action buttons ───────────────────────────────────────
        btn_row = QHBoxLayout()

        send_btn = QPushButton("Send  ➤")
        send_btn.setObjectName("sendBtn")
        send_btn.clicked.connect(self._send)
        btn_row.addWidget(send_btn, 2)

        screen_btn = QPushButton("📷 Analyse Screen")
        screen_btn.setToolTip("Capture screen — AI reads the question automatically")
        screen_btn.clicked.connect(self._analyse_screen)
        btn_row.addWidget(screen_btn, 2)

        self.meeting_btn = QPushButton("🎧 Meeting Listen")
        self.meeting_btn.setToolTip("Listen to interviewer through speakers and auto-answer")
        self.meeting_btn.setObjectName("meetingBtn")
        self.meeting_btn.clicked.connect(self._toggle_meeting)
        btn_row.addWidget(self.meeting_btn, 2)

        clear_btn = QPushButton("🗑 Clear")
        clear_btn.clicked.connect(self._clear)
        btn_row.addWidget(clear_btn, 1)

        root.addLayout(btn_row)

        # ── resume upload row ─────────────────────────────────────
        resume_row = QHBoxLayout()

        self.resume_btn = QPushButton("📄 Upload Resume")
        self.resume_btn.setToolTip("Upload PDF/DOCX resume to personalise answers with your background")
        self.resume_btn.clicked.connect(self._upload_resume)
        resume_row.addWidget(self.resume_btn, 2)

        self.resume_label = QLabel("No resume loaded")
        self.resume_label.setStyleSheet("color:#888; font-size:11px;")
        self.resume_label.setWordWrap(True)
        resume_row.addWidget(self.resume_label, 3)

        clear_resume_btn = QPushButton("✕")
        clear_resume_btn.setFixedWidth(28)
        clear_resume_btn.setToolTip("Remove resume")
        clear_resume_btn.setStyleSheet("QPushButton{background:#7f1d1d;color:#fca5a5;border:none;border-radius:4px;}")
        clear_resume_btn.clicked.connect(self._clear_resume)
        resume_row.addWidget(clear_resume_btn)

        root.addLayout(resume_row)

        # ── status bar ───────────────────────────────────────────
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready — Ctrl+Shift+Space to toggle visibility")

    # ── stealth ──────────────────────────────────────────────────
    def _apply_stealth(self):
        hwnd = int(self.winId())
        ok = apply_stealth(hwnd)
        if ok:
            self.stealth_btn.setText("👁 Hidden")
            self.stealth_btn.setStyleSheet("QPushButton{background:#157347;}")
        else:
            self.stealth_btn.setText("👁 Visible")
            self.stealth_btn.setStyleSheet("")
        self._stealth_on = ok

    def _toggle_stealth(self):
        hwnd = int(self.winId())
        if self._stealth_on:
            remove_stealth(hwnd)
            self._stealth_on = False
            self.stealth_btn.setText("👁 Visible")
            self.stealth_btn.setStyleSheet("")
            self.status_bar.showMessage("Screen-capture hiding OFF")
        else:
            ok = apply_stealth(hwnd)
            self._stealth_on = ok
            self.stealth_btn.setText("👁 Hidden" if ok else "👁 Visible")
            self.stealth_btn.setStyleSheet("QPushButton{background:#157347;}" if ok else "")
            self.status_bar.showMessage("Screen-capture hiding ON" if ok else "Stealth unavailable on this OS/build")

    def _cycle_opacity(self):
        levels = [0.95, 0.75, 0.55, 0.35]
        cur = self.windowOpacity()
        try:
            idx = min(range(len(levels)), key=lambda i: abs(levels[i] - cur))
        except Exception:
            idx = 0
        nxt = levels[(idx + 1) % len(levels)]
        self.setWindowOpacity(nxt)

    # ── provider / model ─────────────────────────────────────────
    def _quick_provider_change(self, provider: str):
        self._refresh_model_combo(provider)
        key_map = {
            "groq":    os.getenv("GROQ_API_KEY", ""),
            "mistral": os.getenv("MISTRAL_API_KEY", ""),
            "openai":  os.getenv("OPENAI_API_KEY", ""),
            "ollama":  "",
        }
        env_key = key_map.get(provider, "")
        # always switch the key field to the new provider's key (clears old provider's key)
        self.api_key_input.setText(env_key)
        self.ai.update(provider, self.model_cb.currentText(), api_key=env_key)
        self._update_provider_indicator()

    def _update_provider_indicator(self):
        p = self.ai.provider or "unknown"
        m = self.ai.model or "—"
        self.provider_indicator.setText(f"Active: {p.upper()}  |  {m}")

    def _quick_model_change(self, model: str):
        self.ai.model = model

    def _on_api_key_changed(self):
        key = self.api_key_input.text().strip()
        self.ai.api_key = key
        self.ai._setup()
        self._update_provider_indicator()
        self.status_bar.showMessage(
            f"API key updated for {self.ai.provider}" if key else "API key cleared"
        )

    def _refresh_model_combo(self, provider: str):
        self.model_cb.blockSignals(True)
        self.model_cb.clear()
        models = AIClient.models_for(provider)
        if models:
            self.model_cb.addItems(models)
        self.model_cb.setCurrentText(self.ai.model if self.ai.model and self.ai.model in models else (models[0] if models else ""))
        self.model_cb.blockSignals(False)
        if hasattr(self, "model_cb"):
            self._attach_model_completer()

    def _attach_model_completer(self):
        from PyQt5.QtWidgets import QCompleter
        from PyQt5.QtCore import Qt
        models = [self.model_cb.itemText(i) for i in range(self.model_cb.count())]
        completer = QCompleter(models, self.model_cb)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.popup().setStyleSheet(
            "QListView { background:#16213e; color:#e0e0e0; font-size:13px; "
            "border:1px solid #e94560; selection-background-color:#0f3460; }"
        )
        self.model_cb.setCompleter(completer)

    def _open_settings(self):
        dlg = SettingsDialog(self.ai, self)
        if dlg.exec_() == QDialog.Accepted:
            vals = dlg.get_values()
            self.ai.update(vals["provider"], vals["model"], vals["api_key"])
            self.ai.ollama_url = vals["ollama_url"]
            self.provider_cb.setCurrentText(vals["provider"])
            self._refresh_model_combo(vals["provider"])
            self.model_cb.setCurrentText(vals["model"])
            if vals["api_key"]:
                self.api_key_input.setText(vals["api_key"])
            self.status_bar.showMessage(f"Provider: {vals['provider']} / {vals['model']}")

    # ── send / answer ────────────────────────────────────────────
    def _send(self):
        question = self.question_input.text().strip()
        if not question:
            return
        self._submit_question(question, "You")
        self.question_input.clear()

    def _submit_question(self, question: str, source: str):
        question = question.strip()
        if not question:
            return

        # apply any key typed in the field that hasn't been committed yet
        typed_key = self.api_key_input.text().strip()
        if typed_key and typed_key != self.ai.api_key:
            self.ai.api_key = typed_key
            self.ai._setup()

        self._chat_history.append(("user", question))
        self._append_chat(source, question, "#61dafb")
        self._run_worker(question)

    def _run_worker(self, question: str):
        self.status_bar.showMessage(f"Using: {self.ai.provider} / {self.ai.model}")

        # pass last 4 exchanges (8 messages) so the AI has context without exceeding token limits
        self.worker = AnswerWorker(
            question, self.ai, self.web_chk.isChecked(),
            resume=self._resume_text,
            history=self._chat_history[-8:],
        )
        worker = self.worker
        self._answer_workers.add(worker)
        self.worker.answer_ready.connect(self._on_answer)
        self.worker.status_update.connect(self._on_answer_status)
        self.worker.error.connect(self._on_answer_error)
        self.worker.finished.connect(lambda worker=worker: self._on_answer_worker_finished(worker))
        self.worker.start()
        self.status_bar.showMessage("Processing…")

    def _on_answer_status(self, message: str):
        self.status_bar.showMessage(message)

    def _on_answer_error(self, message: str):
        self._append_chat("Error", message, "#e94560")
        self.status_bar.showMessage(f"Answer error: {message[:100]}")

    def _on_answer_worker_finished(self, worker: AnswerWorker):
        self._answer_workers.discard(worker)
        if not self._answer_workers:
            self.status_bar.showMessage("Ready")

    def _on_answer(self, text: str):
        self._last_answer = text
        self.copy_answer_btn.setEnabled(True)
        self._append_chat("Assistant", text, "#98c379")
        self._chat_history.append(("assistant", text))

    def _show_chat_context_menu(self, position):
        menu = QMenu(self.chat_display)
        copy_selected = menu.addAction("Copy selected text")
        copy_selected.setEnabled(self.chat_display.textCursor().hasSelection())
        copy_selected.triggered.connect(self.chat_display.copy)
        copy_latest = menu.addAction("Copy latest answer")
        copy_latest.setEnabled(bool(self._last_answer))
        copy_latest.triggered.connect(self._copy_latest_answer)
        menu.addAction("Copy conversation", self._copy_conversation)
        menu.exec_(self.chat_display.mapToGlobal(position))

    def _copy_latest_answer(self):
        if not self._last_answer:
            self.status_bar.showMessage("There is no answer to copy")
            return
        QApplication.clipboard().setText(self._last_answer)
        self.status_bar.showMessage("Latest answer copied")

    def _copy_conversation(self):
        text = self.chat_display.toPlainText()
        if not text:
            self.status_bar.showMessage("There is no conversation to copy")
            return
        QApplication.clipboard().setText(text)
        self.status_bar.showMessage("Conversation copied")

    # ── voice ────────────────────────────────────────────────────
    def _toggle_voice(self):
        if self.voice_active:
            self._stop_voice()
        else:
            self._start_voice()

    def _start_voice(self):
        if self.voice_listener is None or not self.voice_listener.is_alive():
            self.voice_listener = VoiceListener(on_text=self._voice_text_queued)
        self.voice_listener.start_listening()
        self.voice_active = True
        self.voice_btn.setProperty("active", "true")
        self.voice_btn.setStyleSheet("QPushButton{background:#c0392b;font-size:16px;padding:7px 12px;}")
        self.status_bar.showMessage("🎙 Listening… speak your question")

    def _stop_voice(self):
        if self.voice_listener:
            self.voice_listener.stop_listening()
        self.voice_active = False
        self.voice_btn.setProperty("active", "false")
        self.voice_btn.setStyleSheet("")
        self.status_bar.showMessage("Voice stopped")

    def _voice_text_queued(self, text: str):
        # Called from voice thread — just stores; drain timer dispatches to GUI
        pass

    def _setup_voice_drain_timer(self):
        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(300)
        self._drain_timer.timeout.connect(self._drain_voice)
        self._drain_timer.start()

    def _drain_voice(self):
        if self.voice_listener:
            self.voice_listener.on_text = self._on_voice_text
            self.voice_listener.drain()

    def _on_voice_text(self, text: str):
        self.question_input.setText(text)
        self.status_bar.showMessage(f"Voice: {text}")
        self._stop_voice()
        self._send()

    # ── meeting audio listener ────────────────────────────────────
    def _toggle_meeting(self):
        if self.meeting_active:
            self._stop_meeting()
        else:
            self._start_meeting()

    def _start_meeting(self):
        self._meeting_signal = _MeetingTextSignal()
        self._meeting_signal.text_ready.connect(self._on_meeting_text)
        self._meeting_signal.error_ready.connect(self._on_meeting_listener_error)
        self.meeting_listener = MeetingListener(
            on_text=lambda t: self._meeting_signal.text_ready.emit(t),
            on_error=lambda message: self._meeting_signal.error_ready.emit(message),
        )
        self.meeting_listener.start_listening()
        self.meeting_active = True
        self.meeting_btn.setText("🔴 Stop Listening")
        self.meeting_btn.setProperty("active", "true")
        self.meeting_btn.setStyleSheet(
            "QPushButton{background:#c0392b;font-size:13px;}"
        )
        self.status_bar.showMessage("🎧 Listening live — transcribes every 5 s automatically")

    def _stop_meeting(self):
        if self.meeting_listener:
            self.meeting_listener.stop_listening()
        self.meeting_active = False
        self.meeting_btn.setText("🎧 Meeting Listen")
        self.meeting_btn.setProperty("active", "false")
        self.meeting_btn.setStyleSheet("")
        self.status_bar.showMessage("Meeting listener stopped")

    def _on_meeting_text(self, text: str):
        self._append_chat("Interviewer", text, "#f0a500")
        worker = MeetingFilterWorker(text, self.ai, self._resume_text, self.web_chk.isChecked())
        worker.is_question.connect(self._on_meeting_question)
        worker.not_question.connect(self._on_meeting_not_question)
        worker.error.connect(self._on_meeting_filter_error)
        worker.start()
        self._meeting_workers = getattr(self, "_meeting_workers", [])
        self._meeting_workers.append(worker)

    def _on_meeting_question(self, text: str):
        self.status_bar.showMessage(f"Question detected: {text[:60]}")
        self._run_worker(text)
        self._chat_history.append(("user", text))

    def _on_meeting_not_question(self, text: str):
        self.status_bar.showMessage(f"Heard (not a question): {text[:80]}")

    def _on_meeting_listener_error(self, message: str):
        if self.meeting_active:
            self._stop_meeting()
        self._append_chat("Meeting error", message, "#e94560")
        self.status_bar.showMessage(f"Meeting error: {message[:100]}")

    def _on_meeting_filter_error(self, message: str):
        self._append_chat("Meeting error", message, "#e94560")
        self.status_bar.showMessage(f"AI question filter error: {message[:100]}")

    # ── screen analysis ──────────────────────────────────────────
    def _analyse_screen(self):
        if self._screen_worker and self._screen_worker.isRunning():
            self.status_bar.showMessage("Screen analysis is already running")
            return

        self.ai.model = self.model_cb.currentText().strip()
        api_key = self.api_key_input.text().strip()
        if api_key != self.ai.api_key:
            self.ai.api_key = api_key
            self.ai._setup()

        self.status_bar.showMessage("Capturing screen…")
        self.hide()
        QApplication.processEvents()
        import time; time.sleep(0.5)   # let window fully hide before screenshot

        img = capture_screen()
        self.show()
        self.raise_()

        if img is None:
            self._on_screen_analysis_error(
                "Screenshot capture failed. Check the application log for details."
            )
            return

        status = (
            "Reading screen locally…"
            if self.ai.provider != "ollama" and not api_key
            else "AI is reading the screen…"
        )
        self.status_bar.showMessage(status)
        self._screen_worker = ScreenAnalysisWorker(
            img,
            self.ai.provider,
            self.ai.api_key,
            self.ai.model,
            self.ai.ollama_url,
        )
        self._screen_worker.question_extracted.connect(self._on_screen_question)
        self._screen_worker.offline_text_extracted.connect(self._on_offline_screen_text)
        self._screen_worker.error.connect(self._on_screen_analysis_error)
        self._screen_worker.start()

    def _on_offline_screen_text(self, text: str):
        extracted = text.strip()
        if not extracted:
            self._on_screen_analysis_error("No readable text was found on the screen.")
            return

        self.question_input.setText(extracted)
        self._append_chat("Screen", extracted, "#a78bfa")
        self.status_bar.showMessage(
            "Screen text extracted offline. Add an API key and press Send for an AI answer."
        )

    def _on_screen_analysis_error(self, message: str):
        logger.error("Screen analysis failed: %s", message)
        self._append_chat("Screen analysis error", message, "#e94560")
        self.status_bar.showMessage(f"Screen analysis failed: {message[:100]}")

    def _on_screen_question(self, question: str):
        q = question.strip()
        if not q or q.upper() == "NONE" or q.upper().startswith("NONE"):
            self.status_bar.showMessage("No question found on screen")
            return
        logger.info("Screen question extracted (%d characters)", len(q))
        self.question_input.setText(q)
        self._submit_question(q, "Screen")

    # ── chat display helpers ─────────────────────────────────────
    def _append_chat(self, role: str, text: str, color: str = "#e0e0e0"):
        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.chat_display.setTextCursor(cursor)

        if role == "Assistant":
            in_code = False
            code_lines = []
            for line in text.splitlines():
                stripped = line.strip()

                if stripped.startswith("```"):
                    if not in_code:
                        in_code = True
                        code_lines = []
                    else:
                        in_code = False
                        code_html = (
                            '<pre style="background:#0d1117;color:#a8ff78;'
                            'font-family:Consolas,monospace;font-size:12px;'
                            'padding:10px 14px;border-left:3px solid #4a7eff;'
                            'border-radius:4px;margin:6px 0 10px 0;white-space:pre-wrap;">'
                            + html.escape("\n".join(code_lines))
                            + "</pre>"
                        )
                        self.chat_display.append(code_html)
                    continue

                if in_code:
                    code_lines.append(line)
                    continue

                if not stripped:
                    self.chat_display.append('<p style="margin:2px;"> </p>')
                elif stripped.startswith("•"):
                    point_text = html.escape(stripped[1:].strip())
                    self.chat_display.append(
                        '<p style="color:#e2e8f0;font-size:13px;'
                        'margin:3px 0 3px 8px;line-height:1.6;">'
                        '<span style="color:#4a7eff;">•</span> '
                        f'{point_text}</p>'
                    )
                elif stripped.startswith("→"):
                    intro_text = html.escape(stripped[1:].strip())
                    self.chat_display.append(
                        f'<p style="color:#f8fafc;font-size:13px;'
                        f'margin:6px 0 4px 0;line-height:1.6;">{intro_text}</p>'
                    )
                else:
                    self.chat_display.append(
                        f'<p style="color:#e2e8f0;font-size:13px;'
                        f'margin:3px 0 4px 0;line-height:1.6;">{html.escape(stripped)}</p>'
                    )

            self.chat_display.append(
                '<hr style="border:none;border-top:1px solid #1e293b;margin:10px 0 12px 0;">'
            )

        elif role in ("You", "Interviewer", "Screen"):
            label = {"You": "YOU", "Interviewer": "INTERVIEWER", "Screen": "SCREEN READ"}.get(role, role.upper())
            lcolor = {"You": "#38bdf8", "Interviewer": "#f0a500", "Screen": "#a78bfa"}.get(role, "#888")
            self.chat_display.append(
                f'<p style="color:{lcolor};font-size:10px;margin:8px 0 2px 0;'
                f'letter-spacing:1px;font-weight:bold;">{label}</p>'
                f'<p style="color:#64748b;font-size:12px;margin:0 0 4px 0;">{html.escape(text)}</p>'
            )
        else:
            self.chat_display.append(
                f'<p style="color:{color};font-size:11px;margin:4px 0;'
                f'font-style:italic;">{html.escape(text)}</p>'
            )

        self.chat_display.ensureCursorVisible()

    # ── resume ───────────────────────────────────────────────────
    def _upload_resume(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Upload Resume", "",
            "Resume Files (*.pdf *.docx *.doc *.txt);;All Files (*)"
        )
        if not path:
            return
        self.status_bar.showMessage("Parsing resume…")
        QApplication.processEvents()
        try:
            raw = parse_resume(path)
            self._resume_text = summarise_for_prompt(raw)
            fname = os.path.basename(path)
            words = len(self._resume_text.split())
            self.resume_label.setText(f"✓ {fname}  ({words} words loaded)")
            self.resume_label.setStyleSheet("color:#86efac; font-size:11px;")
            self.resume_btn.setStyleSheet("QPushButton{background:#14532d;color:#86efac;}")
            self.status_bar.showMessage(f"Resume loaded: {fname} — answers will use your background")
            self._append_chat("System", f"Resume loaded: {fname}. I will now personalise answers using your background.", "#888")
        except Exception as exc:
            self.status_bar.showMessage(f"Resume error: {exc}")
            self.resume_label.setText(f"Error: {exc}")

    def _clear_resume(self):
        self._resume_text = ""
        self.resume_label.setText("No resume loaded")
        self.resume_label.setStyleSheet("color:#888; font-size:11px;")
        self.resume_btn.setStyleSheet("")
        self.status_bar.showMessage("Resume removed")

    def _clear(self):
        self.chat_display.clear()
        self._chat_history.clear()
        self._last_answer = ""
        self.copy_answer_btn.setEnabled(False)
        self.question_input.clear()

    # ── global hotkey (Ctrl+Shift+Space) ─────────────────────────
    def _setup_hotkey_timer(self):
        # Poll via pynput in a background thread
        try:
            from pynput import keyboard as kb

            def on_press(key):
                pass

            combo = {kb.Key.ctrl_l, kb.Key.shift, kb.Key.space}
            current = set()

            def _on_press(key):
                current.add(key)
                if all(k in current for k in combo):
                    self._hotkey_triggered()

            def _on_release(key):
                current.discard(key)

            listener = kb.Listener(on_press=_on_press, on_release=_on_release)
            listener.daemon = True
            listener.start()
        except ImportError:
            logger.warning("pynput not installed — global hotkey disabled")

    def _hotkey_triggered(self):
        self._visibility_toggle_requested.emit()

    def _toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    # ── frameless window drag ────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.status_bar.showMessage("Assistant hidden — Ctrl+Shift+Space to show")


# ─────────────────────────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Interview Assistant")
    app.setQuitOnLastWindowClosed(False)
    app.aboutToQuit.connect(lambda: logger.info("Application is shutting down"))
    win = MainWindow()
    # Position bottom-right by default
    screen = app.primaryScreen().availableGeometry()
    win.move(screen.right() - win.width() - 20, screen.bottom() - win.height() - 60)
    win.show()
    win._apply_stealth()   # must be after show() so HWND is fully created
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
