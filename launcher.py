# launcher.py
import os
import sys
import json
import subprocess
import threading
import time
import requests
from datetime import datetime
import warnings

warnings.filterwarnings(
    "ignore",
    message=r".*incompatible copy of pydevd.*",
    category=UserWarning
)

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
    QFormLayout, QLineEdit, QPushButton, QTextBrowser, QGraphicsOpacityEffect
)
from PyQt6.QtGui import QIcon, QTextCursor, QPixmap
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QPropertyAnimation

from vk2tg import CONFIG
import logging

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    encoding="utf-8",
    errors = "ignore"
)

# ---------------- Signals ----------------
class LogEmitter(QObject):
    new_line = pyqtSignal(str, bool)

# ---------------- Title Bar ----------------
class TitleBar(QWidget):
    def __init__(self, parent=None, icon_path="icon.ico"):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setStyleSheet("background-color:#2e2e2e;")
        layout = QHBoxLayout()
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(8)

        self.icon_label = QLabel()
        if os.path.exists(icon_path):
            pix = QPixmap(icon_path).scaled(20, 20, Qt.AspectRatioMode.KeepAspectRatio)
            self.icon_label.setPixmap(pix)
        layout.addWidget(self.icon_label)

        self.title = QLabel("VK2TG")
        self.title.setStyleSheet("color:white; font-weight:600;")
        layout.addWidget(self.title)
        layout.addStretch()

        btn_style = """
            QPushButton{
                background-color:#2e2e2e;color:white;border:none;padding:2px 8px;border-radius:6px;
            }
            QPushButton:hover{ background-color:#44475a; }
        """
        self.min_btn = QPushButton("🗕")
        self.max_btn = QPushButton("🗖")
        self.close_btn = QPushButton("✕")
        for b in (self.min_btn, self.max_btn, self.close_btn):
            b.setFixedSize(28,22)
            b.setStyleSheet(btn_style)
            layout.addWidget(b)

        self.setLayout(layout)

        if parent:
            self.close_btn.clicked.connect(parent.close)
            self.min_btn.clicked.connect(parent.showMinimized)
            self.max_btn.clicked.connect(lambda: parent.showMaximized() if not parent.isMaximized() else parent.showNormal())

