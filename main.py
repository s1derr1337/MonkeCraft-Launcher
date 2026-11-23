import sys, json, subprocess, uuid, urllib.request, ssl, os, logging, traceback, threading, time, gzip, struct, io
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QThread, Signal
from mrpack_installer import MRPackWorker
import minecraft_launcher_lib
try:
    import certifi
    SSL_CERT_FILE = certifi.where()
    os.environ["SSL_CERT_FILE"] = SSL_CERT_FILE
    os.environ["REQUESTS_CA_BUNDLE"] = SSL_CERT_FILE
    ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=SSL_CERT_FILE)
except ImportError:
    pass
from launcher_ui import LauncherUI

MC_VERSION = "26.3"
LOADER = "fabric"
APP_DIR = Path.home() / "AppData" / "Roaming" / "MonkeCraft"

def setup_logging():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    log_path = APP_DIR / "launcher.log"
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(levelname)s | %(threadName)s | %(name)s | %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler(sys.__stdout__)],
        force=True,
    )
    logging.info("=" * 70)
    logging.info("MonkeCraft starting; Python=%s; platform=%s; executable=%s", sys.version, sys.platform, sys.executable)
    logging.info("Working directory=%s; log=%s", os.getcwd(), log_path)
    logging.info("Environment snapshot (selected): %s", {k: os.environ.get(k) for k in ["PATH","APPDATA","LOCALAPPDATA","TEMP","TMP","SSL_CERT_FILE","REQUESTS_CA_BUNDLE"]})
    def excepthook(exc_type, exc_value, exc_tb):
        logging.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))
    sys.excepthook = excepthook
    if hasattr(threading, "excepthook"):
        threading.excepthook = lambda args: logging.critical("Uncaught thread exception", exc_info=(args.exc_type,args.exc_value,args.exc_traceback))
    return log_path

GAME_DIR = APP_DIR / "game"
SETTINGS_FILE = APP_DIR / "settings.json"
PACK_STATE_FILE = APP_DIR / "pack_state.json"
DESCRIPTION_CACHE = APP_DIR / "description_cache.json"
MODS_CACHE = APP_DIR / "mods_cache.json"
SERVER_CACHE = APP_DIR / "server_cache.json"
DATA_BASE = "https://raw.githubusercontent.com/s1derr1337/minecraft-laucnher-modpack/main/"
DESCRIPTION_URL = DATA_BASE + "description.json"
MODS_URL = DATA_BASE + "mods.json"
SERVER_URL = DATA_BASE + "server.json"
PACK_URL = DATA_BASE + "pack.json"
PACK_CACHE = APP_DIR / "pack_cache.json"
MANIFEST_URL = "https://raw.githubusercontent.com/s1derr1337/minecraft-laucnher-modpack/main/manifest.json"
DEFAULT_SETTINGS = {"java_path":"", "ram":6, "instance_path":str(GAME_DIR), "jvm_args":"", "game_args":"", "manifest_url":MANIFEST_URL}


def read_json(path, default):
    try:
        if path.exists(): return json.loads(path.read_text(encoding="utf-8"))
    except Exception: pass
    return default

