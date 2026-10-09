import os
import json
from dataclasses import replace
import pytest
import numpy as np

pytestmark=pytest.mark.skipif(os.environ.get('STRATASCRY_GUI_TESTS')!='1',reason='Requires a desktop display')


@pytest.fixture
def window(tmp_path):
    from PySide6.QtCore import QCoreApplication,QEvent
    from PySide6.QtTest import QTest
    from stratascry.app import create_application
    from stratascry.window import MainWindow
    app=create_application([])
    w=MainWindow(tile_path=tmp_path); w.show(); w.raise_(); w.activateWindow()
    QTest.qWaitForWindowActive(w,3000); QTest.qWait(100)
    yield w
    w.graph.document.mark_saved(); w.close(); w.deleteLater()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete); app.processEvents()


def prepare(window):
    from PySide6.QtTest import QTest
    c=window.graph; c.set_building(True); c.activate_layer()
    window.globe.navigation.distance=1.03; window.globe.apply_camera(); QTest.qWait(60)
    c.overlay.rebuild()
    return c


def test_hover_click_and_move_with_edges(window):
    from PySide6.QtCore import Qt,QPoint
    from PySide6.QtTest import QTest
    c=prepare(window); g=window.globe; d=c.document
    c.set_tool('node'); g.setFocus()
    p=QPoint(g.width()//2,g.height()//2)
    # Cocoa QTest.mouseMove may only warp the cursor without a hover event.
    from PySide6.QtCore import QEvent,QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    QApplication.sendEvent(g,QMouseEvent(QEvent.Type.MouseMove,QPointF(p),QPointF(g.mapToGlobal(p)),Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier))
    assert c.ghost is not None and not d.nodes
    QTest.mouseClick(g,Qt.MouseButton.LeftButton,pos=p)
    assert len(d.nodes)==1; first=c.selected
    q=p+QPoint(100,0)
    QTest.mouseClick(g,Qt.MouseButton.LeftButton,pos=q)
    assert len(d.nodes)==2; second=c.selected
    e=d.add_edge(first,second); c.changed(); c.overlay.rebuild()
    c.set_tool('select'); g.setFocus()
    old=(d.nodes[first].lon,d.nodes[first].lat); cursor=d.cursor
    QTest.mousePress(g,Qt.MouseButton.LeftButton,pos=p)
    QTest.mouseMove(g,p+QPoint(30,20)); QTest.mouseRelease(g,Qt.MouseButton.LeftButton,pos=p+QPoint(30,20))
    assert (d.nodes[first].lon,d.nodes[first].lat)!=old
    assert d.cursor==cursor+1 and d.edges[e].source==first
    c.undo(); assert (d.nodes[first].lon,d.nodes[first].lat)==old
    c.set_tool('node'); count=len(d.nodes)
    QTest.mousePress(g,Qt.MouseButton.LeftButton,pos=p)
    QTest.mouseMove(g,p+QPoint(30,0)); QTest.mouseRelease(g,Qt.MouseButton.LeftButton,pos=p+QPoint(30,0))
    assert len(d.nodes)==count


def test_viewing_blocks_commands_and_text_b_does_not_toggle(window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    c=prepare(window); d=c.document
    key=d.add_node(c.active,-90,25); c.changed(); c.select(key); c.show_properties()
    c.name.setFocus(); c.name.clear(); QTest.keyClicks(c.name,'B test')
    assert c.building and c.name.text()=='B test'
    c.apply_properties(); assert d.nodes[key].name=='B test'
    c.set_building(False); before=d.to_dict()
    for key in ('delete','undo','redo','visible_layer','up_layer','pin','definitions','node'):
        assert not c.actions[key].isEnabled(),key
        c.actions[key].trigger()
    with pytest.raises(ValueError): c.apply_properties()
    assert d.to_dict()==before
    window.globe.setFocus(); QTest.keyClick(window.globe,Qt.Key.Key_B)
    assert c.building


def test_top_layer_edge_blocks_lower_node_and_parallel_list(window):
    c=prepare(window); d=c.document; low=c.active
    center=d.add_node(low,-90,25)
    high=d.new_layer('Top'); a=d.add_node(high,-90.4,25); b=d.add_node(high,-89.6,25)
    e=d.add_edge(a,b); other=d.add_edge(a,b)
    c.changed(); c.overlay.rebuild()
    p=c.overlay.node_xy[center]
    hits=c.overlay.hits(*p)
    assert hits and set(hits)=={e,other}
    assert not c.can_edit(e) and c.can_edit(center)
    c.select(hits[0],hits); assert not c.apply_button.isEnabled()
    assert c.candidates.count()==2
    d.update_layer(high,visible=False); c.changed(); c.overlay.rebuild()
    assert c.overlay.hits(*p)[0]==center


def test_layer_history_null_active_and_properties(window):
    c=prepare(window); d=c.document; layer=c.active
    a=d.add_node(layer,-90,25); b=d.add_node(layer,-89.9,25); e=d.add_edge(a,b)
    c.changed(); c.select(e); c.show_properties()
    c.weight_mode.setCurrentIndex(2); c.weight_scale.setText('0.001'); c.weight_unit.setText('km'); c.apply_properties()
    assert d.weight(d.edges[e])==pytest.approx(d.edge_length(d.edges[e])*.001)
    c.toggle_layer(); assert c.active is None and not d.layers[layer].visible
    c.undo(); assert d.layers[layer].visible and c.active is None
    assert not c.can_edit(e)
    c.activate_layer(); assert c.can_edit(e)
    d.delete_layer(layer); c.changed(); assert not d.layers and c.active is None
    c.undo(); assert len(d.edges)==1 and c.active is None


def test_display_changes_leave_weights_and_topology_unchanged(window):
    c=prepare(window); d=c.document; layer=c.active
    a=d.add_node(layer,-90,25); b=d.add_node(layer,-89.9,25); e=d.add_edge(a,b)
    d.update_edge(e,weight_mode='length'); c.changed(); c.overlay.rebuild()
    original=d.weight(d.edges[e]); edges=json.dumps(d.to_dict()['edges'],sort_keys=True)
    c.toggle_dim(True); c.toggle_declutter(False); window.globe.zoom(1); c.overlay.rebuild()
    assert d.weight(d.edges[e])==original
    assert json.dumps(d.to_dict()['edges'],sort_keys=True)==edges


def test_save_open_roundtrip_ui(window,tmp_path,monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from PySide6.QtTest import QTest
    c=prepare(window); c.document.add_node(c.active,-90,25); c.changed()
    path=str(tmp_path/'edited.ssg.json')
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *args,**kwargs:(path,''))
    assert c.save() and not c.document.dirty
    expected=c.document.to_dict(); c.new_project(); assert not c.document.nodes
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *args,**kwargs:(path,''))
    c.open_project()
    for _ in range(100):
        if c.reader is None: break
        QTest.qWait(20)
    assert c.reader is None and c.document.to_dict()==expected


def test_shared_tool_actions_accept_toggled_state(window,monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    c=prepare(window)
    errors=[]
    monkeypatch.setattr(QMessageBox,'warning',lambda *args:errors.append(args[2]))
    for key in ('node','edge','select','node'):
        c.actions[key].trigger()
        assert c.tool==key
        assert c.actions[key].isChecked()
        assert sum(c.actions[k].isChecked() for k in ('node','edge','select'))==1
    assert not errors


@pytest.mark.parametrize('dim',[0.0,0.3])
def test_drag_redraw_replaces_previous_pixels(window,dim):
    """A retained transparent surface must match a freshly painted frame.

    A normal QWidget.grab() starts with a clean image and misses stale backing
    pixels. Reuse the destination here, including its alpha channel, instead.
    """
    from PySide6.QtCore import QEvent,QPoint,QPointF,Qt
    from PySide6.QtGui import QImage,QMouseEvent,QPainter,QRegion
    from PySide6.QtWidgets import QApplication,QWidget
    from PySide6.QtTest import QTest
    c=prepare(window); g=window.globe; d=c.document; o=c.overlay
    a=d.add_node(c.active,-90,25); b=d.add_node(c.active,-89.8,25.1)
    d.add_edge(a,b); d.setting('dim',dim,'Dim basemap')
    c.changed(); c.set_building(False); o.rebuild()
    original=d.to_dict()

    def image():
        result=QImage(o.size()*o.devicePixelRatioF(),QImage.Format.Format_ARGB32_Premultiplied)
        result.setDevicePixelRatio(o.devicePixelRatioF())
        result.fill(Qt.GlobalColor.transparent)
        return result

    def paint(target):
        painter=QPainter(target)
        try:
            o.render(painter,QPoint(),QRegion(),QWidget.RenderFlag.DrawChildren)
        finally:
            painter.end()

    retained=image(); paint(retained)

    def check_frame():
        paint(retained)
        fresh=image(); paint(fresh)
        assert np.array_equal(np.frombuffer(retained.constBits(),dtype=np.uint8),
                              np.frombuffer(fresh.constBits(),dtype=np.uint8))
        assert retained.pixelColor(0,0).alpha()==round(dim*255)

    start=QPoint(g.width()//2,g.height()//2); finish=start
    longitude=g.navigation.longitude
    QTest.mousePress(g,Qt.MouseButton.RightButton,pos=start)
    try:
        for step in range(1,9):
            finish=start+QPoint(step*14,step*4)
            QApplication.sendEvent(g,QMouseEvent(QEvent.Type.MouseMove,QPointF(finish),
                QPointF(g.mapToGlobal(finish)),Qt.MouseButton.NoButton,
                Qt.MouseButton.RightButton,Qt.KeyboardModifier.NoModifier))
            QTest.qWait(25); o.rebuild(); check_frame()
    finally:
        QTest.mouseRelease(g,Qt.MouseButton.RightButton,pos=finish)
    assert g.navigation.longitude!=longitude
    assert d.to_dict()==original
    # Idle redraws must not accumulate dimming; disappearing objects must erase.
    check_frame()
    d.update_layer(d.nodes[a].layer,visible=False)
    c.changed(); o.rebuild(); check_frame()


def test_hotbar_default_repeat_menu_and_coordinate_placement(window,monkeypatch):
    from PySide6.QtCore import QPoint,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QInputDialog
    c=prepare(window); bar=c.hotbar; node=bar.buttons['node']; menu=bar.menus['node']
    prompts=[]
    def coordinates(*args,**kwargs):
        prompts.append(args)
        return '-90.1, 25.1',True
    monkeypatch.setattr(QInputDialog,'getText',coordinates)
    # Press the main icon, not its separate dropdown arrow.
    main=QPoint(12,node.height()//2)
    QTest.mouseClick(node,Qt.MouseButton.LeftButton,pos=main)
    assert c.tool=='node' and node.isChecked() and not menu.isVisible()
    assert not c.document.nodes and not prompts
    QTest.mouseClick(node,Qt.MouseButton.LeftButton,pos=main)
    assert menu.isVisible() and c.tool=='node' and node.isChecked()
    click_choice,coordinate_choice=menu.actions()
    assert [a.text() for a in menu.actions()]==['Add node by clicking','Add node by coordinates…']
    assert click_choice.isChecked()
    QTest.mouseClick(menu,Qt.MouseButton.LeftButton,pos=menu.actionGeometry(coordinate_choice).center())
    assert len(prompts)==1 and len(c.document.nodes)==1
    added=c.document.nodes[c.selected]
    assert (added.lon,added.lat)==(-90.1,25.1)
    assert c.tool=='node' and node.isChecked() and not menu.isVisible()
    c.undo(); assert not c.document.nodes
    # Coordinate placement is one command; the default remains click placement.
    g=window.globe
    QTest.mouseClick(g,Qt.MouseButton.LeftButton,pos=QPoint(g.width()//2,g.height()//2))
    assert len(c.document.nodes)==1
    QTest.mouseClick(node,Qt.MouseButton.LeftButton,pos=main)
    QTest.mouseClick(menu,Qt.MouseButton.LeftButton,pos=menu.actionGeometry(click_choice).center())
    assert c.tool=='node' and node.isChecked() and not menu.isVisible()
    assert len(c.document.nodes)==1


def test_hotbar_shared_state_permissions_and_cancel(window,monkeypatch):
    from PySide6.QtCore import QPoint,Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QInputDialog
    c=prepare(window); bar=c.hotbar; menu=bar.menus['node']; node=bar.buttons['node']
    for key in ('edge','node','select'):
        c.actions[key].trigger()
        assert bar.buttons[key].isChecked()
        assert sum(b.isChecked() for b in bar.buttons.values())==1
    c.set_tool('node')  # Controller updates block QAction signals; still synchronize.
    assert node.isChecked() and not bar.buttons['select'].isChecked()
    original=c.document.to_dict()
    monkeypatch.setattr(QInputDialog,'getText',lambda *args,**kwargs:('',False))
    QTest.mouseClick(node,Qt.MouseButton.LeftButton,pos=QPoint(12,node.height()//2))
    QTest.mouseClick(menu,Qt.MouseButton.LeftButton,pos=menu.actionGeometry(menu.actions()[1]).center())
    assert c.document.to_dict()==original and node.isChecked()
    c.clear_active()
    assert not menu.actions()[1].isEnabled()
    c.activate_layer(); assert menu.actions()[1].isEnabled()
    c.toggle_layer(); assert not menu.actions()[1].isEnabled()
    c.set_building(False)
    assert all(not b.isEnabled() for b in bar.buttons.values())
    assert not menu.actions()[1].isEnabled()
    before=c.document.to_dict()
    QTest.mouseClick(node,Qt.MouseButton.LeftButton)
    assert c.document.to_dict()==before and not menu.isVisible()


def test_hotbar_keyboard_and_another_tool_can_have_choices(window):
    from PySide6.QtCore import QPoint,Qt
    from PySide6.QtTest import QTest
    from stratascry.graph.hotbar import GraphHotbar,ToolSpec,ToolChoice
    c=prepare(window)
    # Reuse the same mechanism for a future edge variant without node branches.
    extra=GraphHotbar(c,(ToolSpec('edge','Future edge tool','add-edge.svg','Edge tool options',
                                (ToolChoice('edge','Add edge by clicking'),)),))
    window.centralWidget().layout().insertWidget(3,extra)
    QTest.qWait(40)
    button=extra.buttons['edge']; menu=extra.menus['edge']
    button.setFocus(); QTest.keyClick(button,Qt.Key.Key_Space)
    assert c.tool=='edge' and button.isChecked() and not menu.isVisible()
    button.setFocus(); QTest.keyClick(button,Qt.Key.Key_Space)
    assert menu.isVisible() and c.tool=='edge'
    QTest.keyClick(menu,Qt.Key.Key_Escape)
    assert not menu.isVisible() and button.isChecked()
    assert not button.icon().isNull()
    extra.hide(); extra.deleteLater()
