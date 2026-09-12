import ast
import copy
import re
import string
import threading
from decimal import Decimal as D
from pathlib import Path

from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QApplication,QDialogButtonBox,QComboBox,QTextBrowser
from app.i18n import tr,message,error_text,set_language,language
from app.translations import CATALOG
from app.storage import Store
from app.engine import Engine
from app.ui import MainWindow,money,pct,parse_amount
from tests.test_integration import populate,FakeEsi
from tests.test_ui import wait_until

def test_catalog_complete_and_placeholders_preserved():
    for source,entry in CATALOG.items():
        fields=lambda s:{f for _,f,_,_ in string.Formatter().parse(s) if f is not None}
        assert set(entry)=={'pl','en'}
        assert fields(source)==fields(entry['pl'])==fields(entry['en']),source
        assert not re.search('[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]',entry['en']),source
    tree=ast.parse(Path('app/ui.py').read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='tr' and node.args and isinstance(node.args[0],ast.Constant):
            assert node.args[0].value in CATALOG,node.args[0].value

def test_numbers_and_domain_messages():
    try:
        set_language('pl')
        assert money(D('1234.56'),False)=='1\u202f234,56'
        assert pct(D('.051'))=='+5,1%'
        assert parse_amount('1 234,56')==D('1234.56')
        assert parse_amount('1234.56')==D('1234.56')
        assert message('Analyzing Damage Control II')=='Analizowanie: Damage Control II'
        assert message('Insufficient buy depth: 17 unsold')=='Za mała ilość w zleceniach kupna: 17 szt. niesprzedanych'
        assert message('Blueprint Small Armor Repairer I Blueprint')=='Schemat: Small Armor Repairer I Blueprint'
        assert 'HTTP 503' in message("Order book unavailable: Server error '503 Service Unavailable' for url 'https://esi.evetech.net'")
        assert error_text('access_denied')==tr('SSO access denied. Please authorize the requested scopes.')
        set_language('en')
        assert money(D('1234.56'),False)=='1,234.56'
        assert pct(D('.051'))=='+5.1%'
        assert parse_amount('1,234.56')==D('1234.56')
        assert 'Sync now' in message('SSO: czas tokenu wyprzedza zegar komputera o ponad 60 sekund. W Windows otwórz Ustawienia → Czas i język → Data i godzina → Synchronizuj teraz, a następnie ponownie połącz postać.')
    finally:set_language('pl')

def test_language_switch_preserves_analysis_profiles_and_watch_modes(tmp_path):
    app=QApplication.instance() or QApplication([])
    store=Store(tmp_path/'locale.db');populate(store);api=FakeEsi();api.close=lambda:None
    w=MainWindow(store,Engine(store,api));w.show()
    try:
        startup_done=[];QTimer.singleShot(150,lambda:startup_done.append(True));wait_until(app,lambda:bool(startup_done))
        w.raw.setPlainText('Item 1\t10\nItem 6\t2\nUnknown item')
        w.analyze();wait_until(app,lambda:w.result is not None and not w.busy)
        store.save_session('My session','World Ark',30,2,w.result['raw'],w.result)
        store.execute('INSERT INTO watchlist(type_id,name,mode,target,direction) VALUES(?,?,?,?,?)',(1,'Item 1','Sell price','90','>='))
        w.render_watch();w.render_sessions()
        original=copy.deepcopy(w.result);calls=copy.deepcopy(api.calls)
        w.blueprints.sortItems(2,Qt.DescendingOrder)
        assert w.tabs.tabText(0)=='Analiza łupów'
        assert w.regular.horizontalHeaderItem(0).text()=='Przedmiot'
        assert 'NIEROZPOZNANE' in w.summary.text()
        for code in ('en','pl','en'):
            w.language_buttons[code].click();app.processEvents()
            assert language()==code and store.meta('language')==code
            assert w.language_buttons[code].isChecked()
            assert not w.language_buttons['pl' if code=='en' else 'en'].isChecked()
            assert not w.language_buttons[code].icon().isNull()
            assert w.result==original and api.calls==calls
            assert w.raw.toPlainText()==original['raw']
            assert w.params=={}
            assert w.tabs.tabText(0)==('Analyze loot' if code=='en' else 'Analiza łupów')
            assert ('.' if code=='en' else ',') in w.fields['faction'].text()
            assert w.regular.horizontalHeaderItem(0).text()==('Item' if code=='en' else 'Przedmiot')
            assert w.blueprints.horizontalHeaderItem(2).text()==tr('Avg cost / 1 BPC')
            assert w.blueprints.horizontalHeader().sortIndicatorSection()==2
            assert w.watch.item(0,1).text()==tr('Sell price')
            assert tr(original['regular'][0]['action']) in w.regular.item(0,13).text()
            assert tr('Build cost') in w.blueprint_html(original['blueprints'][0])
            assert tr('Immutable saved snapshot') in w.snapshot_html(store.sessions()[0])
            box=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel,w)
            expected=('Zapisz','Zachowaj') if code=='pl' else ('Save',)
            assert box.button(QDialogButtonBox.Save).text().replace('&','') in expected
            box.deleteLater()
        w.watch.selectRow(0)
        def save_target():
            dialog=app.activeModalWidget()
            combo=next(c for c in dialog.findChildren(QComboBox) if c.findData('Buy price')>=0)
            combo.setCurrentIndex(combo.findData('Buy price'))
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Save).click()
        QTimer.singleShot(20,save_target);w.edit_watch()
        assert store.query('SELECT mode FROM watchlist')[0]['mode']=='Buy price'
        assert store.sessions()[0]['snapshot']['regular'][0]['action']==original['regular'][0]['action']
        w.close();app.processEvents()
        other=MainWindow(store,Engine(store,api))
        assert other.language_buttons['en'].isChecked()
        assert other.tabs.tabText(0)=='Analyze loot'
        other.close();app.processEvents()
    finally:
        if w.busy:wait_until(app,lambda:not w.busy)
        w.close();app.processEvents();set_language('pl')

def test_language_change_during_worker_updates_new_widgets(tmp_path):
    app=QApplication.instance() or QApplication([])
    store=Store(tmp_path/'worker.db');populate(store);api=FakeEsi();api.close=lambda:None
    w=MainWindow(store,Engine(store,api));w.show()
    release=threading.Event()
    report=w.engine.analyze('Item 1',w.profile)
    def task(progress):
        release.wait(3)
        progress('Analyzing Item 1')
        return report
    try:
        w.raw.setPlainText('Item 1');w.run(task,w.render_result)
        w.language_buttons['en'].click()
        assert w.busy and not w.analyze_button.isEnabled()
        release.set();wait_until(app,lambda:not w.busy)
        assert w.result==report and w.analyze_button.isEnabled()
        assert w.status.text().startswith('Analysis complete.')
    finally:
        release.set();wait_until(app,lambda:not w.busy);w.close();app.processEvents();set_language('pl')