def write_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(data,indent=4,ensure_ascii=False),encoding="utf-8")
def fetch_json_cached(url, cache_path, default):
    cache_path=Path(cache_path)
    try:
        req=urllib.request.Request(url, headers={"User-Agent":"MonkeCraft Launcher"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data=json.loads(r.read().decode("utf-8"))
        write_json(cache_path,data)
        return data
    except Exception as e:
        logging.warning("Remote JSON unavailable (%s): %s",url,e)
        return read_json(cache_path,default)

def download_file(url,target):
    target=Path(target); target.parent.mkdir(parents=True,exist_ok=True); tmp=target.with_suffix(target.suffix+".part"); urllib.request.urlretrieve(url,tmp); tmp.replace(target)
def find_fabric_version(install_dir):
    versions_dir=Path(install_dir)/"versions"
    if not versions_dir.exists(): return None
    candidates=[]
    for folder in versions_dir.iterdir():
        if not folder.is_dir() or not folder.name.startswith("fabric-loader-") or not folder.name.endswith("-"+MC_VERSION): continue
        if (folder/(folder.name+".json")).exists() and (folder/(folder.name+".jar")).exists(): candidates.append(folder.name)
    return sorted(candidates)[-1] if candidates else None

class InstallWorker(QThread):
    status=Signal(str); progress=Signal(int); maximum=Signal(int); finished_ok=Signal(str); failed=Signal(str)
    def __init__(self,install_dir): super().__init__(); self.install_dir=install_dir
    def run(self):
        stage="Подготовка папки игры"
        try:
            Path(self.install_dir).mkdir(parents=True,exist_ok=True)
            cb={"setStatus":lambda v:self.status.emit(str(v)),"setProgress":lambda v:self.progress.emit(int(v)),"setMax":lambda v:self.maximum.emit(int(v))}
            stage=f"Установка Minecraft {MC_VERSION}"
            self.status.emit(stage+"..."); minecraft_launcher_lib.install.install_minecraft_version(MC_VERSION,self.install_dir,callback=cb)

            # Ensure the Java runtime required by this Minecraft version is installed locally.
            stage="Проверка Java"
            version_json=Path(self.install_dir)/"versions"/MC_VERSION/(MC_VERSION+".json")
            component=None
            if version_json.exists():
                try: component=json.loads(version_json.read_text(encoding="utf-8")).get("javaVersion",{}).get("component")
                except Exception: component=None
            if component:
                java_path=minecraft_launcher_lib.runtime.get_executable_path(component,self.install_dir)
                if not java_path:
                    stage=f"Загрузка встроенной Java ({component})"
                    self.status.emit("Загрузка Java для Minecraft...")
                    minecraft_launcher_lib.runtime.install_jvm_runtime(component,self.install_dir,callback=cb)
                    java_path=minecraft_launcher_lib.runtime.get_executable_path(component,self.install_dir)
                if not java_path or not Path(java_path).exists():
                    raise FileNotFoundError("Не удалось найти Java после установки встроенного runtime.")

            stage="Установка Fabric"
            self.status.emit("Установка Fabric...")
            # Fabric installer subprocess calls "java" through PATH. Make the
            # bundled Minecraft runtime visible for this operation only.
            java_path = None
            if component:
                java_path = minecraft_launcher_lib.runtime.get_executable_path(component, self.install_dir)
            if not java_path or not Path(java_path).exists():
                raise FileNotFoundError("Java runtime не найден перед установкой Fabric.")
            java_dir = str(Path(java_path).parent)
            old_path = os.environ.get("PATH", "")
            old_java_home = os.environ.get("JAVA_HOME")
            try:
                os.environ["PATH"] = java_dir + os.pathsep + old_path
                os.environ["JAVA_HOME"] = java_dir
                logging.info("Fabric install using bundled Java: %s", java_path)
                minecraft_launcher_lib.mod_loader.get_mod_loader(LOADER).install(MC_VERSION,self.install_dir)
            finally:
                os.environ["PATH"] = old_path
                if old_java_home is None:
                    os.environ.pop("JAVA_HOME", None)
                else:
                    os.environ["JAVA_HOME"] = old_java_home
            self.finished_ok.emit(self.install_dir)
        except FileNotFoundError as e:
            self.failed.emit(f"Ошибка на этапе: {stage}\nWindows не смогла найти нужный файл.\n\n{e}")
        except Exception as e:
            self.failed.emit(f"Ошибка на этапе: {stage}\n\n{type(e).__name__}: {e}")

class PackWorker(QThread):
    status=Signal(str); progress=Signal(int); finished_ok=Signal(str); failed=Signal(str)
    def __init__(self,install_dir,manifest_url,state_file=PACK_STATE_FILE): super().__init__(); self.install_dir=Path(install_dir); self.manifest_url=manifest_url; self.state_file=Path(state_file)
    def run(self):
        try:
            if not self.manifest_url.strip(): self.finished_ok.emit("Манифест не настроен."); return
            self.status.emit("Проверка сборки...")
            with urllib.request.urlopen(self.manifest_url,timeout=30) as r: manifest=json.loads(r.read().decode("utf-8"))
            files=manifest.get("mods",manifest.get("files",[])); destinations=[]
            for item in files:
                rel=Path(item["path"])
                if rel.is_absolute() or ".." in rel.parts: raise ValueError(f"Недопустимый путь в манифесте: {rel}")
                destinations.append(self.install_dir/rel)
            previous=read_json(self.state_file,{}); same=previous.get("manifest")==manifest; present=all(p.exists() for p in destinations)
            if same and present: self.finished_ok.emit(f"Сборка {manifest.get('pack_version','')} актуальна."); return
            for i,(item,dest) in enumerate(zip(files,destinations),1):
                if dest.exists() and same: continue
                self.status.emit(f"Синхронизация {i}/{len(files)}: {item['path']}"); self.progress.emit(int((i-1)*100/max(1,len(files))))
                download_file(item["url"],dest); self.progress.emit(int(i*100/max(1,len(files))))
            write_json(self.state_file,{"manifest":manifest,"pack_version":manifest.get("pack_version","unknown")})
            self.finished_ok.emit(f"Сборка {manifest.get('pack_version','')} синхронизирована.")
        except Exception as e:self.failed.emit(str(e))

class LaunchWorker(QThread):
    started_game=Signal(); finished_game=Signal(); failed=Signal(str)
    def __init__(self,install_dir,nickname,settings): super().__init__(); self.install_dir=install_dir; self.nickname=nickname; self.settings=settings
    def run(self):
        try:
            version_id=find_fabric_version(self.install_dir)
            if not version_id: raise RuntimeError("Fabric-профиль не найден. Переустанови Minecraft + Fabric.")
            name=self.nickname; offline_uuid=str(uuid.uuid3(uuid.NAMESPACE_DNS,"OfflinePlayer:"+name))
            options={"username":name,"uuid":offline_uuid,"token":"0","gameDirectory":self.install_dir,"jvmArguments":[f"-Xmx{int(self.settings.get('ram',4))}G",f"-Xms{min(2,int(self.settings.get('ram',4)))}G"]}
            java=self.settings.get("java_path","").strip();
            if java: options["executablePath"]=java
            extra=self.settings.get("jvm_args","").strip();
            if extra: options["jvmArguments"].extend(extra.split())
            game=self.settings.get("game_args","").strip();
            if game: options["customArgs"]=game.split()
            command=minecraft_launcher_lib.command.get_minecraft_command(version_id,self.install_dir,options)
            startupinfo=subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            process=subprocess.Popen(command,cwd=self.install_dir,creationflags=subprocess.CREATE_NO_WINDOW,startupinfo=startupinfo)
            self.started_game.emit(); process.wait(); self.finished_game.emit()
        except FileNotFoundError as e:
            self.failed.emit("Не найден исполняемый файл Java. Проверь Java в настройках лаунчера или установи Java 25.\n\n" + str(e))
        except Exception as e:self.failed.emit(str(e))

# Minimal gzip-compressed NBT reader/writer for Minecraft servers.dat (preserves other entries).
_NBT_NAMES={1:"byte",2:"short",3:"int",4:"long",5:"float",6:"double",7:"bytearray",8:"string",9:"list",10:"compound",11:"intarray",12:"longarray"}
def _read_exact(f,n):
    b=f.read(n)
    if len(b)!=n: raise ValueError("Truncated NBT")
    return b
def _read_string(f): return _read_exact(f,struct.unpack(">H",_read_exact(f,2))[0]).decode("utf-8")
def _read_payload(f,t):
    if t==1:return struct.unpack(">b",_read_exact(f,1))[0]
    if t==2:return struct.unpack(">h",_read_exact(f,2))[0]
    if t==3:return struct.unpack(">i",_read_exact(f,4))[0]
    if t==4:return struct.unpack(">q",_read_exact(f,8))[0]
    if t==5:return struct.unpack(">f",_read_exact(f,4))[0]
    if t==6:return struct.unpack(">d",_read_exact(f,8))[0]
    if t==7:return _read_exact(f,struct.unpack(">i",_read_exact(f,4))[0])
    if t==8:return _read_string(f)
    if t==9:
        et=struct.unpack(">b",_read_exact(f,1))[0]; n=struct.unpack(">i",_read_exact(f,4))[0]; return (et,[_read_payload(f,et) for _ in range(n)])
    if t==10:
        d={}
        while True:
            et=struct.unpack(">b",_read_exact(f,1))[0]
            if et==0:break
            name=_read_string(f); d[name]=(et,_read_payload(f,et))
        return d
    if t==11:
        n=struct.unpack(">i",_read_exact(f,4))[0];return [struct.unpack(">i",_read_exact(f,4))[0] for _ in range(n)]
    if t==12:
        n=struct.unpack(">i",_read_exact(f,4))[0];return [struct.unpack(">q",_read_exact(f,8))[0] for _ in range(n)]
    raise ValueError("Unsupported NBT tag "+str(t))
def _write_string(f,s):
    b=str(s).encode("utf-8");f.write(struct.pack(">H",len(b)));f.write(b)
def _write_payload(f,t,v):
    if t==1:f.write(struct.pack(">b",v))
    elif t==2:f.write(struct.pack(">h",v))
    elif t==3:f.write(struct.pack(">i",v))
    elif t==4:f.write(struct.pack(">q",v))
    elif t==5:f.write(struct.pack(">f",v))
    elif t==6:f.write(struct.pack(">d",v))
    elif t==7:f.write(struct.pack(">i",len(v)));f.write(v)
    elif t==8:_write_string(f,v)
    elif t==9:
        et,items=v;f.write(struct.pack(">b",et));f.write(struct.pack(">i",len(items)))
        for x in items:_write_payload(f,et,x)
    elif t==10:
        for name,(et,x) in v.items():f.write(struct.pack(">b",et));_write_string(f,name);_write_payload(f,et,x)
        f.write(b"\x00")
    elif t==11:f.write(struct.pack(">i",len(v)));[f.write(struct.pack(">i",x)) for x in v]
    elif t==12:f.write(struct.pack(">i",len(v)));[f.write(struct.pack(">q",x)) for x in v]
def _load_servers(path):
    if not path.exists():return {"servers":(9,(10,[]))}
    raw=path.read_bytes()
    # Minecraft 26.3 stores servers.dat as plain NBT (not gzip).
    # Still accept gzip files left by older launcher versions.
    if raw[:2] == b"\x1f\x8b":
        raw=gzip.decompress(raw)
    f=io.BytesIO(raw)
    root=struct.unpack(">b",_read_exact(f,1))[0]
    if root!=10:raise ValueError("servers.dat root tag is not Compound")
    _read_string(f)
    return _read_payload(f,10)
def _save_servers(path,root):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(".dat.tmp")
    with open(tmp,"wb") as f:
        f.write(b"\x0a");_write_string(f,"");_write_payload(f,10,root)
    tmp.replace(path)
def add_server_to_dat(game_dir,server_data):
    ip=str(server_data.get("ip","")).strip();port=int(server_data.get("port",25565));name=str(server_data.get("name","MonkeCraft"))
    if not ip:return
    address=ip if port==25565 else f"{ip}:{port}"
    path=Path(game_dir)/"servers.dat";root=_load_servers(path)
    taglist=root.get("servers",(9,(10,[])))
    if taglist[0]!=9 or taglist[1][0]!=10:raise ValueError("Unexpected servers.dat list format")
    servers=taglist[1][1]; filtered=[]
    for entry in servers:
        addr=entry.get("ip",(8,""))[1]
        if addr.lower()!=address.lower():filtered.append(entry)
    entry={"hidden":(1,0),"ip":(8,address),"name":(8,name)}
    filtered.insert(0,entry);root["servers"]=(9,(10,filtered));_save_servers(path,root)

class Launcher:
    def __init__(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self.settings = read_json(SETTINGS_FILE, DEFAULT_SETTINGS.copy())
        self.nickname = read_json(APP_DIR / "nickname.json", {"name": ""}).get("name", "")
        self.game_dir = GAME_DIR
        self.manifest_url = MANIFEST_URL
        self.settings.setdefault("instance_path", str(GAME_DIR))
        self.settings.setdefault("manifest_url", MANIFEST_URL)

        self.remote_description = fetch_json_cached(DESCRIPTION_URL, DESCRIPTION_CACHE, {})
        self.remote_mods = fetch_json_cached(MODS_URL, MODS_CACHE, {"mods": []})
        self.remote_server = fetch_json_cached(SERVER_URL, SERVER_CACHE, {})
        self.remote_pack = fetch_json_cached(PACK_URL, PACK_CACHE, {})

        logging.info("Settings loaded: %s", self.settings)
        self.ui = LauncherUI(self)
        self.worker = None
        self.pending_launch = False
        self.save_settings()
        self.ui.update_install_button(self.installed())
        self.ui.show()

    def save_settings(self):
        self.settings["manifest_url"] = self.settings.get("manifest_url", MANIFEST_URL)
        write_json(SETTINGS_FILE, self.settings)

    def pack_info(self):
        pack = self.remote_pack
        if not isinstance(pack, dict):
            return None
        required = ("version", "minecraft", "loader", "loader_version", "pack_url")
        if not all(pack.get(key) for key in required):
            logging.warning("pack.json is incomplete or invalid")
            return None
        return pack

    def installed(self):
        d = Path(self.settings.get("instance_path", str(GAME_DIR)))
        vanilla = d / "versions" / MC_VERSION
        return vanilla.exists() and any(vanilla.iterdir()) and bool(find_fabric_version(d))

    def set_busy(self, msg, show_progress=False):
        self.ui.play_button.setEnabled(False)
        self.ui.status.setText(msg)
        if show_progress:
            self.ui.progress.show()
            self.ui.progress.setValue(0)
        else:
            self.ui.progress.hide()

    def set_idle(self, msg):
        self.ui.play_button.setEnabled(True)
        self.ui.status.setText(msg)
        self.ui.progress.hide()
        self.ui.update_install_button(self.installed())

    # Retained for compatibility, but startup sync is intentionally not invoked.
    def startup_sync(self):
        if self.worker and self.worker.isRunning():
            return
        pack = self.pack_info()
        if not pack:
            self.ui.status.setText("Информация о модпаке недоступна")
            return
        self.set_busy("Проверка сборки...", True)
        self.worker = MRPackWorker(pack["pack_url"], Path(self.settings.get("instance_path", str(GAME_DIR))))
        self.worker.status.connect(self.ui.status.setText)
        self.worker.progress.connect(self.progress_update)
        self.worker.finished_ok.connect(self.pack_done)
        self.worker.failed.connect(self.pack_error)
        self.worker.start()

    def progress_update(self, val):
        self.ui.progress.show()
        self.ui.progress.setValue(val)

    def pack_done(self, msg):
        self._sync_server()
        self.set_idle(msg)

    def pack_error(self, error):
        self.set_idle("Не удалось синхронизировать сборку")
        QMessageBox.warning(self.ui, "Синхронизация", str(error))

    def play_clicked(self):
        name = self.ui.nick.text().strip()
        if not name or len(name) < 3 or not name.replace("_", " ").replace(" ", "").isalnum():
            QMessageBox.warning(self.ui, "Никнейм", "Ник должен содержать 3–16 символов: буквы, цифры или _.")
            return
        self.nickname = name
        write_json(APP_DIR / "nickname.json", {"name": name})
        if self.worker and self.worker.isRunning():
            return
        if not self.installed():
            self.install()
            return
        self.sync_then_launch()

    def install(self):
        if self.worker and self.worker.isRunning():
            return
        self.set_busy("Установка Minecraft и Fabric...", True)
        self.worker = InstallWorker(self.settings.get("instance_path", str(GAME_DIR)))
        self.worker.status.connect(self.ui.status.setText)
        self.worker.progress.connect(self.progress_update)
        self.worker.maximum.connect(self.ui.progress.setMaximum)
        self.worker.finished_ok.connect(self.install_done)
        self.worker.failed.connect(self.install_error)
        self.worker.start()

    def install_done(self, directory):
        self.ui.progress.hide()
        self.set_idle("Minecraft и Fabric установлены. Синхронизация сборки...")
        self.sync_then_launch()

    def install_error(self, error):
        self.set_idle("Ошибка установки")
        QMessageBox.critical(self.ui, "Установка", str(error))

    def sync_then_launch(self):
        if self.worker and self.worker.isRunning():
            return
        pack = self.pack_info()
        if not pack:
            self.set_idle("Не удалось получить информацию о модпаке")
            QMessageBox.warning(self.ui, "Модпак", "pack.json отсутствует или повреждён.")
            return
        self.set_busy("Проверка и обновление модпака...", True)
        self.worker = MRPackWorker(pack["pack_url"], Path(self.settings.get("instance_path", str(GAME_DIR))))
        self.worker.status.connect(self.ui.status.setText)
        self.worker.progress.connect(self.progress_update)
        self.worker.finished_ok.connect(lambda _msg: (self._sync_server(), self.launch_game()))
        self.worker.failed.connect(self.sync_launch_error)
        self.worker.start()

    def _sync_server(self):
        try:
            add_server_to_dat(self.settings.get("instance_path", str(GAME_DIR)), self.remote_server)
        except Exception as e:
            logging.warning("Could not update servers.dat: %s", e)

    def sync_launch_error(self, error):
        self.set_idle("Синхронизация не выполнена")
        QMessageBox.warning(self.ui, "Сборка", str(error))

    def launch_game(self):
        self.ui.progress.hide()
        self.set_busy("Запуск Minecraft...")
        self.worker = LaunchWorker(self.settings.get("instance_path", str(GAME_DIR)), self.nickname, self.settings)
        self.worker.started_game.connect(self.ui.hide)
        self.worker.finished_game.connect(self.restore)
        self.worker.failed.connect(self.launch_error)
        self.worker.start()

    def launch_error(self, error):
        self.set_idle("Ошибка запуска")
        QMessageBox.critical(self.ui, "Запуск", str(error))

    def restore(self):
        self.ui.show()
        self.ui.raise_()
        self.ui.activateWindow()
        self.set_idle("Minecraft закрыт")

if __name__=="__main__":
    setup_logging()
    try:
        app=QApplication(sys.argv); launcher=Launcher(); sys.exit(app.exec())
    except Exception:
        logging.exception("Fatal launcher startup error")
        raise
