"""Aplicativo gráfico único. O motor HTTP só escuta na interface local.

O controlador não importa Qt: seu ciclo de vida pode ser verificado em Linux.
A janela, o tray e o WebEngine são carregados somente por ``main``.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import sys
import threading
import time
from typing import Callable


APP_NAME = "Escritura Integrada"
APP_ORGANIZATION = "Codisplan"


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def application_version() -> str:
    try:
        return (resource_root() / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        from app import __version__
        return __version__


class DesktopSmokeReport:
    """Diagnóstico incremental; só aprova depois do encerramento do motor."""

    def __init__(self, path: Path):
        self.path = path.resolve()
        self.result = {
            "schema_version": 2, "ok": False, "phase": "bootstrap",
            "version": application_version(), "platform": sys.platform,
            "packaged": bool(getattr(sys, "frozen", False)), "pid": os.getpid(),
            "shutdown_complete": False, "ui_verified": False, "events": [],
        }
        self.record("bootstrap")

    def record(self, phase: str, **values):
        self.result.update(values, phase=phase)
        self.result["events"].append({"phase": phase, "at_utc": datetime.now(timezone.utc).isoformat()})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def complete(self, stopped: bool, exit_code: int) -> int:
        success = bool(self.result.get("ui_verified") and stopped and exit_code == 0)
        self.record("shutdown_complete" if stopped else "shutdown_failed", ok=success,
                    shutdown_complete=stopped, exit_code=0 if success else 1)
        return 0 if success else 1


class LocalApplicationServer:
    """Um processo, uma instância Uvicorn, uma porta reservada antes da thread.

    ``stop`` é assíncrono. O chamador continua consultando ``snapshot`` até a
    thread finalizar, preservando o encerramento das requisições em andamento.
    """

    def __init__(self, app_factory: Callable | None = None):
        self._factory = app_factory
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._server = None
        self._socket: socket.socket | None = None
        self._stop_requested = threading.Event()
        self._state = "stopped"
        self._error = ""
        self._port = 0
        self._generation = 0

    def snapshot(self) -> dict:
        with self._lock:
            if self._state == "starting" and self._server and self._server.started:
                self._state = "running"
            return {
                "state": self._state,
                "error": self._error,
                "port": self._port,
                "url": f"http://127.0.0.1:{self._port}" if self._port else "",
                "generation": self._generation,
                "alive": bool(self._thread and self._thread.is_alive()),
            }

    def start(self, data_dir: str | Path, port: int = 0, *, demo: bool = False) -> bool:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            if not 0 <= int(port) <= 65535:
                raise ValueError("A porta deve estar entre 0 e 65535.")
            self._state, self._error = "starting", ""
            self._stop_requested.clear()
            self._server = None
            self._generation += 1
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                # Exclusividade no Windows; nunca reutilizar porta de outro processo.
                if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                else:
                    # Em Unix permite reiniciar depois de TIME_WAIT, sem SO_REUSEPORT.
                    # Um listener já ativo continua impedindo a abertura da porta.
                    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(("127.0.0.1", int(port)))
                listener.listen(128)
                listener.setblocking(False)
            except OSError as exc:
                listener.close()
                self._state = "error"
                self._error = f"Não foi possível abrir a porta local {port}: {exc}"
                return False
            self._socket = listener
            self._port = listener.getsockname()[1]
            self._thread = threading.Thread(
                target=self._run, args=(str(data_dir), bool(demo), listener),
                name="escritura-local", daemon=True,
            )
            self._thread.start()
            return True

    def _run(self, data_dir: str, demo: bool, listener: socket.socket) -> None:
        try:
            import uvicorn
            factory = self._factory
            if factory is None:
                # app.api também expõe uma instância ASGI no import. Esse import
                # deve usar o mesmo diretório explícito do desktop, inclusive no CI.
                previous_data_dir = os.environ.get("ESCRITURA_DATA_DIR")
                os.environ["ESCRITURA_DATA_DIR"] = data_dir
                try:
                    from app.api import create_app
                finally:
                    if previous_data_dir is None:
                        os.environ.pop("ESCRITURA_DATA_DIR", None)
                    else:
                        os.environ["ESCRITURA_DATA_DIR"] = previous_data_dir
                factory = create_app
            api = factory(data_dir=data_dir, demo=demo)
            server = uvicorn.Server(uvicorn.Config(
                api, host="127.0.0.1", port=self._port, workers=1,
                loop="asyncio", http="h11", lifespan="on",
                log_config=None, access_log=False, timeout_graceful_shutdown=10,
            ))
            with self._lock:
                self._server = server
                if self._stop_requested.is_set():
                    self._state = "stopped"
                    return
            server.run(sockets=[listener])
            with self._lock:
                if not server.started and not self._stop_requested.is_set():
                    self._state = "error"
                    self._error = "A aplicação não concluiu a inicialização. Consulte os registros."
                else:
                    self._state = "stopped"
        except BaseException as exc:
            logging.getLogger(__name__).exception("Falha no motor local")
            with self._lock:
                self._state = "error"
                self._error = f"{type(exc).__name__}: {exc}"
        finally:
            listener.close()
            with self._lock:
                self._socket = None

    def stop(self) -> None:
        with self._lock:
            if not self._thread or not self._thread.is_alive():
                if self._state != "error":
                    self._state = "stopped"
                return
            self._stop_requested.set()
            self._state = "stopping"
            if self._server is not None:
                self._server.should_exit = True

    def wait_stopped(self, timeout: float = 15) -> bool:
        """Somente para testes/encerramento sem event loop; não usar na UI."""
        thread = self._thread
        if thread:
            thread.join(timeout)
        return not bool(thread and thread.is_alive())


def configure_logging(profile_dir: Path) -> None:
    log_dir = profile_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "aplicacao.log", maxBytes=2_000_000,
                                  backupCount=4, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def run_desktop(smoke: DesktopSmokeReport | None = None) -> int:
    # Imports deliberadamente locais: o container não depende de Qt.
    from PySide6.QtCore import (QCoreApplication, QEvent, QLockFile, QMarginsF, QSettings,
                              QStandardPaths, Qt, QTimer, QUrl, qInstallMessageHandler)
    from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QPageLayout, QPageSize, QPainter, QPixmap
    from PySide6.QtNetwork import QLocalServer, QLocalSocket, QNetworkAccessManager, QNetworkRequest
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
        QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
        QMessageBox, QPushButton, QSpinBox, QStackedWidget, QSystemTrayIcon,
        QVBoxLayout, QWidget,
    )
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView

    app = QApplication(sys.argv)
    app.setOrganizationName(APP_ORGANIZATION)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(application_version())
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)

    smoke_result = str(smoke.path) if smoke else None
    smoke_dir = (Path(os.environ.get("ESCRITURA_DESKTOP_SMOKE_PROFILE",
                                   str(smoke.path.parent / "desktop-smoke-profile"))).resolve() if smoke else None)
    profile_dir = smoke_dir or Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))
    profile_dir.mkdir(parents=True, exist_ok=True)
    settings = QSettings(str(profile_dir / "config.ini"), QSettings.IniFormat)
    configure_logging(profile_dir)

    def qt_message(_kind, context, message):
        logging.getLogger("qt").info("%s: %s", context.category or "qt", message)

    qInstallMessageHandler(qt_message)
    if smoke:
        smoke.record("qt_initialized", profile_isolated=True)

    instance_name = "escritura-" + hashlib.sha256(str(profile_dir).encode()).hexdigest()[:24]
    instance_lock = QLockFile(str(profile_dir / "aplicacao.lock"))
    instance_lock.setStaleLockTime(0)
    if not instance_lock.tryLock(100):
        if smoke:
            smoke.record("failed", detail="O perfil isolado do smoke já está bloqueado.")
            return 1
        socket_client = QLocalSocket()
        socket_client.connectToServer(instance_name)
        if socket_client.waitForConnected(1500):
            socket_client.write(b"show\n")
            socket_client.waitForBytesWritten(1000)
            socket_client.disconnectFromServer()
            return 0
        QMessageBox.information(None, APP_NAME,
            "A aplicação já está aberta ou está iniciando. Procure o ícone na área de notificações.")
        return 1

    def make_icon() -> QIcon:
        for relative in ("app/assets/app.ico", "frontend/dist/brand.svg", "frontend/public/brand.svg"):
            candidate = resource_root() / relative
            if candidate.is_file():
                icon = QIcon(str(candidate))
                if not icon.isNull():
                    return icon
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor("#215e59"))
        painter = QPainter(pixmap)
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Segoe UI", 32, QFont.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "E")
        painter.end()
        return QIcon(pixmap)

    icon = make_icon()
    app.setWindowIcon(icon)
    controller = LocalApplicationServer()

    class ApplicationPage(QWebEnginePage):
        def javaScriptConsoleMessage(self, level, message, line_number, source_id):
            logging.getLogger("webengine").info("%s %s:%s %s", level, source_id, line_number, message)

        def acceptNavigationRequest(self, url, nav_type, is_main_frame):
            base = QUrl(controller.snapshot()["url"])
            own_origin = (url.scheme() == "http" and url.host() == "127.0.0.1"
                          and url.port() == base.port())
            blob_origin = QUrl(url.toString()[5:]) if url.scheme() == "blob" else QUrl()
            own_blob = (blob_origin.scheme() == "http" and blob_origin.host() == "127.0.0.1"
                        and blob_origin.port() == base.port())
            if own_origin or own_blob or url.toString() == "about:blank":
                return True
            if is_main_frame and nav_type == QWebEnginePage.NavigationTypeLinkClicked:
                if url.scheme() in ("https", "mailto"):
                    QDesktopServices.openUrl(url)
            return False

        def createWindow(self, _window_type):
            snapshot = controller.snapshot()
            origin, local = self.url(), QUrl(snapshot["url"])
            factory = getattr(self, "print_page_factory", None)
            if (factory and snapshot["state"] == "running" and origin.scheme() == "http"
                    and origin.host() == "127.0.0.1" and origin.port() == local.port()):
                # Não abre outra janela: a página interna só recebe o HTML de impressão.
                return factory()
            return None

    class PrintPage(QWebEnginePage):
        def acceptNavigationRequest(self, url, _nav_type, is_main_frame):
            # O relatório usa window.open('') e document.write(). URLs externas,
            # arquivos locais e frames não são destinos admitidos nesta página.
            return is_main_frame and url.toString() == "about:blank"

        def createWindow(self, _window_type):
            return None

    class DesktopWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle(f"{APP_NAME} · {application_version()}")
            self.setWindowIcon(icon)
            self.resize(1360, 850)
            self.setMinimumSize(800, 560)
            self._exit_requested = False
            self._restart_requested = False
            self._guard_pending = False
            self._loaded_generation = -1
            self._loading_generation = -1
            self._health_pending = False
            self._healthy = False
            self._last_state = ""
            self._hidden_notice = False
            self._smoke_finished = False
            self._smoke_started = time.monotonic()
            self._smoke_deadline = max(20.0, float(os.environ.get("ESCRITURA_DESKTOP_SMOKE_TIMEOUT", "125")))
            self._smoke_candidate = None
            self._smoke_stable_polls = 0
            self._smoke_capture_pending = False
            self._smoke_paint_ready = False
            self._tearing_down = False
            self._started_at = 0.0
            self._ipc_clients = []
            self._print_page = None
            self._print_dialog_open = False
            self._pdf_pending = False

            self.stack = QStackedWidget()
            self.setCentralWidget(self.stack)
            self.status_page = QWidget()
            layout = QVBoxLayout(self.status_page)
            layout.setContentsMargins(52, 48, 52, 48)
            layout.addStretch()
            title = QLabel(APP_NAME)
            title.setStyleSheet("font-size: 27px; font-weight: 600; color: #254a47;")
            layout.addWidget(title)
            self.status_title = QLabel("Iniciando a aplicação…")
            self.status_title.setStyleSheet("font-size: 19px; font-weight: 600; margin-top: 16px;")
            layout.addWidget(self.status_title)
            self.status_detail = QLabel("Aguarde a abertura da sua área de trabalho.")
            self.status_detail.setWordWrap(True)
            self.status_detail.setTextFormat(Qt.PlainText)
            self.status_detail.setStyleSheet("font-size: 14px; color: #4d5b63; margin: 8px 0 24px;")
            layout.addWidget(self.status_detail)
            buttons = QHBoxLayout()
            self.start_button = QPushButton("Iniciar aplicação")
            self.start_button.clicked.connect(self.start_application)
            buttons.addWidget(self.start_button)
            config_button = QPushButton("Configurações")
            config_button.clicked.connect(self.configure)
            buttons.addWidget(config_button)
            logs_button = QPushButton("Abrir registros")
            logs_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(profile_dir / "logs"))))
            buttons.addWidget(logs_button)
            buttons.addStretch()
            layout.addLayout(buttons)
            layout.addStretch()
            layout.addWidget(QLabel(f"Versão {application_version()} · Dados mantidos no computador"))
            self.stack.addWidget(self.status_page)

            self.web_profile = QWebEngineProfile("EscrituraIntegrada", self)
            self.web_profile.setPersistentStoragePath(str(profile_dir / "navegador"))
            self.web_profile.setCachePath(str(profile_dir / "cache"))
            self.web_profile.setHttpCacheType(QWebEngineProfile.DiskHttpCache)
            self.web = QWebEngineView()
            self.page = ApplicationPage(self.web_profile, self.web)
            self.page.print_page_factory = self.create_print_page
            self.web.setPage(self.page)
            # createWindow restringe toda solicitação à página interna de relatório.
            self.page.settings().setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, True)
            self.page.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
            self.page.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, False)
            self.page.settings().setAttribute(QWebEngineSettings.FullScreenSupportEnabled, False)
            self.web.setContextMenuPolicy(Qt.NoContextMenu)
            self.web.loadFinished.connect(self.on_loaded)
            self.page.renderProcessTerminated.connect(self.on_render_terminated)
            self.web_profile.downloadRequested.connect(self.download)
            self.stack.addWidget(self.web)
            self.statusBar().showMessage("Iniciando…")

            self.tray = QSystemTrayIcon(icon, self)
            self.tray.setToolTip(APP_NAME)
            self.tray_menu = QMenu(self)
            self.actions = {}
            for label, callback in (
                ("Abrir", self.show_window),
                ("Iniciar", self.start_application),
                ("Parar", lambda: self.guard_operation("parar", self.stop_application)),
                ("Reiniciar", lambda: self.guard_operation("reiniciar", self.restart_application)),
                ("Configurações", self.configure),
                ("Sair", lambda: self.guard_operation("sair", self.exit_application)),
            ):
                if label in ("Configurações", "Sair"):
                    self.tray_menu.addSeparator()
                action = QAction(label, self)
                action.triggered.connect(callback)
                self.tray_menu.addAction(action)
                self.actions[label] = action
            self.tray.setContextMenu(self.tray_menu)
            self.tray.activated.connect(self.on_tray_activated)
            self.tray.show()

            self.network = QNetworkAccessManager(self)
            self.timer = QTimer(self)
            self.timer.setInterval(200)
            self.timer.timeout.connect(self.poll)
            self.timer.start()

            QLocalServer.removeServer(instance_name)
            self.ipc = QLocalServer(self)
            self.ipc.setSocketOptions(QLocalServer.UserAccessOption)
            if not self.ipc.listen(instance_name):
                logging.getLogger(__name__).warning("IPC não disponível: %s", self.ipc.errorString())
            self.ipc.newConnection.connect(self.on_second_instance)

        def on_second_instance(self):
            while self.ipc.hasPendingConnections():
                client = self.ipc.nextPendingConnection()
                self._ipc_clients.append(client)
                self.show_window()
                client.disconnectFromServer()
                client.deleteLater()
            self._ipc_clients.clear()

        def on_tray_activated(self, reason):
            if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
                self.show_window()

        def show_window(self):
            self.showNormal()
            self.raise_()
            self.activateWindow()

        def closeEvent(self, event):
            if self._exit_requested and not controller.snapshot()["alive"]:
                event.accept()
                return
            event.ignore()
            if QSystemTrayIcon.isSystemTrayAvailable():
                self.hide()
                if not self._hidden_notice:
                    self.tray.showMessage(APP_NAME, "A aplicação continua aberta na área de notificações.",
                                          QSystemTrayIcon.Information, 3500)
                    self._hidden_notice = True
            else:
                self.guard_operation("sair", self.exit_application)

        def current_data_dir(self) -> Path:
            if smoke_dir:
                return smoke_dir / "data"
            return Path(settings.value("data_dir", str(profile_dir / "data"), type=str)).expanduser()

        def start_application(self):
            if controller.snapshot()["alive"]:
                return
            self._healthy = False
            self._started_at = time.monotonic()
            self.stack.setCurrentWidget(self.status_page)
            port = settings.value("port", 0, type=int)
            if smoke_dir:
                port = 0
            remembered = settings.value("last_auto_port", 0, type=int) if port == 0 and not smoke_dir else 0
            started = controller.start(self.current_data_dir(), port or remembered, demo=bool(smoke_dir))
            if not started and port == 0 and remembered:
                started = controller.start(self.current_data_dir(), 0, demo=False)
            if started and port == 0:
                settings.setValue("last_auto_port", controller.snapshot()["port"])
                settings.sync()
            self.poll()

        def guard_operation(self, verb, callback):
            if self._guard_pending:
                return
            if not self._healthy or self.stack.currentWidget() is not self.web:
                callback()
                return
            self._guard_pending = True
            script = """(() => {
                try {
                    if (typeof window.escrituraHasUnsavedChanges === 'function')
                        return Boolean(window.escrituraHasUnsavedChanges());
                    return Boolean(window.__ESCRITURA_HAS_UNSAVED__ ||
                        document.querySelector('[data-unsaved="true"]'));
                } catch (_) { return true; }
            })()"""
            def decision(dirty):
                self._guard_pending = False
                if dirty:
                    self.show_window()
                    answer = QMessageBox.question(self, "Alterações em edição",
                        f"Há alterações ainda não salvas. Deseja descartá-las e {verb}?",
                        QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
                    if answer != QMessageBox.Discard:
                        return
                callback()
            self.page.runJavaScript(script, decision)

        def stop_application(self):
            self._healthy = False
            self.stack.setCurrentWidget(self.status_page)
            controller.stop()
            self.poll()

        def restart_application(self):
            self._restart_requested = True
            self.stop_application()

        def exit_application(self):
            self._exit_requested = True
            self._restart_requested = False
            self.stop_application()

        def set_status(self, title, detail):
            self.status_title.setText(title)
            self.status_detail.setText(detail)
            self.statusBar().showMessage(title)

        def poll(self):
            if self._tearing_down:
                return
            snapshot = controller.snapshot()
            state = snapshot["state"]
            alive = snapshot["alive"]
            self.actions["Iniciar"].setEnabled(not alive and not self._exit_requested)
            self.start_button.setEnabled(not alive and not self._exit_requested)
            self.actions["Parar"].setEnabled(alive and state != "stopping")
            self.actions["Reiniciar"].setEnabled(state != "stopping" and not self._exit_requested)
            if not alive:
                if self._exit_requested:
                    if self._pdf_pending or self._print_dialog_open:
                        self.set_status("Concluindo o relatório…", "Aguarde a gravação do PDF ou feche a janela de salvamento.")
                        return
                    self.timer.stop()
                    self.tray.hide()
                    self.ipc.close()
                    instance_lock.unlock()
                    self.dispose_webengine()
                    app.exit(0 if not smoke or smoke.result.get("ui_verified") else 1)
                    return
                if self._restart_requested:
                    self._restart_requested = False
                    self.start_application()
                    return
            if state == "starting":
                self.set_status("Iniciando a aplicação…", "Abrindo os dados e preparando sua área de trabalho.")
            elif state == "stopping":
                self.set_status("Encerrando as operações…", "Aguarde a conclusão das solicitações em andamento.")
            elif state == "stopped":
                self.set_status("Aplicação pausada", "Seus dados estão preservados. Use Iniciar para continuar.")
            elif state == "error":
                self.stack.setCurrentWidget(self.status_page)
                self.set_status("Não foi possível iniciar", snapshot["error"] + "\nVerifique a pasta de dados, a porta e os registros.")
                if self._last_state != "error":
                    self.show_window()
                    self.tray.showMessage(APP_NAME, "A aplicação precisa de atenção. Abra a janela para verificar.", QSystemTrayIcon.Warning)
                if smoke_result:
                    self.finish_smoke(False, snapshot["error"])
            elif state == "running":
                if not self._healthy and not self._health_pending:
                    self.check_health(snapshot)
            if state in ("starting", "running") and not self._healthy and time.monotonic() - self._started_at > 30:
                self.set_status("A inicialização está demorando", "Confira os registros ou use Parar e Iniciar para tentar novamente.")
                if not smoke_result:
                    self.show_window()
            self._last_state = state
            if smoke_result and not self._smoke_finished and time.monotonic() - self._smoke_started > self._smoke_deadline:
                self.finish_smoke(False, "Tempo excedido ao abrir API e interface.")

        def dispose_webengine(self):
            if self._tearing_down:
                return
            self._tearing_down = True
            self.timer.stop()
            self.web.stop()
            if self._print_page is not None:
                self.release_print_page(self._print_page)
            # O perfil só pode ser destruído depois de todas as suas páginas.
            self.stack.removeWidget(self.web)
            self.web.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.web_profile.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

        def check_health(self, snapshot):
            self._health_pending = True
            request = QNetworkRequest(QUrl(snapshot["url"] + "/api/health"))
            request.setTransferTimeout(2000)
            request.setAttribute(QNetworkRequest.CacheLoadControlAttribute, QNetworkRequest.AlwaysNetwork)
            reply = self.network.get(request)
            generation = snapshot["generation"]
            def complete():
                self._health_pending = False
                try:
                    payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
                except (ValueError, UnicodeError):
                    payload = {}
                reply.deleteLater()
                current = controller.snapshot()
                if (current["generation"] != generation or current["state"] != "running"
                        or payload.get("status") != "ok"):
                    return
                if smoke and (payload.get("version") != application_version() or payload.get("demo") is not True):
                    self.finish_smoke(False, "A saúde da API não confirmou a versão e o ambiente isolado de demonstração.")
                    return
                self._healthy = True
                if smoke:
                    smoke.record("api_ready", health=payload)
                self.statusBar().showMessage(f"Aplicação ativa · {current['url']} · {application_version()}")
                if self._loaded_generation != generation and self._loading_generation != generation:
                    self._loading_generation = generation
                    self.web.setUrl(QUrl(current["url"]))
            reply.finished.connect(complete)

        def on_loaded(self, success):
            if self._exit_requested or self._tearing_down:
                return
            snapshot = controller.snapshot()
            if snapshot["state"] != "running" or not self._healthy:
                return
            if not success:
                self.stack.setCurrentWidget(self.status_page)
                self.set_status("Não foi possível abrir a interface", "Reinicie a aplicação pelo menu ou confira os registros.")
                self.show_window()
                if smoke_result:
                    self.finish_smoke(False, "QWebEngineView não carregou a interface.")
                return
            self._loaded_generation = snapshot["generation"]
            self.stack.setCurrentWidget(self.web)
            if smoke_result:
                QTimer.singleShot(300, self.inspect_smoke)

        def on_render_terminated(self, status, exit_code):
            if self._tearing_down:
                return
            detail = f"O navegador integrado encerrou inesperadamente ({status}, código {exit_code})."
            logging.getLogger(__name__).error(detail)
            self.stack.setCurrentWidget(self.status_page)
            self.set_status("Não foi possível manter a interface aberta", detail + " Use Reiniciar ou consulte os registros.")
            self.show_window()
            if smoke:
                self.finish_smoke(False, detail)

        def inspect_smoke(self):
            if self._smoke_finished or self._tearing_down:
                return
            script = """(() => {
                const login = document.querySelector('.demo-login button');
                if (login && !login.disabled && !window.__escrituraSmokeLoginRequested) {
                    window.__escrituraSmokeLoginRequested = true;
                    login.click();
                }
                const active = document.querySelector('#active-company');
                const brand = document.querySelector('.app-shell .brand img');
                const main = document.querySelector('.main-content');
                const side = document.querySelector('.sidebar');
                return JSON.stringify({title:document.title, ready:document.readyState,
                    app:Boolean(document.querySelector('.app-shell')),
                    loginRequested:Boolean(window.__escrituraSmokeLoginRequested),
                    mainTextLength:main?.innerText.length || 0,
                    heading:main?.querySelector('h1,h2')?.innerText || '',
                    companyId:active?.value || '',
                    company:active?.selectedOptions[0]?.textContent || '',
                    period:document.querySelector('#active-period')?.value || '',
                    version:document.querySelector('.connection small')?.textContent || '',
                    navigationItems:document.querySelectorAll('.sidebar nav button').length,
                    stylesheetApplied:side ? getComputedStyle(side).display==='flex' : false,
                    brandLoaded:Boolean(brand?.complete && brand.naturalWidth>0),
                    errors:[...document.querySelectorAll('[role=alert]')].map(x=>x.textContent)
                });
            })()"""
            def inspected(value):
                if self._smoke_finished or self._tearing_down:
                    return
                try:
                    dom = json.loads(value) if isinstance(value, str) else {}
                except ValueError:
                    dom = {}
                verified = (dom.get("app") and dom.get("ready") == "complete"
                            and dom.get("loginRequested") and dom.get("companyId")
                            and dom.get("navigationItems", 0) >= 10
                            and dom.get("mainTextLength", 0) > 80
                            and dom.get("version") == application_version()
                            and dom.get("brandLoaded") and dom.get("stylesheetApplied")
                            and not dom.get("errors"))
                if verified:
                    candidate = (dom.get("companyId"), dom.get("company"), dom.get("period"),
                                 dom.get("version"), dom.get("heading"), dom.get("mainTextLength"))
                    if candidate != self._smoke_candidate:
                        self._smoke_candidate = candidate
                        self._smoke_stable_polls = 1
                        self._smoke_paint_ready = False
                    else:
                        self._smoke_stable_polls += 1
                    if self._smoke_stable_polls >= 3 and self._smoke_paint_ready:
                        dom["stable_polls_before_capture"] = self._smoke_stable_polls
                        dom["composition_wait_ms"] = 1200
                        self.finish_smoke(True, "API, autenticação de demonstração e área de trabalho Vue renderizadas.", dom)
                        return
                    if self._smoke_stable_polls >= 3 and not self._smoke_capture_pending:
                        # O callback JS pode preceder o frame do compositor. Não
                        # capturar nele imediatamente: deixe o event loop pintar,
                        # então valide novamente o mesmo contexto antes do grab.
                        self._smoke_capture_pending = True
                        expected_candidate = candidate
                        def after_composition():
                            self._smoke_capture_pending = False
                            if self._smoke_finished or self._tearing_down:
                                return
                            self._smoke_paint_ready = self._smoke_candidate == expected_candidate
                            self.inspect_smoke()
                        QTimer.singleShot(1200, after_composition)
                        return
                    QTimer.singleShot(300, self.inspect_smoke)
                elif time.monotonic() - self._smoke_started >= self._smoke_deadline:
                    self.finish_smoke(False, "A área de trabalho Vue não concluiu a renderização esperada.", dom)
                else:
                    self._smoke_candidate = None
                    self._smoke_stable_polls = 0
                    self._smoke_paint_ready = False
                    QTimer.singleShot(300, self.inspect_smoke)
            self.page.runJavaScript(script, inspected)

        def finish_smoke(self, success, detail, dom=None):
            if self._smoke_finished:
                return
            self._smoke_finished = True
            screenshot = smoke.path.with_suffix(".png")
            pixmap = self.grab()
            captured = not pixmap.isNull() and pixmap.save(str(screenshot))
            if not captured:
                success, detail = False, detail + " Não foi possível capturar a janela."
            smoke.record("ui_rendered" if success else "failed", ui_verified=bool(success),
                         detail=detail, server=controller.snapshot(), dom=dom,
                         screenshot=screenshot.name if captured else None,
                         window_size={"width": self.width(), "height": self.height()},
                         tray_available=QSystemTrayIcon.isSystemTrayAvailable(),
                         tray_actions=list(self.actions))
            smoke.record("shutdown_requested")
            QTimer.singleShot(50, self.exit_application)

        def create_print_page(self):
            if self._pdf_pending or self._print_dialog_open or self._exit_requested:
                self.statusBar().showMessage("Aguarde a conclusão do relatório em andamento.", 6000)
                return None
            if self._print_page is not None:
                self.release_print_page(self._print_page)
            page = PrintPage(self.web_profile, self)
            page.settings().setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, False)
            page.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
            page.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, False)
            page.settings().setAttribute(QWebEngineSettings.PluginsEnabled, False)
            self._print_page = page
            page.printRequested.connect(lambda: self.save_print_page(page))
            page.pdfPrintingFinished.connect(lambda path, success: self.pdf_finished(page, path, success))
            page.windowCloseRequested.connect(lambda: self.release_print_page(page)
                                              if not self._pdf_pending and not self._print_dialog_open else None)
            # Uma solicitação bloqueada ou sem window.print não conserva páginas indefinidamente.
            QTimer.singleShot(60000, lambda: self.release_print_page(page)
                              if page is self._print_page and not self._pdf_pending and not self._print_dialog_open else None)
            return page

        def release_print_page(self, page):
            if page is self._print_page:
                self._print_page = None
                page.deleteLater()

        def save_print_page(self, page):
            if page is not self._print_page or self._pdf_pending or self._print_dialog_open:
                return
            self._print_dialog_open = True
            title = "".join(c if c.isalnum() or c in " ._-" else "-" for c in page.title()).strip(" .")[:100]
            suggested = (title or "Relatorio") + ".pdf"
            folder = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation)
            dialog = QFileDialog(self, "Salvar relatório em PDF", folder)
            dialog.setAcceptMode(QFileDialog.AcceptSave)
            dialog.setFileMode(QFileDialog.AnyFile)
            dialog.setNameFilter("Documento PDF (*.pdf)")
            dialog.setDefaultSuffix("pdf")
            dialog.selectFile(suggested)
            try:
                accepted = dialog.exec() == QDialog.Accepted
                paths = dialog.selectedFiles() if accepted else []
            finally:
                self._print_dialog_open = False
                dialog.deleteLater()
            if not paths or page is not self._print_page:
                self.release_print_page(page)
                return
            self._pdf_pending = True
            self.statusBar().showMessage("Gerando o relatório em PDF…")
            layout = QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Landscape,
                                 QMarginsF(12, 12, 12, 12), QPageLayout.Millimeter)
            try:
                page.printToPdf(paths[0], layout)
                QTimer.singleShot(60000, lambda: self.pdf_timeout(page))
            except Exception:
                logging.getLogger(__name__).exception("Falha ao solicitar PDF do relatório")
                self.pdf_finished(page, paths[0], False)

        def pdf_timeout(self, page):
            if page is self._print_page and self._pdf_pending:
                page.triggerAction(QWebEnginePage.Stop)
                self.pdf_finished(page, "", False)

        def pdf_finished(self, page, path, success):
            if page is not self._print_page:
                return
            self._pdf_pending = False
            self.release_print_page(page)
            if success:
                self.statusBar().showMessage(f"PDF salvo: {Path(path).name}", 12000)
            else:
                self.statusBar().showMessage("Não foi possível concluir o PDF.", 12000)
                self._print_dialog_open = True
                try:
                    QMessageBox.warning(self, "Relatório em PDF",
                        "Não foi possível concluir a gravação do relatório. Confira a pasta escolhida e tente novamente.")
                finally:
                    self._print_dialog_open = False

        def download(self, request):
            name = Path(request.downloadFileName().replace("\\", "/")).name or "relatorio.csv"
            folder = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
            target, _selected = QFileDialog.getSaveFileName(self, "Salvar arquivo", str(Path(folder) / name))
            if target:
                destination = Path(target)
                request.setDownloadDirectory(str(destination.parent))
                request.setDownloadFileName(destination.name)
                request.accept()
            else:
                request.cancel()

        def configure(self):
            dialog = QDialog(self)
            dialog.setWindowTitle("Configurações da aplicação")
            dialog.setMinimumWidth(560)
            layout = QVBoxLayout(dialog)
            form = QFormLayout()
            folder_row = QWidget()
            row = QHBoxLayout(folder_row)
            row.setContentsMargins(0, 0, 0, 0)
            data_folder = QLineEdit(str(self.current_data_dir()))
            choose = QPushButton("Escolher…")
            def select_folder():
                selected = QFileDialog.getExistingDirectory(dialog, "Pasta de dados", data_folder.text())
                if selected:
                    data_folder.setText(selected)
            choose.clicked.connect(select_folder)
            row.addWidget(data_folder)
            row.addWidget(choose)
            form.addRow("Pasta de dados", folder_row)
            port = QSpinBox()
            port.setRange(0, 65535)
            port.setSpecialValueText("Automática")
            port.setValue(settings.value("port", 0, type=int))
            form.addRow("Porta local", port)
            minimized = QCheckBox("Iniciar minimizado na área de notificações")
            minimized.setChecked(settings.value("start_minimized", False, type=bool))
            form.addRow("", minimized)
            layout.addLayout(form)
            note = QLabel("Pasta e porta serão aplicadas no próximo reinício. Alterar a pasta abre os dados desse local; nenhum arquivo será movido automaticamente.")
            note.setWordWrap(True)
            note.setStyleSheet("color: #4d5b63; margin: 12px 0;")
            layout.addWidget(note)
            button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
            button_box.accepted.connect(dialog.accept)
            button_box.rejected.connect(dialog.reject)
            layout.addWidget(button_box)
            if dialog.exec() != QDialog.Accepted:
                return
            candidate = Path(data_folder.text().strip()).expanduser()
            if not data_folder.text().strip() or not candidate.is_absolute():
                QMessageBox.warning(self, "Pasta de dados", "Escolha uma pasta com caminho completo.")
                return
            try:
                candidate.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                QMessageBox.warning(self, "Pasta de dados", f"Não foi possível preparar a pasta: {exc}")
                return
            settings.setValue("data_dir", str(candidate))
            settings.setValue("port", port.value())
            settings.setValue("start_minimized", minimized.isChecked())
            settings.sync()
            self.statusBar().showMessage("Configurações salvas. Pasta e porta serão aplicadas ao reiniciar a aplicação.", 10000)

    window = DesktopWindow()
    minimized = settings.value("start_minimized", False, type=bool)
    if smoke_result or not minimized or not QSystemTrayIcon.isSystemTrayAvailable():
        window.show()
    QTimer.singleShot(0, window.start_application)
    exit_code = app.exec()
    # Normalmente o timer já concluiu o encerramento. Também cobre logoff do SO.
    controller.stop()
    stopped = controller.wait_stopped(12)
    window.dispose_webengine()
    instance_lock.unlock()
    qInstallMessageHandler(None)
    return smoke.complete(stopped, exit_code) if smoke else exit_code


def main() -> int:
    # Execução por arquivo fonte também encontra o pacote app; PyInstaller usa pathex.
    project = str(Path(__file__).resolve().parents[1])
    if project not in sys.path:
        sys.path.insert(0, project)
    smoke = None
    try:
        result = os.environ.get("ESCRITURA_DESKTOP_SMOKE_RESULT")
        smoke = DesktopSmokeReport(Path(result)) if result else None
        return run_desktop(smoke)
    except Exception as exc:
        logging.getLogger(__name__).exception("Erro ao abrir a aplicação gráfica")
        if smoke:
            # Um diálogo modal bloquearia o CI e esconderia o diagnóstico.
            smoke.record("failed", ok=False, detail=f"{type(exc).__name__}: {exc}")
            return 1
        # Um binário windowed nunca depende de stderr para explicar a falha.
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            emergency_app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, APP_NAME,
                f"Não foi possível abrir a aplicação.\n{type(exc).__name__}: {exc}\n"
                "Confira se todos os arquivos do pacote foram extraídos.")
            del emergency_app
        except Exception:
            if sys.platform == "win32":
                import ctypes
                ctypes.windll.user32.MessageBoxW(None, f"Não foi possível abrir a aplicação:\n{exc}", APP_NAME, 16)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