# ---------------- Bot GUI ----------------
class BotGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.bot_running = False
        self.vk_process = None
        self.stdout_thread = None
        self.stderr_thread = None
        self.log_emitter = LogEmitter()
        self.log_emitter.new_line.connect(self.handle_new_line)

        self.ui_colors = [(30,30,50),(50,30,60),(30,50,50),(60,30,30),(30,30,30)]
        self.ui_index = 0
        self.ui_subphase = 0.0
        self._drag_offset = None

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        if os.path.exists("icon.ico"):
            self.setWindowIcon(QIcon("icon.ico"))
        self.setWindowTitle("RepostGUI")
        self.resize(800, 500)

        # ---------------- UI ----------------
        self.init_ui()
        self.tabs.currentChanged.connect(self.animate_tab_change)
        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self.ui_tick)
        self.ui_timer.start(40)

    # ---------------- UI Init ----------------
    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0,0,0,0)
        main_layout.setSpacing(0)

        self.title_bar = TitleBar(self, icon_path="icon.ico")
        main_layout.addWidget(self.title_bar)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: none; background: transparent; }
            QTabBar::tab { background: transparent; padding: 6px 12px; border-radius:6px; }
            QTabBar::tab:selected { background: rgba(255,255,255,0.1); }
        """)
        main_layout.addWidget(self.tabs)
        self.setLayout(main_layout)

        # Tabs
        self.main_tab = QWidget()
        self.settings_tab = QWidget()
        self.tabs.addTab(self.main_tab, "Главная")
        self.tabs.addTab(self.settings_tab, "Настройки")

        self.init_main_tab()
        self.init_settings_tab()

    # ---------------- Main Tab ----------------
    def init_main_tab(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(12,12,12,12)
        layout.setSpacing(10)

        status_row = QHBoxLayout()
        status_row.setSpacing(12)
        status_row.addStretch()

        self.start_btn = QPushButton("Старт")
        self.stop_btn = QPushButton("Стоп")
        for b in (self.start_btn, self.stop_btn):
            b.setFixedHeight(30)
            b.setStyleSheet("""
                QPushButton{ background-color:#2e2e2e;color:white;border-radius:8px;padding:6px 12px; }
                QPushButton:hover{ background-color:#44475a; }
            """)
        self.start_btn.clicked.connect(self.start_bot)
        self.stop_btn.clicked.connect(self.stop_bot)
        status_row.addWidget(self.start_btn)
        status_row.addWidget(self.stop_btn)

        layout.addLayout(status_row)

        self.log_box = QTextBrowser()
        self.log_box.setOpenExternalLinks(True)
        self.log_box.setStyleSheet("background-color:transparent; color:#ddd; padding:8px; border:none;")
        layout.addWidget(self.log_box,1)

        hint = QLabel("Репостинг: ВКонтакте → Telegram.")
        hint.setStyleSheet("color:#9aa9b2; font-size:12px;")
        layout.addWidget(hint)

        self.main_tab.setLayout(layout)

    # ---------------- Settings Tab ----------------
    def init_settings_tab(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(12,12,12,12)

        form = QFormLayout()
        vk = CONFIG.get('vk', {})
        tg = CONFIG.get('telegram', {})

        self.vk_token_input = QLineEdit(vk.get('token',''))
        self.owner_id_input = QLineEdit(str(vk.get('owner_id','')))
        self.api_version_input = QLineEdit(vk.get('api_version','5.131'))
        self.tg_token_input = QLineEdit(tg.get('bot_token',''))
        self.tg_chat_input = QLineEdit(tg.get('chat_id',''))
        self.tg_botname_input = QLineEdit(tg.get('bot_username',''))

        form.addRow("VK token (user):", self.vk_token_input)
        form.addRow("Owner ID:", self.owner_id_input)
        form.addRow("VK API version:", self.api_version_input)
        form.addRow("Telegram bot token:", self.tg_token_input)
        form.addRow("Telegram chat id:", self.tg_chat_input)
        form.addRow("Telegram bot username:", self.tg_botname_input)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("💾 Сохранить")
        save_btn.setFixedHeight(34)
        save_btn.clicked.connect(self.save_settings)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        self.settings_tab.setLayout(layout)

    # ---------------- Save Settings ----------------
    def save_settings(self):
        try:
            CONFIG['vk']['token'] = self.vk_token_input.text().strip()
            CONFIG['vk']['owner_id'] = int(self.owner_id_input.text().strip())
            CONFIG['vk']['api_version'] = self.api_version_input.text().strip()
            CONFIG['telegram']['bot_token'] = self.tg_token_input.text().strip()
            CONFIG['telegram']['chat_id'] = self.tg_chat_input.text().strip()
            CONFIG['telegram']['bot_username'] = self.tg_botname_input.text().strip()
            with open("config.json", "w", encoding="utf-8", errors="ignore") as f:
                json.dump(CONFIG, f, ensure_ascii=False, indent=2)
            self.append_log("Настройки сохранены в config.json", mode="info")
        except Exception as e:
            self.append_log(f"Ошибка сохранения настроек: {e}", mode="error")

    # ---------------- Logs ----------------
    def append_log(self, text, mode="normal"):
        color = {"normal": "white","info":"cyan","error":"red"}.get(mode,"white")
        html = f'<div style="color:{color}; font-family: monospace; font-size:12px;">'
        html += f'[{datetime.now().strftime("%H:%M:%S")}] {text}</div>'
        self.log_box.insertHtml(html + "<br>")
        self.log_box.moveCursor(QTextCursor.MoveOperation.End)

    # ---------------- Handle new line ----------------
    def handle_new_line(self, text, is_err):
        lowered = text.lower()
        if "ошибка" in lowered or is_err:
            self.append_log(text, mode="error")
        else:
            self.append_log(text, mode="normal")

    # ---------------- Bot process ----------------
    def start_bot(self):
        if self.bot_running:
            self.append_log("Бот уже запущен", mode="info")
            return
        python_exe = sys.executable
        script_path = os.path.join(os.getcwd(), "vk2tg.py")
        if not os.path.exists(script_path):
            self.append_log(f"vk2tg.py не найден в {script_path}", mode="error")
            return
        try:
            self.vk_process = subprocess.Popen(
                [python_exe, script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
                encoding="utf-8",
                errors = "ignore"
            )
        except Exception as e:
            self.append_log(f"Не удалось запустить процесс: {e}", mode="error")
            return
        self._stop_threads = False
        self.stdout_thread = threading.Thread(target=self._read_stream,args=(self.vk_process.stdout,False),daemon=True)
        self.stderr_thread = threading.Thread(target=self._read_stream,args=(self.vk_process.stderr,True),daemon=True)
        self.stdout_thread.start()
        self.stderr_thread.start()
        self.bot_running = True
        self.append_log("Скрипт запущен.", mode="info")

    def stop_bot(self):
        if not self.bot_running:
            self.append_log("Скрипт уже остановлен", mode="info")
            return
        try:
            if self.vk_process:
                self.vk_process.terminate()
                try:
                    self.vk_process.wait(timeout=5)
                except Exception:
                    try:
                        self.vk_process.kill()
                    except Exception:
                        pass
            self._stop_threads = True
            if self.stdout_thread and self.stdout_thread.is_alive():
                self.stdout_thread.join(timeout=1)
            if self.stderr_thread and self.stderr_thread.is_alive():
                self.stderr_thread.join(timeout=1)
        except Exception as e:
            self.append_log(f"Ошибка при остановке процесса: {e}", mode="error")
        self.vk_process = None
        self.bot_running = False
        self.append_log("Скрипт отключен", mode="info")

    def _read_stream(self, stream, is_err):
        try:
            for line in stream:
                if line is None: break
                line = line.rstrip("\n")
                self.log_emitter.new_line.emit(line, is_err)
                if getattr(self,"_stop_threads",False):
                    break
        except Exception as e:
            self.log_emitter.new_line.emit(f"Ошибка чтения потока: {e}", True)

    # ---------------- UI Tick ----------------
    def ui_tick(self):
        if self.bot_running and self.vk_process and self.vk_process.poll() is not None:
            self.append_log(f"vk2tg.py процесс завершился с кодом {self.vk_process.returncode}", mode="error")
            self.bot_running = False

    # ---------------- Tab Animation ----------------
    def animate_tab_change(self, index):
        widget = self.tabs.widget(index)
        if widget is None: return
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect,b"opacity",self)
        anim.setDuration(250)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    # ---------------- Drag Window ----------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint()-self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint()-self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None

    # ---------------- Close Event ----------------
    def closeEvent(self, event):
        try:
            if self.bot_running: self.stop_bot()
        except: pass
        event.accept()

# ---------------- Main ----------------
def main():
    app = QApplication(sys.argv)
    try:
        import qdarktheme
        app.setStyleSheet(qdarktheme.load_stylesheet("dark"))
    except: pass
    gui = BotGUI()
    gui.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
