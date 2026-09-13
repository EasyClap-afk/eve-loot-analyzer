import copy
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
from PySide6.QtWidgets import QApplication

from app.cancellation import CancellationScope, check_cancelled
from app.engine import Engine
from app.esi import Esi
from app.i18n import set_language, tr
from app.storage import Store
from app.ui import MainWindow
from tests.test_integration import FakeEsi, populate
from tests.test_ui import wait_until


def test_stop_during_http_request_preserves_result_and_allows_restart(tmp_path):
    app = QApplication.instance() or QApplication([])
    received = threading.Event()
    release = threading.Event()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append(self.path)
            received.set()
            release.wait(10)
            try:
                self.send_response(200)
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'[]')
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    store = Store(tmp_path / 'stop.db')
    populate(store)
    fake = FakeEsi()
    fake.close = lambda: None
    esi = Esi(store)
    esi.client.close()
    esi.client = httpx.Client(base_url=f'http://127.0.0.1:{server.server_port}', timeout=30)
    w = MainWindow(store, Engine(store, esi))
    w.show()
    previous = Engine(store, fake).analyze('Item 1', {})
    w.raw.setPlainText('Item 1')
    w.render_result(previous)
    original = copy.deepcopy(previous)
    try:
        w.raw.setPlainText('Item 2\t10')
        w.analyze()
        wait_until(app, received.is_set)
        assert w.stop_button.isEnabled()
        assert w.stop_button.text() == 'Zatrzymaj analizę'
        w.language_buttons['en'].click()
        assert w.stop_button.text() == 'Stop analysis' and w.stop_button.isEnabled()
        w.pending_reanalysis = True
        started = time.monotonic()
        w.stop_button.click()
        w.raw.setPlainText('Item 3\t5')
        wait_until(app, lambda: not w.busy, seconds=2)
        assert time.monotonic() - started < 2
        assert not release.is_set()  # Server still has not answered.
        assert len(requests) == 1  # No history fetch after cancellation.
        assert not w.pending_reanalysis
        assert w.result == original
        assert w.raw.toPlainText() == 'Item 3\t5'
        assert w.analyze_button.isEnabled() and not w.stop_button.isEnabled()
        assert w.status.text() == tr('Analysis stopped. Edit the loot and analyze again.')
        assert not w.save_button.isEnabled()
        assert not store.sessions()
        assert not store.query('SELECT * FROM cache')
        w.engine.esi = fake
        w.analyze()
        wait_until(app, lambda: not w.busy)
        assert w.result['raw'] == 'Item 3\t5'
        assert w.result['regular'][0]['type_id'] == 3
        assert w.save_button.isEnabled()
        release.set()
        with CancellationScope(threading.Event()):
            assert esi.get('/success')[0] == []
            count = len(requests)
            assert esi.get('/success')[0] == []
            assert len(requests) == count  # Completed requests still use the cache.
    finally:
        release.set()
        if w.busy:
            w.stop_analysis()
            wait_until(app, lambda: not w.busy)
        w.close()
        esi.close()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)
        set_language('pl')


def test_stop_discards_success_already_queued_to_gui(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / 'race.db')
    populate(store)
    api = FakeEsi()
    api.close = lambda: None
    w = MainWindow(store, Engine(store, api))
    delivered = []
    try:
        w.run(lambda progress: {'stale': True}, delivered.append, cancellable=True)
        assert w.worker.wait(2000)  # Finish without processing queued GUI signals.
        w.stop_analysis()
        wait_until(app, lambda: not w.busy)
        assert delivered == []
        assert w.status.text() == tr('Analysis stopped. Edit the loot and analyze again.')
    finally:
        w.close()


def test_stop_unwinds_blueprint_analysis_without_incomplete_report(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / 'blueprint.db')
    populate(store)
    started = threading.Event()

    class SlowMaterials(FakeEsi):
        def orders(self, type_id):
            started.set()
            while True:
                check_cancelled()
                time.sleep(.01)

        def close(self):
            pass

    w = MainWindow(store, Engine(store, SlowMaterials()))
    try:
        w.raw.setPlainText('Item 6')
        w.analyze()
        wait_until(app, started.is_set)
        w.stop_button.click()
        wait_until(app, lambda: not w.busy)
        assert w.result is None
        assert not w.save_button.isEnabled()
        assert not w.pending_reanalysis
    finally:
        if w.busy:
            w.stop_analysis()
            wait_until(app, lambda: not w.busy)
        w.close()
