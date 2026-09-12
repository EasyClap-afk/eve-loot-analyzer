import copy
import html
import json
import logging
import re
import sys
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path
from statistics import median
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QDate, QTranslator, QLocale, QLibraryInfo
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPixmap, QPainter, QPen
from PySide6.QtCore import QUrl, QSize, QPointF
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QDialog, QFormLayout, QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit, QCheckBox, QMessageBox, QDialogButtonBox, QFileDialog, QTextBrowser, QScrollArea, QFrame, QDateEdit
from .storage import dumps, data_dir
from .rules import tax, broker, SKILL_IDS
from .sde import update_sde
from .sso import SSO, REDIRECT
from .i18n import tr, message, error_text, set_language, language
WATCH_MODES = ('Sell price', 'Buy price', 'Realistic net')

def language_flag(code):
    # Draw real flags rather than emoji, which Windows may display as letters.
    pixmap = QPixmap(72, 48)
    pixmap.fill(QColor('#ffffff' if code == 'pl' else '#012169'))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    if code == 'pl':
        painter.fillRect(0, 24, 72, 24, QColor('#dc143c'))
    else:
        for color, width in (('#ffffff', 10), ('#c8102e', 4)):
            painter.setPen(QPen(QColor(color), width))
            painter.drawLine(QPointF(0, 0), QPointF(72, 48))
            painter.drawLine(QPointF(0, 48), QPointF(72, 0))
        painter.fillRect(0, 16, 72, 16, QColor('#ffffff'))
        painter.fillRect(28, 0, 16, 48, QColor('#ffffff'))
        painter.fillRect(0, 19, 72, 10, QColor('#c8102e'))
        painter.fillRect(31, 0, 10, 48, QColor('#c8102e'))
    painter.end()
    return QIcon(pixmap)

def localized_number(value,digits=2):
    numeric=D(str(value))
    if numeric.is_nan():return tr('N/A')
    if not numeric.is_finite():return '-∞' if numeric<0 else '∞'
    text=f'{numeric:,.{digits}f}'
    return text.replace(',','\u202f').replace('.',',') if language()=='pl' else text

def parse_amount(text):
    cleaned=re.sub(r'[\s\u00a0\u202f]','',text)
    if language()=='pl' and ',' in cleaned:
        cleaned=cleaned.replace('.','').replace(',','.')
    elif language()=='en':
        cleaned=cleaned.replace(',','')
    return D(cleaned)

def money(value, short=True):
    if value is None:
        return tr('N/A')
    v = D(str(value))
    if not v.is_finite():
        return '∞'
    if short:
        for scale, suffix in [(D('1e12'), 't'), (D('1e9'), 'b'), (D('1e6'), 'm'), (D('1e3'), 'k')]:
            if abs(v) >= scale:
                return localized_number(v/scale,3)+suffix
    return localized_number(v)

def number(value):
    return tr('N/A') if value is None else localized_number(value)

def pct(value):
    if value is None:return tr('N/A')
    numeric=D(str(value))*100
    return ('+' if numeric>=0 else '')+localized_number(numeric,1)+'%'

def per_copy(blueprint, key):
    value = blueprint.get(key)
    copies = blueprint['quantity']
    return D(str(value)) / copies if value is not None and copies > 0 else None

def esc(value):
    return html.escape(str(value))

def sort_key(value):
    if isinstance(value, (tuple, list)):
        return (2, tuple((sort_key(v) for v in value)))
    if value is None or str(value) in (tr('N/A'), '—', ''):
        return (3, ())
    if isinstance(value, (int, float, D)):
        return (0, D(int(value)) if isinstance(value, bool) else D(str(value)))
    return (1, str(value).casefold())

class SortableItem(QTableWidgetItem):

    def __init__(self, text, value, source_row):
        super().__init__(str(text))
        self.sort_value = sort_key(value)
        self.setData(Qt.UserRole, source_row)

    def __lt__(self, other):
        return self.sort_value < other.sort_value

def selected_source_row(t):
    cell = t.item(t.currentRow(), 0)
    return cell.data(Qt.UserRole) if cell is not None else -1

def display_sort_value(value):
    """Fallback for score/count columns; money columns supply unrounded values."""
    if not isinstance(value, str):
        return value
    match = re.match('^([+-]?[\\d,]+(?:\\.\\d+)?)([kmbt]?)(?=$|[\\s%/])', value)
    if match:
        return D(match[1].replace(',', '')) * {'': 1, 'k': 10 ** 3, 'm': 10 ** 6, 'b': 10 ** 9, 't': 10 ** 12}[match[2]]
    return value

def table(headers, sortable=True):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels([tr(h) for h in headers])
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setAlternatingRowColors(True)
    t.verticalHeader().hide()
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setStretchLastSection(True)
    t.setMinimumHeight(130)
    if sortable:
        t.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
        t.setSortingEnabled(True)
        for i in range(len(headers)):
            t.horizontalHeaderItem(i).setToolTip(tr('Kliknij, aby sortować; ponowne kliknięcie odwraca kolejność. Kolumny z kilkoma wartościami: od lewej.'))
    return t

def fill_table(t, rows, sort_values=None):
    sorting = t.isSortingEnabled()
    t.setSortingEnabled(False)
    t.clearSelection()
    t.setCurrentCell(-1, -1)
    t.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            value = sort_values[i][j] if sort_values is not None else v if j == 0 else display_sort_value(v)
            cell = SortableItem(v, value, i)
            cell.setToolTip(str(v))
            if j > 0:
                cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if any((word in str(v) for word in [tr('PRICE UNRELIABLE'), tr('CANNOT BUILD'), tr('INCOMPLETE DATA'), tr('Uncertain / insufficient market history'), tr('STALE DATA'), tr('LOW')])):
                cell.setForeground(QColor('#f6bd70'))
            elif tr('BUILD — PROFITABLE') in str(v) or tr('BUILD — STRONG') in str(v) or tr('HIGH') in str(v):
                cell.setForeground(QColor('#54d8b3'))
            t.setItem(i, j, cell)
    t.setSortingEnabled(sorting)

class Worker(QThread):
    success = Signal(object)
    failure = Signal(str)
    progress = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            result = self.fn(self.progress.emit)
        except Exception as exc:
            logging.exception('Background operation failed')
            self.failure.emit(str(exc))
        else:
            self.success.emit(result)
