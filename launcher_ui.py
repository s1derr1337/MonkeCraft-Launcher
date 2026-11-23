import json
from pathlib import Path
from PySide6.QtWidgets import (QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QFrame,
    QLineEdit, QStackedWidget, QSpinBox, QFileDialog, QMessageBox, QFormLayout, QProgressBar,
    QTextBrowser, QDialog, QApplication)
from PySide6.QtCore import Qt, QUrl, QSize
from PySide6.QtGui import QDesktopServices, QPixmap, QIcon

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
DESCRIPTION_FILE = BASE_DIR / "description.txt"
MODS_FILE = BASE_DIR / "mods.json"
VIDEO_FILE = ASSETS_DIR / "background.mp4"
AVATAR_FILE = ASSETS_DIR / "avatar.png"
ICON_DIR = ASSETS_DIR / "icons"
DISCORD_URL = "https://discord.gg/UZZjMhBQxy"

STYLE = '''
* { font-family: "Segoe UI"; }
QWidget { color: #f4f0fa; background: transparent; }
QFrame#topbar { background: rgba(22,18,29,220); border: 1px solid rgba(153,115,220,40); border-radius: 18px; }
QFrame#panel { background: rgba(22,18,29,185); border: 1px solid rgba(180,145,230,55); border-radius: 20px; }
QLabel#muted { color: #b6a9c7; }
QLabel#online { background: rgba(24,20,32,210); border: 1px solid rgba(180,145,230,50); border-radius: 12px; padding: 8px 13px; color: #e8defa; }
QLabel#title { font-size: 42px; font-weight: 900; letter-spacing: 3px; color: white; }
QLineEdit,QSpinBox { background: rgba(35,29,45,220); border: 1px solid rgba(180,145,230,90); border-radius: 10px; padding: 10px; }
QPushButton#icon { background: rgba(45,37,58,190); border: 1px solid rgba(180,145,230,50); border-radius: 12px; padding: 8px; font-size: 18px; }
QPushButton#icon:hover,QPushButton#secondary:hover { background: rgba(90,67,125,220); }
QPushButton#play { background: #8054d9; color: white; border: none; border-radius: 13px; font-size: 16px; font-weight: bold; padding: 15px 26px; }
QPushButton#play:hover { background: #9569ed; }
QPushButton#secondary { background: rgba(47,39,60,220); border: 1px solid rgba(180,145,230,70); border-radius: 13px; padding: 12px 20px; }
QPushButton#mods { background: rgba(35,29,45,220); border: 1px solid rgba(180,145,230,50); border-radius: 12px; padding: 10px 14px; }
QProgressBar { background: rgba(30,25,38,220); border: 1px solid rgba(180,145,230,45); border-radius: 5px; height: 9px; text-align: center; }
QProgressBar::chunk { background: #8054d9; border-radius: 5px; }
QDialog { background: #211b2b; }
'''

class ModsDialog(QDialog):
    def __init__(self, parent=None, remote_data=None):
        super().__init__(parent)
        self.setWindowTitle("Список модов")
        self.setWindowIcon(QIcon(str(BASE_DIR / "icon.ico")))
        self.resize(460, 420)
        layout=QVBoxLayout(self); title=QLabel("МОДЫ СБОРКИ"); title.setStyleSheet("font-size:22px;font-weight:bold;")
        layout.addWidget(title)
        try:
            data=remote_data if isinstance(remote_data,dict) else json.loads(MODS_FILE.read_text(encoding="utf-8")); mods=data.get("mods",[])
            for item in mods:
                if isinstance(item,dict):
                    text="•  "+str(item.get("name", "Без названия"))
                    if item.get("description"):text += "\n"+str(item["description"])
                else:text="•  "+str(item)
                label=QLabel(text); label.setWordWrap(True); label.setStyleSheet("padding:8px 4px;"); layout.addWidget(label)
        except Exception as e:
            layout.addWidget(QLabel(f"Не удалось прочитать список модов: {e}"))
        layout.addStretch(); close=QPushButton("Закрыть"); close.setObjectName("secondary"); close.clicked.connect(self.accept); layout.addWidget(close)

