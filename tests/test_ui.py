import time
from PySide6.QtWidgets import QApplication,QDialog,QDialogButtonBox,QPushButton,QSpinBox
from PySide6.QtCore import QTimer,Qt
from app.ui import MainWindow,STYLE,table,fill_table,money,selected_source_row,per_copy
from decimal import Decimal as D
from app.storage import Store
from app.engine import Engine
from tests.test_integration import populate,FakeEsi

def wait_until(app,predicate,seconds=10):
    deadline=time.monotonic()+seconds
    while not predicate() and time.monotonic()<deadline:
        app.processEvents()
        time.sleep(.005)
    assert predicate()

def test_gui_analyze_blueprint_watch_session_and_profile(tmp_path):
    app=QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLE)
    s=Store(tmp_path/'ui.db');populate(s);api=FakeEsi();api.close=lambda:None
    w=MainWindow(s,Engine(s,api));w.show()
    try:
        w.raw.setPlainText('\n'.join(f'Item {i}\t2' for i in range(1,8)))
        w.analyze()
        wait_until(app,lambda:w.result is not None and not w.busy)
        assert w.regular.rowCount()==5 and w.blueprints.rowCount()==2
        assert w.save_button.isEnabled()
        w.blueprints.selectRow(0)
        def edit_bpc():
            d=app.activeModalWidget()
            controls=d.findChildren(QSpinBox)
            controls[0].setValue(3);controls[1].setValue(2);controls[2].setValue(6);controls[3].setValue(10)
            next(b for b in d.findChildren(QPushButton) if b.text()=='Zastosuj i przelicz').click()
        QTimer.singleShot(20,edit_bpc);w.blueprint_details()
        wait_until(app,lambda:not w.busy)
        assert w.result['blueprints'][0]['params']['runs']==2
        w.regular.selectRow(0)
        def save_watch():
            app.activeModalWidget().findChild(QDialogButtonBox).button(QDialogButtonBox.Save).click()
        QTimer.singleShot(20,save_watch);w.watch_selected()
        assert w.watch.rowCount()==1
        w.refresh_watch();wait_until(app,lambda:not w.busy)
        assert w.watch.item(0,5).text()!='N/A'
        QTimer.singleShot(20,lambda:app.activeModalWidget().accept());w.save_session()
        assert w.sessions_table.rowCount()==1 and w.drops.rowCount()==7
        first=s.sessions()[0]['snapshot']
        w.fields['accounting'].setValue(5)
        wait_until(app,lambda:w.profile.get('accounting')==5 and not w.busy)
        assert s.sessions()[0]['snapshot']==first
        w.raw.setPlainText('Item 1\t100')
        assert not w.save_button.isEnabled()
    finally:
        wait_until(app,lambda:not w.busy)
        w.close();app.processEvents()

def test_sorting_uses_exact_money_and_keeps_rows_together():
    app=QApplication.instance() or QApplication([])
    t=table(['Item','ISK','Qty'])
    amounts=[D('1000000.02'),D('900000'),D('1000000.01'),None,D('-2000')]
    rows=[[str(i),money(value),100+i] for i,value in enumerate(amounts)]
    keys=[[str(i),value,100+i] for i,value in enumerate(amounts)]
    fill_table(t,rows,keys)
    t.sortItems(1,Qt.AscendingOrder)
    assert [t.item(i,0).text() for i in range(5)]==['4','1','2','0','3']
    t.sortItems(1,Qt.DescendingOrder)
    assert [t.item(i,0).text() for i in range(5)]==['3','0','2','1','4']
    fill_table(t,rows,keys)
    assert t.horizontalHeader().sortIndicatorSection()==1
    assert [t.item(i,0).text() for i in range(5)]==['3','0','2','1','4']
    for i in range(5):assert int(t.item(i,2).text())==100+int(t.item(i,0).text())
    t.selectRow(1);assert selected_source_row(t)==0
    t.close()

def test_sorted_actions_use_the_selected_item_watch_and_session(tmp_path):
    app=QApplication.instance() or QApplication([])
    s=Store(tmp_path/'sorted.db');populate(s);api=FakeEsi();api.close=lambda:None
    w=MainWindow(s,Engine(s,api))
    try:
        report=w.engine.analyze('\n'.join(f'Item {i}\t{i}' for i in range(1,8)),{})
        w.render_result(report)
        w.regular.sortItems(1,Qt.DescendingOrder);w.regular.selectRow(0)
        assert w.chosen(w.regular,'regular')['type_id']==5
        w.blueprints.sortItems(1,Qt.DescendingOrder);w.blueprints.selectRow(0)
        assert w.chosen(w.blueprints,'blueprints')['type_id']==7
        blueprint=w.chosen(w.blueprints,'blueprints')
        assert w.blueprints.item(0,2).text()==money(blueprint['build_cost']/7)
        assert w.blueprints.item(0,3).text()==money(blueprint['realistic_profit']/7)
        for i in (1,2):s.execute('INSERT INTO watchlist(type_id,name,mode,target,direction) VALUES(?,?,?,?,?)',(i,f'Item {i}','Sell price',str(i),'>='))
        w.render_watch();w.watch.sortItems(2,Qt.DescendingOrder);w.watch.selectRow(0)
        captured=[];w.add_watch=lambda **kw:captured.append(kw['existing']['type_id'])
        w.edit_watch();assert captured==[2]
        w.remove_watch();assert [r['type_id'] for r in s.query('SELECT type_id FROM watchlist')]==[1]
        for name in ('Alpha','Zulu'):s.save_session(name,'World Ark',30,1,report['raw'],report)
        w.render_sessions();w.sessions_table.sortItems(0,Qt.DescendingOrder);w.sessions_table.selectRow(0)
        w.detail_browser=lambda title,content:captured.append(title)
        w.session_details();assert captured[-1]=='Zulu'
    finally:w.close();app.processEvents()

def test_per_copy_uses_copies_not_runs_and_preserves_missing_values():
    blueprint={'quantity':4,'params':{'runs':10},'build_cost':D('100.12'),'realistic_profit':D('-20.04')}
    assert per_copy(blueprint,'build_cost')==D('25.03')
    assert per_copy(blueprint,'realistic_profit')==D('-5.01')
    assert per_copy(blueprint,'output_instant_net') is None