STYLE = '\nQWidget { background:#0d0c0f; color:#e6e0e4; font-family:"Segoe UI"; font-size:10pt; }\nQMainWindow { background:#0d0c0f; }\nQLabel#title { font-size:25pt; font-weight:700; color:#fff0f2; }\nQLabel#sub { color:#aa929b; }\nQLabel#metric { font-size:24pt; font-weight:600; color:#f08a96; }\nQFrame#card { background:#191316; border:1px solid #3b242c; border-left:3px solid #a32b3e; border-radius:8px; }\nQFrame#card QLabel { background:transparent; }\nQPushButton { background:#26191f; border:1px solid #62303d; border-radius:5px; padding:8px 16px; }\nQPushButton:hover { background:#43202c; border-color:#bf485c; }\nQPushButton:pressed { background:#5c2635; }\nQPushButton:disabled { color:#715c65; background:#191418; border-color:#35252b; }\nQPushButton#primary { background:#b82e43; color:#ffffff; font-weight:700; border:1px solid #e14b61; }\nQPushButton#primary:hover { background:#d13a50; }\nQPushButton#primary:disabled { background:#51222c; color:#a68089; border-color:#63303c; }\nQPlainTextEdit,QLineEdit,QSpinBox,QDoubleSpinBox,QComboBox,QDateEdit,QTextBrowser { background:#100d11; border:1px solid #4b2b36; border-radius:4px; padding:5px; selection-background-color:#742d41; }\nQPlainTextEdit:focus,QLineEdit:focus,QSpinBox:focus,QDoubleSpinBox:focus,QComboBox:focus,QDateEdit:focus { border-color:#c94b60; }\nQTableWidget { background:#120e12; alternate-background-color:#1b1319; gridline-color:#37212b; border:1px solid #422633; }\nQTableWidget::item { padding:7px; }\nQTableWidget::item:selected { background:#512535; color:#fff0f4; }\nQHeaderView::section { background:#2a1720; color:#dcb5c1; border:none; padding:8px; font-weight:600; }\nQTabWidget::pane { border:0; }\nQTabBar::tab { background:#0d0c0f; color:#ac929d; padding:12px 22px; border-bottom:2px solid transparent; }\nQTabBar::tab:selected { color:#ff8395; border-bottom:2px solid #d73e58; }\nQTabBar::tab:hover { background:#23141c; }\nQScrollArea { border:none; }\nQScrollBar:vertical { background:#120e12; width:12px; margin:0; }\nQScrollBar:horizontal { background:#120e12; height:12px; margin:0; }\nQScrollBar::handle { background:#56303f; border-radius:4px; min-height:25px; min-width:25px; }\nQScrollBar::handle:hover { background:#9b3d55; }\nQScrollBar::add-line,QScrollBar::sub-line { width:0; height:0; }\nQScrollBar::add-page,QScrollBar::sub-page { background:transparent; }\nQToolTip { background:#321d28; color:#fff0f4; border:1px solid #a54c65; }\n'