class LauncherUI(QWidget):
    def __init__(self, launcher):
        super().__init__(); self.launcher=launcher
        self.setWindowTitle("MonkeCraft"); self.resize(1120,720); self.setMinimumSize(940,620); self.setStyleSheet(STYLE)
        self.setWindowIcon(QIcon(str(BASE_DIR / "icon.ico")))
        self.build()

    def build(self):
        outer=QHBoxLayout(self); outer.setContentsMargins(14,14,14,14); outer.setSpacing(14)
        self.background=QLabel(self); self.background.setObjectName("background"); self.background.setGeometry(self.rect()); self.background.lower()
        self.video_widget=None
        if VIDEO_FILE.exists():
            try:
                from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QVideoSink
                # Render decoded frames into a QLabel to avoid QVideoWidget's
                # native-window stacking behavior on some Windows systems.
                self.video_widget=QLabel(self); self.video_widget.setGeometry(self.rect()); self.video_widget.setScaledContents(True); self.video_widget.lower()
                self.video_sink=QVideoSink(self)
                self.video_sink.videoFrameChanged.connect(self._display_video_frame)
                self.player=QMediaPlayer(self); self.audio=QAudioOutput(self); self.audio.setVolume(0); self.player.setAudioOutput(self.audio); self.player.setVideoSink(self.video_sink)
                self.player.setSource(QUrl.fromLocalFile(str(VIDEO_FILE)))
                self.player.setLoops(QMediaPlayer.Loops.Infinite)
                self.player.play()
            except Exception: self.video_widget=None
        self.tint=QFrame(self); self.tint.setStyleSheet("background:rgba(12,9,18,125);"); self.tint.lower()
        sidebar=QFrame(); sidebar.setObjectName("topbar"); sidebar.setFixedWidth(72); sl=QVBoxLayout(sidebar); sl.setContentsMargins(8,12,8,12); sl.setSpacing(12)
        avatar=QLabel(); avatar.setAlignment(Qt.AlignCenter); avatar.setFixedSize(52,52)
        if AVATAR_FILE.exists():
            pix=QPixmap(str(AVATAR_FILE)).scaled(52,52,Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation); avatar.setPixmap(pix); avatar.setStyleSheet("border-radius:26px;")
        else: avatar.setText("M"); avatar.setStyleSheet("background:#8054d9;border-radius:26px;font-size:22px;font-weight:900;color:white;")
        sl.addWidget(avatar,0,Qt.AlignHCenter); sl.addStretch(1)
        center_buttons=QVBoxLayout(); center_buttons.setSpacing(12); center_buttons.setAlignment(Qt.AlignHCenter)
        self.home_btn=self.icon_button("⌂","Главная","home.png"); self.home_btn.clicked.connect(self.show_home); center_buttons.addWidget(self.home_btn,0,Qt.AlignHCenter)
        self.settings_btn=self.icon_button("⚙","Настройки","settings.png"); self.settings_btn.clicked.connect(self.show_settings); center_buttons.addWidget(self.settings_btn,0,Qt.AlignHCenter)
        sl.addLayout(center_buttons); sl.addStretch(1)
        self.exit_btn=self.icon_button("×","Выход","close.png"); self.exit_btn.clicked.connect(QApplication.quit); sl.addWidget(self.exit_btn,0,Qt.AlignHCenter)
        outer.addWidget(sidebar)
        right=QVBoxLayout(); right.setSpacing(12); outer.addLayout(right,1)
        self.stack=QStackedWidget(); self.home=self.home_page(); self.settings=self.settings_page(); self.stack.addWidget(self.home); self.stack.addWidget(self.settings); right.addWidget(self.stack,1)
        self.resize_layers()
    def _display_video_frame(self, frame):
        try:
            image = frame.toImage()
            if not image.isNull():
                self.video_widget.setPixmap(QPixmap.fromImage(image))
        except Exception:
            pass

    def resizeEvent(self,event):
        super().resizeEvent(event); self.resize_layers()
    def resize_layers(self):
        for layer in (getattr(self,"background",None),getattr(self,"video_widget",None),getattr(self,"tint",None)):
            if layer: layer.setGeometry(self.rect())

    def set_button_icon(self, button, icon_name):
        icon_path = ICON_DIR / icon_name
        if icon_path.exists():
            button.setIcon(QIcon(str(icon_path)))
            button.setIconSize(QSize(24, 24))
            button.setText("")

    def icon_button(self, glyph, tooltip, icon_name=None):
        b=QPushButton(glyph); b.setObjectName("icon"); b.setFixedSize(44,44); b.setToolTip(tooltip)
        if icon_name:
            self.set_button_icon(b, icon_name)
        return b

    def home_page(self):
        page=QWidget(); layout=QVBoxLayout(page); layout.setContentsMargins(28,24,28,24); layout.setSpacing(14)
        # online=QLabel("◉   -- / -- игроков"); online.setObjectName("online"); online.setMaximumWidth(240); layout.addWidget(online,0,Qt.AlignLeft)
        layout.addStretch(1)
        content=QFrame(); content.setObjectName("panel"); content.setMinimumWidth(680); content.setMaximumWidth(760); c=QVBoxLayout(content); c.setContentsMargins(38,36,38,36); c.setSpacing(18)
        remote=self.launcher.remote_description if isinstance(getattr(self.launcher,"remote_description",None),dict) else {}
        title=QLabel(str(remote.get("title","MonkeCraft"))); title.setObjectName("title"); c.addWidget(title)
        description=str(remote.get("description","Небольшой закрытый Minecraft-сервер."))
        self.description=QLabel(description); self.description.setWordWrap(True); self.description.setObjectName("muted"); self.description.setMinimumHeight(65); self.description.setMaximumWidth(650); self.description.setStyleSheet("font-size:16px; line-height:1.4;"); c.addWidget(self.description)
        news=str(remote.get("news", ""))
        if news:
            self.news_label=QLabel(news); self.news_label.setWordWrap(True); self.news_label.setObjectName("muted"); c.addWidget(self.news_label)
        self.nick=QLineEdit(self.launcher.nickname); self.nick.setMaxLength(16); self.nick.setPlaceholderText("Ваш игровой никнейм"); c.addWidget(self.nick)
        row=QHBoxLayout(); self.play_button=QPushButton(); self.play_button.setObjectName("play"); self.play_button.clicked.connect(self.launcher.play_clicked); row.addWidget(self.play_button)
        config=QPushButton("⚙   НАСТРОИТЬ"); config.setObjectName("secondary"); config.clicked.connect(self.show_settings); row.addWidget(config); c.addLayout(row)
        self.status=QLabel("Готов к запуску"); self.status.setObjectName("muted"); self.status.setWordWrap(True); c.addWidget(self.status)
        self.progress=QProgressBar(); self.progress.setRange(0,100); self.progress.hide(); c.addWidget(self.progress)
        bottom=QHBoxLayout(); mods=QPushButton("▤   СПИСОК МОДОВ"); mods.setObjectName("mods"); self.set_button_icon(mods,"mods.png"); mods.clicked.connect(lambda:ModsDialog(self,self.launcher.remote_mods).exec()); bottom.addWidget(mods); bottom.addStretch()
        dev=QVBoxLayout(); dev.setSpacing(4); dlabel=QLabel("РАЗРАБОТЧИК"); dlabel.setObjectName("muted"); dlabel.setAlignment(Qt.AlignRight); dlabel.setStyleSheet("font-size:10px;letter-spacing:2px;"); dev.addWidget(dlabel)
        social=QHBoxLayout(); social.setSpacing(8); ds=self.icon_button("◉","Discord разработчика","discord.png"); ds.clicked.connect(lambda:QDesktopServices.openUrl(QUrl(DISCORD_URL))); social.addWidget(ds)
        tg=self.icon_button("➤","Telegram","telegram.png"); tg.clicked.connect(lambda:QDesktopServices.openUrl(QUrl("https://t.me/s1derr1337"))); social.addWidget(tg); dev.addLayout(social); bottom.addLayout(dev); c.addLayout(bottom)
        layout.addWidget(content,0,Qt.AlignLeft); layout.addStretch(2); return page

    def update_install_button(self, installed):
        self.play_button.setText("▶   ИГРАТЬ" if installed else "⬇   УСТАНОВИТЬ")
    def show_discord_id(self):
        QMessageBox.information(self,"Discord разработчика","Discord: @s1derr\n\nНажмите OK, чтобы закрыть.")

    def settings_page(self):
        page=QWidget(); layout=QVBoxLayout(page); layout.setContentsMargins(28,26,28,26); layout.setSpacing(14)
        heading=QLabel("НАСТРОЙКИ"); heading.setStyleSheet("font-size:30px;font-weight:bold;"); layout.addWidget(heading)
        form=QFormLayout(); form.setSpacing(12)
        self.java=QLineEdit(self.launcher.settings.get("java_path","")); self.java.setPlaceholderText("Автоматическое определение Java")
        java_row=QHBoxLayout(); java_row.addWidget(self.java); jb=QPushButton("Обзор"); jb.setObjectName("secondary"); jb.clicked.connect(self.pick_java); java_row.addWidget(jb); form.addRow("Java",java_row)
        self.ram=QSpinBox(); self.ram.setRange(1,32); self.ram.setValue(int(self.launcher.settings.get("ram",4))); self.ram.setSuffix(" ГБ"); form.addRow("Оперативная память",self.ram)
        self.instance=QLineEdit(self.launcher.settings.get("instance_path",str(self.launcher.game_dir))); fr=QHBoxLayout(); fr.addWidget(self.instance); fb=QPushButton("Обзор"); fb.setObjectName("secondary"); fb.clicked.connect(self.open_game_folder); fr.addWidget(fb); form.addRow("Папка игры",fr)
        self.jvm=QLineEdit(self.launcher.settings.get("jvm_args","")); form.addRow("JVM аргументы",self.jvm)
        self.gameargs=QLineEdit(self.launcher.settings.get("game_args","")); form.addRow("Игровые аргументы",self.gameargs)
        self.manifest=QLineEdit(self.launcher.settings.get("manifest_url",self.launcher.manifest_url)); form.addRow("URL манифеста",self.manifest)
        layout.addLayout(form); save=QPushButton("Сохранить настройки"); save.setObjectName("play"); save.clicked.connect(self.save_settings); layout.addWidget(save)
        back=QPushButton("←  Назад"); back.setObjectName("secondary"); back.clicked.connect(self.show_home); layout.addWidget(back); layout.addStretch(); return page
    def pick_java(self):
        f,_=QFileDialog.getOpenFileName(self,"Выбрать Java","","Java (*.exe)");
        if f:self.java.setText(f)
    def open_game_folder(self):
        folder = Path(self.instance.text().strip()).expanduser()
        if not folder.exists():
            QMessageBox.warning(self, "Папка игры", "Указанная папка не существует.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))
    def save_settings(self):
        self.launcher.settings.update({"java_path":self.java.text().strip(),"ram":self.ram.value(),"instance_path":self.instance.text().strip(),"jvm_args":self.jvm.text().strip(),"game_args":self.gameargs.text().strip(),"manifest_url":self.manifest.text().strip()})
        self.launcher.save_settings(); QMessageBox.information(self,"Настройки","Настройки сохранены.")
    def show_home(self): self.stack.setCurrentWidget(self.home)
    def show_settings(self): self.stack.setCurrentWidget(self.settings)