class MainWindow(QMainWindow):

    def __init__(self, store, engine):
        super().__init__()
        self.store, self.engine = (store, engine)
        self.profile = store.profile(store.meta('active_profile', 'Default'))
        self.result = None
        self.params = {}
        self.worker = None
        self.sso = SSO()
        self.busy = False
        set_language(store.meta('language', 'pl'))
        self.qt_translator = None
        self.configure_qt_language()
        self.build_ui()
        self.profile_timer = QTimer(self)
        self.profile_timer.setSingleShot(True)
        self.profile_timer.setInterval(600)
        self.profile_timer.timeout.connect(self.persist_settings)
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(15 * 60 * 1000)
        self.sync_timer.timeout.connect(lambda: self.sso_action('refresh', automatic=True))
        self.sync_timer.start()
        QTimer.singleShot(100, self.startup)

    def configure_qt_language(self):
        app = QApplication.instance()
        if self.qt_translator:
            app.removeTranslator(self.qt_translator)
        locale=QLocale('pl_PL' if language() == 'pl' else 'en_GB')
        QLocale.setDefault(locale)
        self.setLocale(locale)
        self.qt_translator = QTranslator(self)
        if language() == 'pl':
            bundled = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent)) / 'assets' / 'qt'
            if self.qt_translator.load('qtbase_pl', str(bundled)) or self.qt_translator.load('qtbase_pl', QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
                app.installTranslator(self.qt_translator)

    def build_ui(self):
        self.setWindowTitle(tr('EVE • Loot & Jita Market Analyzer'))
        self.resize(1480, 950)
        self.setMinimumSize(1000, 700)
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 18, 24, 14)
        title = QLabel(tr('LOOT / JITA'))
        title.setObjectName('title')
        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch()
        self.language_buttons = {}
        for code, label in (('pl', 'Polski'), ('en', 'English')):
            button = QPushButton()
            button.setObjectName('language_' + code)
            button.setIcon(language_flag(code))
            button.setIconSize(QSize(36, 24))
            button.setFixedSize(54, 40)
            button.setCheckable(True)
            button.setChecked(language() == code)
            button.setToolTip(label)
            button.setAccessibleName(label)
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet('QPushButton { padding:5px; } QPushButton:checked { border:2px solid #f08a96; background:#512535; } QPushButton:focus { border:2px solid #ffffff; }')
            button.clicked.connect(lambda checked=False, selected=code: self.change_language(selected))
            self.language_buttons[code] = button
            header.addWidget(button)
        layout.addLayout(header)
        subtitle = QLabel(tr('EVE ONLINE     /     Jita IV – Moon 4 – Caldari Navy Assembly Plant     /     Local-first'))
        subtitle.setObjectName('sub')
        layout.addWidget(subtitle)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.analyze_page()
        self.watch_page()
        self.sessions_page()
        self.settings_page()
        self.data_page()
        self.status = QLabel(tr('Gotowy. Wklej loot, aby rozpocząć.'))
        self.status.setObjectName('sub')
        layout.addWidget(self.status)
        self.render_sessions()
        self.render_watch()
        self.load_settings()
        self.render_data()

    def change_language(self, selected):
        if selected == language():
            self.language_buttons[selected].setChecked(True)
            return
        pending_settings=self.profile_timer.isActive()
        self.profile_timer.stop()
        self.collect_settings()
        self.store.save_profile(self.profile)
        self.store.set_meta('language', selected)
        raw = self.raw.toPlainText()
        tab = self.tabs.currentIndex()
        size = self.size()
        filters = (self.site_filter.text(), self.date_from.date(), self.date_to.date())
        sorts = [(t.horizontalHeader().sortIndicatorSection(), t.horizontalHeader().sortIndicatorOrder()) for t in (self.regular, self.blueprints, self.watch, self.sessions_table, self.drops, self.sources)]
        set_language(selected)
        self.configure_qt_language()
        self.loading_settings = True
        self.build_ui()
        self.resize(size)
        self.raw.setPlainText(raw)
        self.site_filter.setText(filters[0])
        self.date_from.setDate(filters[1])
        self.date_to.setDate(filters[2])
        if self.result:
            self.render_result(self.result)
        for t, (column, order) in zip((self.regular, self.blueprints, self.watch, self.sessions_table, self.drops, self.sources), sorts):
            if column >= 0:
                t.sortItems(column, order)
        self.tabs.setCurrentIndex(tab)
        self.analyze_button.setEnabled(not self.busy)
        self.raw_changed()
        self.status.setText(tr('Language changed.'))
        if pending_settings and self.result:self.analyze()

    def show_progress(self, text):
        self.status.setText(message(text))

    def page(self, title):
        outer = QScrollArea()
        outer.setWidgetResizable(True)
        widget = QWidget()
        outer.setWidget(widget)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 15, 0, 10)
        layout.setSpacing(12)
        self.tabs.addTab(outer, title)
        return layout

    def button(self, text, fn, primary=False):
        b = QPushButton(text)
        b.clicked.connect(fn)
        if primary:
            b.setObjectName('primary')
        return b

    def analyze_page(self):
        l = self.page(tr('Analiza lootu'))
        l.addWidget(QLabel(tr('PASTE CARGO / LOOT   •   Angielskie nazwy przedmiotów, ilości i tabulatory z EVE')))
        self.raw = QPlainTextEdit()
        self.raw.setPlaceholderText(tr('Wklej skopiowaną zawartość cargo…\n\n12 x Triglavian Survey Database\nTritanium\t1000'))
        self.raw.setFixedHeight(135)
        l.addWidget(self.raw)
        self.raw.textChanged.connect(self.raw_changed)
        row = QHBoxLayout()
        self.analyze_button = self.button(tr('Analizuj rynek'), self.analyze, True)
        row.addWidget(self.analyze_button)
        row.addWidget(self.button(tr('Wklej ze schowka'), lambda: self.raw.setPlainText(QApplication.clipboard().text())))
        row.addWidget(self.button(tr('Wyczyść'), self.clear))
        self.save_button = self.button(tr('Zapisz sesję'), self.save_session)
        self.save_button.setEnabled(False)
        row.addWidget(self.save_button)
        row.addWidget(self.button(tr('Eksport JSON'), self.export))
        row.addStretch()
        l.addLayout(row)
        cards = QHBoxLayout()
        self.metrics = {}
        for key, label in [('instant_net', tr('INSTANT SELL · NET')), ('sell_net', tr('SELL ORDERS · NET')), ('realistic_net', tr('REALISTIC · NET')), ('blueprint_value', tr('BPC · BUILD VALUE'))]:
            frame = QFrame()
            frame.setObjectName('card')
            f = QVBoxLayout(frame)
            caption=QLabel(label);caption.setWordWrap(True);f.addWidget(caption)
            value = QLabel('—')
            value.setObjectName('metric')
            f.addWidget(value)
            f.addWidget(QLabel(tr('ISK  /  po podatkach')))
            cards.addWidget(frame)
            self.metrics[key] = value
        l.addLayout(cards)
        self.summary = QLabel(tr('ACTION SUMMARY   •   Wynik pojawi się po analizie.'))
        self.summary.setWordWrap(True)
        l.addWidget(self.summary)
        self.freshness = QLabel(tr('Historia cen: The Forge (cały region). Zlecenia sprzedaży: wyłącznie Jita 4-4.'))
        self.freshness.setWordWrap(True)
        self.freshness.setObjectName('sub')
        l.addWidget(self.freshness)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr('REGULAR ITEMS')))
        row.addStretch()
        row.addWidget(self.button(tr('Szczegóły przedmiotu'), self.item_details))
        row.addWidget(self.button(tr('+ Watchlist'), self.watch_selected))
        l.addLayout(row)
        self.regular = table([tr('Item'), tr('Qty'), tr('Instant net'), tr('Sell net'), tr('Realistic net'), tr('Spread %'), tr('7d / 30d vol/day'), tr('Jita stock'), tr('Days supply'), tr('Liquidity'), tr('Confidence'), tr('Trend 7d / 30d'), tr('ETA'), tr('Action')])
        self.regular.cellDoubleClicked.connect(lambda *_: self.item_details())
        l.addWidget(self.regular)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr('BLUEPRINT COPIES   •   Materiały zawsze kupowane w całości; bez zużywania lootu.')))
        row.addStretch()
        row.addWidget(self.button(tr('Runs / ME / TE / szczegóły'), self.blueprint_details))
        l.addLayout(row)
        self.blueprints = table([tr('Blueprint'), tr('Copies'), tr('Avg cost / 1 BPC'), tr('Avg profit / 1 BPC'), tr('Runs / ME / TE'), tr('Output'), tr('Materials'), tr('Job fee'), tr('Build cost'), tr('Output instant'), tr('Output sell'), tr('Realistic profit'), tr('ROI'), tr('Time / job'), tr('Liquidity / Confidence'), tr('Verdict')])
        for column in (2, 3):
            self.blueprints.horizontalHeaderItem(column).setToolTip(tr('Average per blueprint copy = stack total / Copies, using the configured runs per copy. Click to sort.'))
        self.blueprints.cellDoubleClicked.connect(lambda *_: self.blueprint_details())
        l.addWidget(self.blueprints)
        self.unresolved = QLabel('')
        self.unresolved.setWordWrap(True)
        l.addWidget(self.unresolved)

    def raw_changed(self):
        self.save_button.setEnabled(bool(self.result and self.raw.toPlainText() == self.result['raw'] and (not self.busy)))
        if self.result and self.raw.toPlainText() != self.result['raw']:
            self.status.setText(tr('Zmieniono tekst lootu — naciśnij Analizuj, aby odświeżyć wynik.'))

    def run(self, fn, done):
        if self.busy:
            return False
        self.busy = True
        self.analyze_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.worker = Worker(fn)
        self.worker.progress.connect(self.show_progress)
        self.worker.success.connect(done)
        self.worker.failure.connect(self.failed)
        self.worker.finished.connect(self.finished)
        self.worker.start()
        return True

    def failed(self, message):
        self.status.setText(tr('Błąd: ') + error_text(message))
        QMessageBox.warning(self, tr('Nie udało się ukończyć operacji'), error_text(message))

    def finished(self):
        self.busy = False
        self.analyze_button.setEnabled(True)
        self.raw_changed()
        self.render_data()
        if getattr(self, 'pending_reanalysis', False):
            self.pending_reanalysis = False
            QTimer.singleShot(0, self.analyze)

    def startup(self):
        if not self.store.meta('sde_build'):
            self.update_data()
        elif self.store.query('SELECT type_id FROM watchlist'):
            self.refresh_watch()

    def analyze(self):
        if not self.raw.toPlainText().strip():
            return
        if self.busy:
            self.pending_reanalysis = True
            return
        raw = self.raw.toPlainText()
        p = copy.deepcopy(self.profile)
        params = copy.deepcopy(self.params)
        self.status.setText(tr('Pobieranie i analiza rynku…'))
        self.run(lambda progress: self.engine.analyze(raw, p, params, progress), self.render_result)

    def clear(self):
        if self.busy:
            return
        self.raw.clear()
        self.result = None
        self.params = {}
        self.regular.setRowCount(0)
        self.blueprints.setRowCount(0)
        for label in self.metrics.values():
            label.setText('—')
        self.summary.setText(tr('ACTION SUMMARY   •   Wklej nowy loot.'))
        self.unresolved.clear()
        self.save_button.setEnabled(False)

    def render_result(self, r):
        self.result = r
        for key, label in self.metrics.items():
            missing = r['totals'].get(key.replace('_net', '_missing'), 0) if key != 'blueprint_value' else r['totals']['blueprint_missing']
            count = len(r['regular']) if key != 'blueprint_value' else len(r['blueprints'])
            label.setText(tr('N/A') if count and count == missing else money(r['totals'][key]) + (' *' if missing else ''))
            label.setToolTip(money(r['totals'][key], False) + tr(' ISK; missing positions: ') + str(missing))
        actions = '   |   '.join((f'{tr(key)}: {money(v)}' for key, v in r['actions'].items()))
        verdicts = {}
        for b in r['blueprints']:
            verdicts[b['verdict']] = verdicts.get(b['verdict'], 0) + 1
        bpc_actions = '   |   '.join((f'{tr(k)}: {n}' for k, n in verdicts.items()))
        self.summary.setText(tr('<b>ACTION SUMMARY</b>   {p0}<br>{p1}<br><b>Estimated realizable value: {p2} ISK</b> ', p0=f'{esc(actions)}', p1=f'{esc(bpc_actions)}', p2=f"{money(r['totals']['estimated_total'])}") + (tr(' · PARTIAL / niepełna wycena') if r['totals']['partial'] else '') + tr('<br>BPC build value to zysk z produkcji wymagający dodatkowego kapitału; nie cena sprzedaży kopii.'))
        self.summary.setText(self.summary.text() + tr('<br>Rozpoznano: {p0} typów przedmiotów · {p1} typów blueprintów', p0=f"{len(r['regular'])}", p1=f"{len(r['blueprints'])}") + (tr(' · <b style="color:#f6bd70">Nierozpoznane wiersze: {p0} — sprawdź sekcję UNRESOLVED pod tabelami.</b>', p0=f"{len(r['unresolved'])}") if r['unresolved'] else ''))
        sources = r['sources']
        timestamps = [s['fetched_at'] for s in sources if s['fetched_at']]
        oldest = datetime.fromtimestamp(min(timestamps)).strftime('%Y-%m-%d %H:%M:%S') if timestamps else tr('N/A')
        stale = any((s['stale'] for s in sources))
        self.freshness.setText(tr('{p0}Najstarsze użyte dane: {p1} · SDE {p2} · The Forge market history (region) · Jita 4-4 orders. Szczegóły źródeł: Dane.', p0=f"{('STALE DATA • ' if stale else '')}", p1=f'{oldest}', p2=f"{r['sde_build']}"))
        fill_table(self.regular, [[x['name'], x['quantity'], money(x['instant_net']) + (tr(' / {p0} unsold', p0=f"{x['unsold']}") if x['unsold'] else ''), money(x['sell_net']), money(x['realistic_net']), number(x['spread']), f"{number(x['avg_volume_7'])} / {number(x['avg_volume_30'])}", x['stock'], number(x['days_supply']), f"{x['liquidity']} {tr(x['liquidity_label'])}", f"{x['confidence']} {tr(x['confidence_label'])}", f"{pct(x['trend_7'])} / {pct(x['trend_30'])}", tr(x['eta']), tr(x['action'])] for x in r['regular']], [[x['name'], x['quantity'], x['instant_net'], x['sell_net'], x['realistic_net'], x['spread'], (x['avg_volume_7'], x['avg_volume_30']), x['stock'], x['days_supply'], x['liquidity'], x['confidence'], (x['trend_7'], x['trend_30']), x['stack_days'] if x['confidence'] >= 45 else None, tr(x['action'])] for x in r['regular']])
        fill_table(self.blueprints, [[x['name'], x['quantity'], money(per_copy(x, 'build_cost')), money(per_copy(x, 'realistic_profit')), f"{x['params'].get('runs', 1)} / {x['params'].get('me', 0)} / {x['params'].get('te', 0)}", ', '.join((f"{o['name']} ×{o['quantity']}" for o in x['outputs'])), money(x.get('material_cost')), money(x.get('job_fee')), money(x.get('build_cost')), money(x.get('output_instant_net')), money(x.get('output_sell_net')), money(x.get('realistic_profit')), pct(x.get('realistic_roi')), tr('{p0} h', p0=f"{number(D(str(x.get('time_seconds', 0))) / 3600)}"), f"{x.get('liquidity', tr('N/A'))} / {x.get('confidence', tr('N/A'))}", tr(x['verdict'])] for x in r['blueprints']], [[x['name'], x['quantity'], per_copy(x, 'build_cost'), per_copy(x, 'realistic_profit'), tuple((x['params'].get(k, 0) for k in ('runs', 'me', 'te'))), ', '.join((o['name'] for o in x['outputs'])), x.get('material_cost'), x.get('job_fee'), x.get('build_cost'), x.get('output_instant_net'), x.get('output_sell_net'), x.get('realistic_profit'), x.get('realistic_roi'), x.get('time_seconds'), (x.get('liquidity'), x.get('confidence')), tr(x['verdict'])] for x in r['blueprints']])
        self.unresolved.setText(tr('UNRESOLVED: ') + '<br>'.join((esc(u['line']) + ' → ' + esc(', '.join(u['suggestions']) or tr('brak dopasowania')) for u in r['unresolved'])) if r['unresolved'] else tr('Wszystkie niepuste pozycje rozpoznane.'))
        self.status.setText(tr('Analiza zakończona. Dwuklik w wiersz otwiera szczegóły.'))
        self.render_data()

    def chosen(self, t, key):
        row = selected_source_row(t)
        return self.result[key][row] if self.result and 0 <= row < len(self.result[key]) else None

    def detail_browser(self, title, content):
        d = QDialog(self)
        d.setWindowTitle(title)
        d.resize(950, 760)
        l = QVBoxLayout(d)
        b = QTextBrowser()
        b.setHtml(content)
        l.addWidget(b)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(d.reject)
        l.addWidget(close)
        d.exec()

    def item_html(self, x):
        pairs = [(tr('Quantity'), x['quantity']), (tr('Instant gross / net'), money(x['instant_gross'], False) + ' / ' + money(x['instant_net'], False)), (tr('Sell gross / net'), money(x['sell_gross'], False) + ' / ' + money(x['sell_net'], False)), (tr('Realistic net'), money(x['realistic_net'], False)), (tr('Sales tax / broker fee'), pct(x['sales_tax']) + ' / ' + pct(x['broker_fee'])), (tr('Unsold quantity'), x['unsold']), (tr('The Forge VWAP 7d / 30d'), money(x['vwap_7'], False) + ' / ' + money(x['vwap_30'], False)), (tr('Liquidity components'), self.score_text(x['liquidity_components'])), (tr('Confidence components'), self.score_text(x['confidence_components'])), (tr('Sell scenario weight'), pct(x['sell_weight'])), (tr('ETA'), tr(x['eta'])), (tr('Action'), tr(x['action']) + ' — ' + tr(x['reason']))]
        content = '<h1>' + esc(x['name']) + '</h1>' + self.html_pairs(pairs)
        for title, levels in [(tr('Executable buy fills'), x['buy_fills']), (tr('Jita 4-4 sell depth — top 10 price levels'), x['sell_depth'])]:
            content += '<h2>' + tr(title) + tr('</h2><table cellpadding="8"><tr><th>Quantity</th><th>Price ISK</th></tr>')
            content += ''.join((f"<tr><td>{r['quantity']}</td><td>{money(r['price'], False)}</td></tr>" for r in levels)) + '</table>'
        return content + tr('<h2>Data / warnings</h2>') + '<br>'.join((esc(message(w)) for w in x['warnings']))

    def score_text(self, components):
        names = {'stack': tr('Stack absorption'), 'supply': tr('Supply'), 'spread': tr('Spread'), 'regularity': tr('Trade regularity'), 'traded_days': tr('Traded days'), 'volume': tr('Volume'), 'depth': tr('Depth'), 'stability': tr('Price stability')}
        return ' · '.join((f'{tr(names[k])}: {number(v)}' for k, v in components.items()))

    def html_pairs(self, pairs):
        return '<table cellpadding="7">' + ''.join(('<tr><td><b>' + esc(tr(k)) + '</b></td><td>' + esc(v) + '</td></tr>' for k, v in pairs)) + '</table>'

    def item_details(self):
        x = self.chosen(self.regular, 'regular')
        if x:
            self.detail_browser(x['name'], self.item_html(x))

    def blueprint_details(self):
        x = self.chosen(self.blueprints, 'blueprints')
        if not x:
            return
        d = QDialog(self)
        d.setWindowTitle(x['name'])
        d.resize(1050, 820)
        l = QVBoxLayout(d)
        f = QFormLayout()
        controls = {}
        for key, label, lo, hi in [('remaining_runs', tr('Remaining runs per copy'), 1, 1000000), ('runs', tr('Runs per copy / job'), 1, 1000000), ('me', tr('ME'), 0, 10), ('te', tr('TE'), 0, 20)]:
            w = QSpinBox()
            w.setRange(lo, hi)
            w.setValue(x['params'].get(key, 1 if 'runs' in key else 0))
            controls[key] = w
            f.addRow(tr(label), w)
        l.addLayout(f)
        l.addWidget(QLabel(tr('Te same parametry dla każdej kopii w stosie. Pozostałe runs wprowadź z informacji o BPC w grze.')))
        b = QTextBrowser()
        l.addWidget(b)
        content = self.blueprint_html(x)
        b.setHtml(content)
        row = QHBoxLayout()

        def recalc():
            p = {k: w.value() for k, w in controls.items()}
            if p['runs'] > p['remaining_runs']:
                QMessageBox.warning(d, tr('Runs'), tr('Runs nie mogą przekraczać remaining runs.'))
                return
            self.params[str(x['type_id'])] = p
            d.accept()
            self.analyze()
        row.addWidget(self.button(tr('Zastosuj i przelicz'), recalc, True))
        for o in x['outputs']:
            row.addWidget(self.button(tr('+ Watch ') + o['name'], lambda checked=False, o=o: self.add_watch(o)))
        row.addWidget(self.button(tr('Zamknij'), d.reject))
        l.addLayout(row)
        d.exec()

    def blueprint_html(self,x):
        content = '<h1>' + esc(tr(x['verdict'])) + '</h1>'
        content += tr('<p>{p0} copies · {p1} runs per copy. Per 1 BPC = stack total / copies. ', p0=f"{x['quantity']}", p1=f"{x['params'].get('runs', 1)}")
        content += tr('These are averages at the analyzed stack depth, not a separate market quote for one copy.</p>')
        content += tr('<table cellpadding="7"><tr><th>Value (ISK)</th><th>Stack total</th><th>Average / 1 BPC</th></tr>')
        for key, label in [('material_cost', tr('Materials')), ('eiv', tr('EIV')), ('job_fee', tr('Job fee')), ('build_cost', tr('Build cost')), ('output_instant_net', tr('Output instant net')), ('output_sell_net', tr('Output sell net')), ('output_realistic_net', tr('Output realistic net')), ('instant_profit', tr('Instant profit')), ('sell_profit', tr('Sell profit')), ('realistic_profit', tr('Realistic profit')), ('build_value', tr('Build value'))]:
            content += f'<tr><td>{tr(label)}</td><td>{money(x.get(key), False)}</td><td>{money(per_copy(x, key), False)}</td></tr>'
        content += '</table>'
        content += self.html_pairs([(tr('ROI instant / sell / realistic'), ' / '.join((pct(x.get(k + '_roi')) for k in ['instant', 'sell', 'realistic']))), (tr('Jita manufacturing SCI'), pct(x.get('sci'))), (tr('Concurrent job slots'), x.get('max_jobs', tr('N/A'))), (tr('Missing skills'), ', '.join((f"{s['name']}: {s['current']}/{s['required']}" for s in x.get('missing_skills', []))) or tr('None')), (tr('Missing adjusted prices'), x.get('missing_adjusted', []))])
        content += tr('<h2>Materials — full external purchase</h2><table cellpadding="7"><tr><th>Item</th><th>Qty</th><th>Cost ISK</th><th>Missing</th></tr>')
        content += ''.join((f"<tr><td>{esc(m['name'])}</td><td>{m['quantity']}</td><td>{money(m.get('cost'), False)}</td><td>{m.get('remaining', 0)}</td></tr>" for m in x['materials'])) + '</table>'
        content += '<p>' + '<br>'.join((esc(message(w)) for w in x['warnings'])) + '</p>'
        for o in x['outputs']:
            content += self.item_html(o)
        return content

    def watch_page(self):
        l = self.page(tr('Watchlist'))
        l.addWidget(QLabel(tr('OBSERWOWANE   •   Targety i alerty przy odświeżeniu, ceny jednostkowe.')))
        row = QHBoxLayout()
        row.addWidget(self.button(tr('+ Dodaj przedmiot'), lambda: self.add_watch()))
        row.addWidget(self.button(tr('Odśwież'), self.refresh_watch))
        row.addWidget(self.button(tr('Edytuj target'), self.edit_watch))
        row.addWidget(self.button(tr('Usuń zaznaczony'), self.remove_watch))
        row.addStretch()
        l.addLayout(row)
        self.watch = table([tr('Item'), tr('Mode'), tr('Target'), tr('Direction'), tr('Previous'), tr('Current'), tr('Delta'), tr('Liquidity'), tr('Confidence'), tr('Alert / data')])
        l.addWidget(self.watch)
        l.addStretch()

    def watch_selected(self):
        x = self.chosen(self.regular, 'regular')
        if x:
            self.add_watch(x)

    def add_watch(self, item=None, existing=None):
        d = QDialog(self)
        d.setWindowTitle(tr('Watchlist target'))
        f = QFormLayout(d)
        name = QLineEdit(existing['name'] if existing else item['name'] if item else '')
        name.setReadOnly(bool(item or existing))
        f.addRow(tr('English item name'), name)
        mode = QComboBox()
        for key in WATCH_MODES:
            mode.addItem(tr(key), key)
        f.addRow(tr('Mode (1 unit)'), mode)
        target = QLineEdit()
        target.setPlaceholderText(tr('Opcjonalnie, ISK'))
        f.addRow(tr('Target'), target)
        direction = QComboBox()
        direction.addItems(['>=', '<='])
        f.addRow(tr('Alert when'), direction)
        if existing:
            mode.setCurrentIndex(mode.findData(existing['mode']))
            target.setText((existing['target'] or '').replace('.', ',') if language()=='pl' else existing['target'] or '')
            direction.setCurrentText(existing['direction'])
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        f.addRow(buttons)
        buttons.rejected.connect(d.reject)

        def save():
            match = self.store.index().get(name.text().strip().casefold())
            if not match or match['category'] == 9:
                QMessageBox.warning(d, tr('Item'), tr('Podaj nazwę przedmiotu rynkowego z SDE (dla BPC wybierz produkt).'))
                return
            try:
                v = parse_amount(target.text()) if target.text().strip() else None
                if v is not None and (not v.is_finite() or v < 0):
                    raise ValueError()
            except Exception:
                QMessageBox.warning(d, tr('Target'), tr('Podaj nieujemną kwotę ISK.'))
                return
            self.store.execute('INSERT INTO watchlist(type_id,name,mode,target,direction) VALUES(?,?,?,?,?) ON CONFLICT(type_id) DO UPDATE SET mode=excluded.mode,target=excluded.target,direction=excluded.direction,last_value=NULL,current_value=NULL,snapshot=NULL', (match['type_id'], match['name'], mode.currentData(), str(v) if v is not None else None, direction.currentText()))
            d.accept()
            self.render_watch()
        buttons.accepted.connect(save)
        d.exec()

    def edit_watch(self):
        rows = self.store.query('SELECT * FROM watchlist ORDER BY name')
        i = selected_source_row(self.watch)
        if 0 <= i < len(rows):
            self.add_watch(existing=rows[i])

    def remove_watch(self):
        rows = self.store.query('SELECT * FROM watchlist ORDER BY name')
        i = selected_source_row(self.watch)
        if 0 <= i < len(rows):
            self.store.execute('DELETE FROM watchlist WHERE type_id=?', (rows[i]['type_id'],))
            self.render_watch()

    def refresh_watch(self):
        p = copy.deepcopy(self.profile)
        self.run(lambda progress: self.engine.refresh_watchlist(p, progress), lambda _: self.render_watch())

    def render_watch(self):
        rows = []
        keys = []
        for x in self.store.query('SELECT * FROM watchlist ORDER BY name'):
            current = D(x['current_value']) if x['current_value'] is not None else None
            last = D(x['last_value']) if x['last_value'] is not None else None
            target = D(x['target']) if x['target'] is not None else None
            snapshot = json.loads(x['snapshot']) if x['snapshot'] else {}
            alert = (current >= target if x['direction'] == '>=' else current <= target) if current is not None and target is not None else False
            stale = any((s['stale'] for s in snapshot.get('sources', [])))
            rows.append([x['name'], tr(x['mode']), money(target), x['direction'], money(last), money(current), pct(current / last - 1) if current is not None and last else tr('N/A'), snapshot.get('liquidity', '—'), snapshot.get('confidence', '—'), (tr('TARGET REACHED') if alert else '—') + (tr(' / STALE DATA') if stale else '')])
            keys.append([x['name'], x['mode'], target, x['direction'], last, current, current / last - 1 if current is not None and last else None, snapshot.get('liquidity'), snapshot.get('confidence'), (alert, stale)])
        fill_table(self.watch, rows, keys)

    def save_session(self):
        if not self.result:
            return
        d = QDialog(self)
        d.setWindowTitle(tr('Zapisz snapshot sesji'))
        f = QFormLayout(d)
        name = QLineEdit('World Ark #' + str(len(self.store.sessions()) + 1))
        site = QLineEdit('World Ark Assault Flashpoint')
        duration = QDoubleSpinBox()
        duration.setRange(0, 100000)
        duration.setSpecialValueText(tr('Nie podano'))
        pilots = QSpinBox()
        pilots.setRange(0, 10000)
        pilots.setSpecialValueText(tr('Nie podano'))
        for label, w in [(tr('Nazwa'), name), (tr('Site type'), site), (tr('Czas (minuty)'), duration), (tr('Piloci'), pilots)]:
            f.addRow(label, w)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        f.addRow(buttons)
        buttons.accepted.connect(d.accept)
        buttons.rejected.connect(d.reject)
        if d.exec() == QDialog.Accepted:
            self.store.save_session(name.text(), site.text(), duration.value() or None, pilots.value() or None, self.result['raw'], self.result)
            self.render_sessions()
            self.status.setText(tr('Zapisano snapshot sesji w lokalnej bazie.'))

    def sessions_page(self):
        l = self.page(tr('Sesje i statystyki'))
        row = QHBoxLayout()
        row.addWidget(QLabel(tr('Site filter')))
        self.site_filter = QLineEdit()
        self.site_filter.setPlaceholderText(tr('Wszystkie site’y'))
        self.site_filter.textChanged.connect(lambda _: self.render_sessions())
        row.addWidget(self.site_filter)
        self.date_from = QDateEdit(QDate(2020, 1, 1))
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_from.setCalendarPopup(True)
        self.date_to.setCalendarPopup(True)
        for w in [self.date_from, self.date_to]:
            w.dateChanged.connect(lambda _: self.render_sessions())
            row.addWidget(w)
        row.addWidget(self.button(tr('Otwórz snapshot'), self.session_details))
        l.addLayout(row)
        self.session_stats = QLabel()
        self.session_stats.setWordWrap(True)
        l.addWidget(self.session_stats)
        self.sessions_table = table([tr('Session'), tr('Site'), tr('Local time'), tr('Minutes'), tr('Pilots'), tr('Instant'), tr('Sell'), tr('Realistic'), tr('BPC build'), 'ISK/h', tr('ISK/pilot'), tr('ISK/pilot/h'), tr('Data')])
        l.addWidget(self.sessions_table)
        self.sessions_table.cellDoubleClicked.connect(lambda *_: self.session_details())
        l.addWidget(QLabel(tr('OBSERVED DROPS   •   Częstość w zapisanych sesjach; nie oficjalny drop chance.')))
        self.drops = table([tr('Item'), tr('Category'), tr('Observed sessions'), tr('Frequency'), tr('Total qty'), tr('Avg qty / drop'), tr('Historical value')])
        l.addWidget(self.drops)

    def render_sessions(self):
        if not hasattr(self, 'drops'):
            return
        rows = [x for x in self.store.sessions() if self.site_filter.text().casefold() in x['site'].casefold() and self.date_from.date().toString('yyyy-MM-dd') <= datetime.fromisoformat(x['timestamp']).astimezone().date().isoformat() <= self.date_to.date().toString('yyyy-MM-dd')]
        self.filtered_sessions = rows
        values = []
        out = []
        keys = []
        drops = {}
        regular_total = D(0)
        blueprint_total = D(0)
        timed_value = D(0)
        total_minutes = D(0)
        for x in rows:
            t = x['snapshot']['totals']
            value = D(t['estimated_total'])
            values.append(value)
            duration = D(x['duration']) if x['duration'] else None
            pilots = x['pilots']
            rate = value * 60 / duration if duration else None
            if duration:
                timed_value += value
                total_minutes += duration
            regular_total += D(t['realistic_net'])
            blueprint_total += D(t['blueprint_value'])
            out.append([x['name'], x['site'], datetime.fromisoformat(x['timestamp']).astimezone().strftime('%Y-%m-%d %H:%M'), duration or '—', pilots or '—', money(t['instant_net']), money(t['sell_net']), money(t['realistic_net']), money(t['blueprint_value']), money(rate), money(value / pilots) if pilots else tr('N/A'), money(rate / pilots) if rate is not None and pilots else tr('N/A'), tr('PARTIAL') if t['partial'] else tr('Complete')])
            keys.append([x['name'], x['site'], datetime.fromisoformat(x['timestamp']).timestamp(), duration, pilots, *(D(t[k]) for k in ('instant_net', 'sell_net', 'realistic_net', 'blueprint_value')), rate, value / pilots if pilots else None, rate / pilots if rate is not None and pilots else None, t['partial']])
            for category in ['regular', 'blueprints']:
                for item in x['snapshot'][category]:
                    key = item['type_id']
                    entry = drops.setdefault(key, dict(name=item['name'], category=category, count=0, quantity=0, value=D(0), missing=0))
                    entry['count'] += 1
                    entry['quantity'] += item['quantity']
                    v = item.get('realistic_net' if category == 'regular' else 'build_value')
                    entry['value'] += D(v) if v is not None else 0
                    entry['missing'] += v is None
        fill_table(self.sessions_table, out, keys)
        total = sum(values, D(0))
        n = len(rows)
        self.session_stats.setText(tr('<b>{p0} zapisanych site’ów</b> · Total {p1} · Średnia {p2} · Mediana {p3} · Best {p4} · Worst {p5}<br>Regular {p6} / BPC {p7} · ISK/h (tylko sesje z czasem): {p8}. Sumy częściowe pozostają oznaczone w tabeli.', p0=f'{n}', p1=f'{money(total)}', p2=f"{(money(total / n) if n else '—')}", p3=f"{(money(median(values)) if n else '—')}", p4=f"{(money(max(values)) if n else '—')}", p5=f"{(money(min(values)) if n else '—')}", p6=f'{money(regular_total)}', p7=f'{money(blueprint_total)}', p8=f"{(money(timed_value * 60 / total_minutes) if total_minutes else tr('N/A'))}"))
        sorted_drops = sorted(drops.values(), key=lambda r: r['value'], reverse=True)
        fill_table(self.drops, [[r['name'], tr('Regular items' if r['category'] == 'regular' else 'Blueprint copies'), f"{r['count']}/{n}", pct(D(r['count']) / n) if n else '—', r['quantity'], number(D(r['quantity']) / r['count']), money(r['value']) + (' *' if r['missing'] else '')] for r in sorted_drops], [[r['name'], r['category'], r['count'], D(r['count']) / n if n else None, r['quantity'], D(r['quantity']) / r['count'], r['value']] for r in sorted_drops])

    def session_details(self):
        i = selected_source_row(self.sessions_table)
        if 0 <= i < len(self.filtered_sessions):
            x = self.filtered_sessions[i]
            self.detail_browser(x['name'],self.snapshot_html(x))

    def snapshot_html(self,session):
        snapshot=session['snapshot'];totals=snapshot['totals']
        content='<h1>'+esc(session['name'])+'</h1><p>'+esc(tr('Immutable saved snapshot'))+'</p>'
        content+=self.html_pairs([(tr('Site'),session['site']),
            (tr('Local time'),datetime.fromisoformat(session['timestamp']).astimezone().strftime('%Y-%m-%d %H:%M:%S')),
            (tr('Minutes'),session['duration'] or tr('Nie podano')),(tr('Pilots'),session['pilots'] or tr('Nie podano')),
            (tr('Instant net'),money(totals['instant_net'],False)),(tr('Sell net'),money(totals['sell_net'],False)),
            (tr('Realistic net'),money(totals['realistic_net'],False)),(tr('Build value'),money(totals['blueprint_value'],False)),
            (tr('Total estimated value'),money(totals['estimated_total'],False)),
            (tr('Data'),tr('PARTIAL') if totals['partial'] else tr('Complete'))])
        p=snapshot.get('profile',{})
        profile_pairs=[(tr('Nazwa'),p.get('name',''))]
        for key,label in [('accounting','Accounting'),('broker','Broker Relations'),('advanced_broker','Advanced Broker Relations'),
                          ('industry','Industry'),('advanced_industry','Advanced Industry'),
                          ('faction','Caldari State — RAW / UNMODIFIED'),('corporation','Caldari Navy — RAW / UNMODIFIED'),('clone','Clone')]:
            profile_pairs.append((tr(label),p.get(key,tr('N/A'))))
        content+='<h2>'+esc(tr('Profile snapshot'))+'</h2>'+self.html_pairs(profile_pairs)
        for item in snapshot['regular']:content+=self.item_html(item)
        for blueprint in snapshot['blueprints']:
            content+='<h1>'+esc(blueprint['name'])+'</h1>'+self.blueprint_html(blueprint)
        if snapshot.get('unresolved'):
            content+='<h2>'+esc(tr('Unresolved lines'))+'</h2><pre>'+esc('\n'.join(u['line'] for u in snapshot['unresolved']))+'</pre>'
        content+='<h2>'+esc(tr('Original loot input'))+'</h2><pre>'+esc(session['raw'])+'</pre>'
        return content

    def settings_page(self):
        l = self.page(tr('Profil i ustawienia'))
        f = QFormLayout()
        self.fields = {}

        self.profile_picker = QComboBox()
        self.profile_picker.setEditable(True)
        f.addRow(tr('Profil (wybierz lub wpisz nową nazwę)'), self.profile_picker)
        for key, label in [('accounting', 'Accounting'), ('broker', 'Broker Relations'), ('advanced_broker', 'Advanced Broker Relations'), ('industry', 'Industry'), ('advanced_industry', 'Advanced Industry'), ('mass_production', 'Mass Production'), ('advanced_mass_production', 'Advanced Mass Production')]:
            w = QSpinBox()
            w.setRange(0, 5)
            self.fields[key] = w
            f.addRow(label, w)
        for key, label, lo, hi in [('faction', tr('Caldari State — RAW / UNMODIFIED'), -10, 10), ('corporation', tr('Caldari Navy — RAW / UNMODIFIED'), -10, 10), ('price_offset', tr('Sell price offset (%)'), -99, 100), ('list_margin', tr('Min. LIST ON MARKET premium (%)'), 0, 100)]:
            w = QDoubleSpinBox()
            w.setDecimals(3)
            w.setRange(lo, hi)
            self.fields[key] = w
            f.addRow(label, w)
        clone = QComboBox()
        clone.addItems(['Omega', 'Alpha'])
        self.fields['clone'] = clone
        f.addRow(tr('Clone'), clone)
        material = QComboBox()
        material.addItem(tr('Instant Jita Sell — zakup z sell depth'), 'instant')
        material.addItem(tr('Jita Buy Orders — estymacja, broker fee'), 'buy')
        self.fields['material_mode'] = material
        f.addRow(tr('Zakup materiałów'), material)
        self.fees = QLabel()
        f.addRow(tr('Opłaty w Jita NPC station'), self.fees)
        l.addLayout(f)
        row = QHBoxLayout()
        row.addWidget(self.button(tr('Wczytaj profil'), self.switch_profile))
        row.addWidget(self.button(tr('Zapisz / utwórz profil'), self.persist_settings))
        row.addWidget(self.button(tr('Dodatkowe skille produkcyjne'), self.edit_skills))
        row.addStretch()
        l.addLayout(row)
        l.addWidget(QLabel(tr('Zmiany skilli i standingów są zapisywane automatycznie i przeliczają aktualny loot.')))
        l.addWidget(QLabel(tr('EVE SSO (opcjonalne)   •   Tryb ręczny działa bez logowania.')))
        self.client_id = QLineEdit()
        self.client_id.setPlaceholderText(tr('Client ID aplikacji EVE Developer (Native / PKCE)'))
        l.addWidget(self.client_id)
        l.addWidget(QLabel(tr('Zarejestruj callback: ') + REDIRECT + tr('\nScopes: esi-skills.read_skills.v1, esi-characters.read_standings.v1')))
        self.manual_override = QCheckBox(tr('Manual override — zachowaj ręczne skille i standingi przy synchronizacji'))
        l.addWidget(self.manual_override)
        row = QHBoxLayout()
        row.addWidget(self.button(tr('Połącz postać'), lambda: self.sso_action('connect')))
        row.addWidget(self.button(tr('Synchronizuj'), lambda: self.sso_action('refresh')))
        row.addWidget(self.button(tr('Rozłącz'), lambda: self.sso_action('disconnect')))
        row.addStretch()
        l.addLayout(row)
        self.sso_status = QLabel(tr('Manual profile'))
        l.addWidget(self.sso_status)
        l.addStretch()
        for w in self.fields.values():
            (w.currentIndexChanged if isinstance(w, QComboBox) else w.valueChanged).connect(self.schedule_settings)
        self.manual_override.toggled.connect(self.schedule_settings)
        self.client_id.editingFinished.connect(self.schedule_settings)

    def schedule_settings(self, *_):
        if hasattr(self, 'profile_timer') and (not getattr(self, 'loading_settings', False)):
            self.profile_timer.start()

    def load_settings(self):
        self.loading_settings = True
        self.profile_picker.clear()
        self.profile_picker.addItems([r['name'] for r in self.store.query('SELECT name FROM profiles ORDER BY name')] or ['Default'])
        self.profile_picker.setCurrentText(self.profile['name'])
        for key, w in self.fields.items():
            value = self.profile.get(key, 5 if key == 'list_margin' else 'Omega' if key == 'clone' else 'instant' if key == 'material_mode' else 0)
            if key == 'material_mode':
                w.setCurrentIndex(max(0, w.findData(value)))
            elif isinstance(w, QComboBox):
                w.setCurrentText(str(value))
            else:
                w.setValue(float(value) if isinstance(w, QDoubleSpinBox) else int(value))
        self.client_id.setText(self.profile.get('client_id', ''))
        self.manual_override.setChecked(self.profile.get('manual_override', False))
        self.sso_status.setText(tr('Connected: ') + self.profile['character_name'] if self.profile.get('character_name') else tr('Manual profile'))
        self.fees.setText(tr('Sales tax {p0}   /   Broker fee {p1}', p0=f'{pct(tax(self.profile))}', p1=f'{pct(broker(self.profile))}'))
        self.loading_settings = False

    def persist_settings(self):
        self.collect_settings()
        self.store.save_profile(self.profile)
        self.fees.setText(tr('Sales tax {p0}   /   Broker fee {p1}', p0=f'{pct(tax(self.profile))}', p1=f'{pct(broker(self.profile))}'))
        if self.result:
            self.analyze()

    def collect_settings(self):
        name = self.profile_picker.currentText().strip() or 'Default'
        if name != self.profile['name']:
            self.profile.pop('character_id', None)
            self.profile.pop('character_name', None)
        self.profile['name'] = name
        for key, w in self.fields.items():
            self.profile[key] = w.currentData() if key == 'material_mode' else w.currentText() if isinstance(w, QComboBox) else w.value()
        self.profile['client_id'] = self.client_id.text().strip()
        self.profile['manual_override'] = self.manual_override.isChecked()
        for key, type_id in SKILL_IDS.items():
            self.profile.setdefault('skills', {})[str(type_id)] = int(self.profile.get(key, 0))

    def switch_profile(self):
        self.profile_timer.stop()
        self.profile = self.store.profile(self.profile_picker.currentText().strip() or 'Default')
        self.store.set_meta('active_profile', self.profile['name'])
        self.load_settings()
        if self.result:
            self.analyze()

    def edit_skills(self):
        d = QDialog(self)
        d.setWindowTitle(tr('Specialized manufacturing skills'))
        d.resize(650, 650)
        l = QVBoxLayout(d)
        search = QLineEdit()
        search.setPlaceholderText(tr('Filtruj skille…'))
        l.addWidget(search)
        t = table([tr('Skill'), tr('Level')], sortable=False)
        l.addWidget(t)
        controls = {}
        skills = self.store.query('SELECT type_id,name FROM item_types WHERE category=16 AND published=1 ORDER BY name')
        t.setRowCount(len(skills))
        for i, s in enumerate(skills):
            t.setItem(i, 0, QTableWidgetItem(s['name']))
            w = QSpinBox()
            w.setRange(0, 5)
            w.setValue(int(self.profile.get('skills', {}).get(str(s['type_id']), 0)))
            t.setCellWidget(i, 1, w)
            controls[str(s['type_id'])] = w
        search.textChanged.connect(lambda text: [t.setRowHidden(i, text.casefold() not in s['name'].casefold()) for i, s in enumerate(skills)])
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(d.accept)
        buttons.rejected.connect(d.reject)
        l.addWidget(buttons)
        if d.exec() == QDialog.Accepted:
            self.profile['skills'] = {k: w.value() for k, w in controls.items()}
            for name, type_id in SKILL_IDS.items():
                self.profile[name] = self.profile['skills'].get(str(type_id), 0)
            self.store.save_profile(self.profile)
            self.load_settings()
            if self.result:
                self.analyze()

    def sso_action(self, action, automatic=False):
        if self.busy or (automatic and (not self.profile.get('character_id'))):
            return
        self.profile_timer.stop()
        self.profile['client_id'] = self.client_id.text().strip()
        self.profile['manual_override'] = self.manual_override.isChecked()
        p = copy.deepcopy(self.profile)

        def task(progress):
            if action == 'connect':
                return self.sso.connect(p, progress)
            if action == 'disconnect':
                return self.sso.disconnect(p)
            return self.sso.sync(p)

        def done(p):
            self.profile = p
            self.store.save_profile(p)
            self.load_settings()
            self.status.setText(tr('Profil postaci zaktualizowany.'))
            if self.result:
                self.pending_reanalysis = True
        self.run(task, done)

    def data_page(self):
        l = self.page(tr('Dane'))
        self.data_status = QLabel()
        self.data_status.setWordWrap(True)
        l.addWidget(self.data_status)
        row = QHBoxLayout()
        row.addWidget(self.button(tr('Sprawdź / pobierz SDE'), self.update_data))
        row.addWidget(self.button(tr('Backup bazy SQLite'), self.backup))
        row.addWidget(self.button(tr('Otwórz folder danych'), lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data_dir())))))
        row.addStretch()
        l.addLayout(row)
        self.sources = table([tr('Endpoint'), tr('Fetched (local)'), tr('Age'), tr('State'), tr('Error')])
        l.addWidget(self.sources)
        l.addWidget(QLabel(tr('ESI cache respektuje Expires i ETag. Refresh korzysta z cache do jego wygaśnięcia.\nRealistic i ETA to heurystyki; źródłem wolumenu jest The Forge, nie dokładny obrót stacji Jita.')))
        l.addStretch()

    def render_data(self):
        self.data_status.setText(tr('SDE build: {p0}\nBaza: {p1}\nBaseline mechanik: specyfikacja v1.0 / 2026-09-09 · Jita manufacturing · NPC facility 0.25% + SCC 4% (+ Alpha 0.25%).', p0=f"{self.store.meta('sde_build', tr('brak — trwa przygotowanie'))}", p1=f'{self.store.path}'))
        sources = list(self.engine.esi.status.values())
        now = datetime.now().timestamp()
        fill_table(self.sources, [[s['source'], datetime.fromtimestamp(s['fetched_at']).strftime('%Y-%m-%d %H:%M:%S') if s['fetched_at'] else tr('N/A'), tr('{p0} s', p0=f"{int(now - s['fetched_at'])}") if s['fetched_at'] else tr('N/A'), tr('STALE DATA') if s['stale'] else tr('Fresh / cache'), error_text(s['error']) if s.get('error') else '—'] for s in sources])

    def update_data(self):
        self.run(lambda progress: update_sde(self.store, progress), lambda build: self.status.setText(tr('SDE gotowe: ') + build))

    def backup(self):
        path, _ = QFileDialog.getSaveFileName(self, tr('Backup bazy'), 'eve-loot-backup.sqlite3', 'SQLite (*.sqlite3)', options=QFileDialog.DontUseNativeDialog)
        if path:
            self.store.backup(path)
            self.status.setText(tr('Backup zapisany: ') + path)

    def export(self):
        if not self.result:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr('Eksport analizy'), 'eve-loot-analysis.json', 'JSON (*.json)', options=QFileDialog.DontUseNativeDialog)
        if path:
            Path(path).write_text(json.dumps(json.loads(dumps(self.result)), ensure_ascii=False, indent=2), encoding='utf-8')

    def closeEvent(self, event):
        if self.busy:
            self.status.setText(tr('Trwa operacja. Poczekaj na jej zakończenie przed zamknięciem.'))
            event.ignore()
            return
        self.profile_timer.stop()
        QApplication.instance().removeTranslator(self.qt_translator)
        self.engine.esi.close()
        event.accept()
