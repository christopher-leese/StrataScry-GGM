# SPDX-License-Identifier: Apache-2.0
"""Single editing authority: modes, shared actions, properties, layers and files."""
from dataclasses import replace
import json
from pathlib import Path
import math
from PySide6.QtCore import Qt, QObject, QThread, Signal, QPointF
from PySide6.QtGui import QActionGroup, QColor
from PySide6.QtWidgets import (
    QDockWidget,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QListWidget,
    QLineEdit,QDoubleSpinBox,QComboBox,QCheckBox,QPushButton,QPlainTextEdit,
    QTableWidget,QTableWidgetItem,QTabWidget,QFileDialog,QMessageBox,QInputDialog,
    QColorDialog,QDialog,QDialogButtonBox,QAbstractItemView,QApplication,QScrollArea,
)
from .model import Document, Node, Edge, Waypoint, uid
from .geometry import coordinate, unit
from .renderer import GraphOverlay
from . import persistence


class ProjectReader(QThread):
    loaded=Signal(object,str)
    failed=Signal(str)
    def __init__(self,path,parent): super().__init__(parent); self.path=path
    def run(self):
        try: self.loaded.emit(persistence.load(self.path),self.path)
        except Exception as e: self.failed.emit(str(e))


class GraphController(QObject):
    def __init__(self,window):
        super().__init__(window)
        self.window=window; self.globe=window.globe
        self.document=Document(); self.path=None; self.building=False; self.tool='select'
        self.active=None; self.selected=None; self.reveal=False; self.overlaps=[]
        self.ghost=None; self.pointer=None; self.draft_source=None; self.draft_points=[]
        self.press=None; self.move_key=None; self.move_preview=None; self.dragged=False
        self.grab_offset=QPointF(); self.closing=False; self.reader=None; self.message=''
        self.globe.graph_controller=self
        self.overlay=GraphOverlay(self)
        self.globe.camera_changed.connect(self.camera_changed)
        self.make_panels(); self.make_actions()
        from .hotbar import GraphHotbar
        self.hotbar=GraphHotbar(self)
        self.changed(full=True)

    def action(self,key,title,callback,shortcuts=(),check=False,globe_only=False):
        a=self.window._action('graph_'+key,title,lambda *args:self.safe(callback,*args),shortcuts,check)
        if globe_only:
            self.window.removeAction(a); self.globe.addAction(a)
            a.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        a.setAutoRepeat(False)
        return a

    def make_actions(self):
        specs=[
            ('build','Graph-Building Mode',self.set_building,('B',),True,True),
            ('select','Select / Move',lambda checked:self.set_tool('select') if checked else None,(),True,False),
            ('node','Add Node',lambda checked:self.set_tool('node') if checked else None,(),True,False),
            ('edge','Add Edge',lambda checked:self.set_tool('edge') if checked else None,(),True,False),
            ('cancel','Cancel Current Gesture',self.cancel,('Escape',),False,True),
            ('properties','Object / Edge Properties…',self.show_properties,(),False,False),
            ('delete','Delete Selected Object',self.delete_selected,('Backspace','Delete'),False,True),
            ('undo','Undo',self.undo,('Ctrl+Z',),False,True),
            ('redo','Redo',self.redo,('Ctrl+Shift+Z',),False,True),
            ('reverse','Reverse Edge Direction',self.reverse,(),False,False),
            ('waypoint','Insert Shape Waypoint…',self.insert_waypoint,(),False,False),
            ('remove_waypoint','Remove Selected Shape Waypoint',self.remove_waypoint,(),False,False),
            ('coordinate','Place Node by Coordinates…',self.place_coordinates,(),False,False),
            ('definitions','Attribute Definitions…',self.definitions,(),False,False),
            ('pin','Pin / Unpin Selected Object',self.pin,(),False,False),
            ('reveal','Reveal Hidden Neighbors',self.reveal_neighbors,(),False,False),
            ('clear_reveal','Clear Reveal',self.clear_reveal,(),False,False),
            ('declutter','Declutter Graph',self.toggle_declutter,(),True,False),
            ('dim','Dim Basemap',self.toggle_dim,(),True,False),
            ('panel','Layers and Properties',self.toggle_panel,(),True,False),
            ('new','New Graph Project',self.new_project,(),False,False),
            ('open','Open Graph Project…',self.open_project,('Ctrl+O',),False,False),
            ('save','Save Graph Project',self.save,('Ctrl+S',),False,False),
            ('save_as','Save Graph Project As…',lambda:self.save(True),('Ctrl+Shift+S',),False,False),
            ('add_layer','Add Layer…',self.add_layer,(),False,False),
            ('rename_layer','Rename Layer…',self.rename_layer,(),False,False),
            ('color_layer','Layer Color…',self.color_layer,(),False,False),
            ('delete_layer','Delete Layer…',self.delete_layer,(),False,False),
            ('visible_layer','Show / Hide Layer',self.toggle_layer,(),False,False),
            ('active_layer','Set Selected Layer Active',self.activate_layer,(),False,False),
            ('clear_active','Clear Active Layer',self.clear_active,(),False,False),
            ('up_layer','Move Layer Up',lambda:self.reorder_layer(-1),(),False,False),
            ('down_layer','Move Layer Down',lambda:self.reorder_layer(1),(),False,False),
            ('status','Graph Performance / Capacity…',self.show_stats,(),False,False),
        ]
        self.actions={k:self.action(k,t,cb,sc,ch,go) for k,t,cb,sc,ch,go in specs}
        group=self.tool_group=QActionGroup(self); group.setExclusive(True)
        for k in ('select','node','edge'): group.addAction(self.actions[k])
        # Project file commands live under File, ahead of Quit (which macOS moves to the app menu).
        file_menu=self.window.file_menu
        for key in ('new','open','save','save_as'): file_menu.insertAction(self.window.quit_action,self.actions[key])
        file_menu.insertSeparator(self.window.quit_action)
        for menu in (self.window.view_menu,self.window.context_menu):
            menu.addSeparator()
            for title,keys in (
                ('Graph Tools',('build','select','node','edge','cancel','properties','coordinate','delete','undo','redo','reverse','waypoint','remove_waypoint','definitions')),
                ('Graph Display',('panel','pin','reveal','clear_reveal','declutter','dim','status')),
                ('Graph Layers',('add_layer','rename_layer','color_layer','delete_layer','visible_layer','active_layer','clear_active','up_layer','down_layer'))):
                sub=menu.addMenu(title)
                for key in keys: sub.addAction(self.actions[key])
        self.dock.visibilityChanged.connect(lambda v:self.sync_checks())
        self.sync_checks()

    def spin(self,lo,hi,value=0):
        s=QDoubleSpinBox(); s.setRange(lo,hi); s.setDecimals(7); s.setValue(value); s.setKeyboardTracking(False)
        return s

    def make_panels(self):
        self.dock=QDockWidget('Graph Layers & Properties',self.window)
        self.dock.setObjectName('graph_inspector')
        self.window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,self.dock)
        root=QWidget(); layout=QVBoxLayout(root)
        self.mode_label=QLabel(); self.mode_label.setWordWrap(True); layout.addWidget(self.mode_label)
        self.tabs=QTabWidget(); layout.addWidget(self.tabs)
        layers=QWidget(); ll=QVBoxLayout(layers)
        ll.addWidget(QLabel('Layer order: top row draws and picks first'))
        self.layer_list=QListWidget(); self.layer_list.setMinimumWidth(280)
        self.layer_list.currentRowChanged.connect(lambda _:self.sync_actions())
        ll.addWidget(self.layer_list)
        self.layer_buttons=[]
        for row in ((('Add',self.add_layer),('Active',self.activate_layer),('Clear active',self.clear_active)),
                    (('Show / Hide',self.toggle_layer),('↑',lambda:self.reorder_layer(-1)),('↓',lambda:self.reorder_layer(1)))):
            box=QHBoxLayout()
            for label,callback in row:
                button=QPushButton(label); self.layer_buttons.append((label,button)); button.clicked.connect(lambda checked=False,cb=callback:self.safe(cb)); box.addWidget(button)
            ll.addLayout(box)
        self.layer_note=QLabel('B enables editing. Hidden and inactive objects are read-only.'); self.layer_note.setWordWrap(True); ll.addWidget(self.layer_note)
        self.tabs.addTab(layers,'Layers')
        props=QWidget(); pl=QVBoxLayout(props)
        self.identity=QLabel('Select an object on the globe.'); self.identity.setWordWrap(True); self.identity.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); pl.addWidget(self.identity)
        self.candidates=QComboBox(); self.candidates.currentIndexChanged.connect(self.choose_overlap); pl.addWidget(self.candidates)
        form=QFormLayout(); pl.addLayout(form)
        self.name=QLineEdit(); self.name.setPlaceholderText('Blank = automatic layer name'); form.addRow('Name',self.name)
        self.kind=QLineEdit(); form.addRow('Node kind',self.kind)
        self.longitude=self.spin(-180,180); self.latitude=self.spin(-90,90)
        form.addRow('Longitude °E',self.longitude); form.addRow('Latitude °N',self.latitude)
        self.directed=QCheckBox('Directed'); form.addRow('Edge',self.directed)
        self.length_label=QLabel('—'); form.addRow('Route length',self.length_label)
        self.weight_mode=QComboBox(); self.weight_mode.addItems(['Unassigned','Manual','Route length']); form.addRow('Weight source',self.weight_mode)
        self.weight_value=QLineEdit('0'); self.weight_scale=QLineEdit('1'); self.weight_unit=QLineEdit('m')
        form.addRow('Manual value',self.weight_value); form.addRow('Length scale',self.weight_scale); form.addRow('Weight units',self.weight_unit)
        self.weight_label=QLabel('—'); form.addRow('Computed weight',self.weight_label)
        pl.addWidget(QLabel('Shape waypoints (longitude, latitude)'))
        self.waypoints=QTableWidget(0,2); self.waypoints.setHorizontalHeaderLabels(['Longitude','Latitude']); self.waypoints.setMaximumHeight(140); pl.addWidget(self.waypoints)
        attributes_help=QLabel('Attributes — JSON object: text, number, boolean, string list'); attributes_help.setWordWrap(True); pl.addWidget(attributes_help)
        self.attributes=QPlainTextEdit('{}'); self.attributes.setMaximumHeight(100); pl.addWidget(self.attributes)
        self.apply_button=QPushButton('Apply Properties'); self.apply_button.clicked.connect(lambda:self.safe(self.apply_properties)); pl.addWidget(self.apply_button)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(props); self.tabs.addTab(scroll,'Properties')
        self.dock.setWidget(root)
        self.status=QLabel(); self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.window.statusBar().addWidget(self.status,1)
        self.dock.hide()

    def safe(self,callback,*args):
        try: return callback(*args)
        except (ValueError,KeyError,TypeError,OSError,OverflowError) as e:
            QMessageBox.warning(self.window,'Graph editor',str(e))
            return None

    def can_edit(self,key=None):
        if not self.building or self.reader: return False
        if key is None: return self.active in self.document.layers and self.document.layers[self.active].visible
        obj=self.document.nodes.get(key) or self.document.edges.get(key)
        return bool(obj and obj.layer==self.active and self.document.layers[obj.layer].visible)

    def require_build(self):
        if not self.building or self.reader: raise ValueError('Enable Graph-Building Mode (B) to edit the document')
    def require_edit(self,key=None):
        if not self.can_edit(key): raise ValueError('Editing requires building mode and a visible active layer')

    def set_building(self,value):
        self.cancel(); self.building=bool(value)
        self.message='Choose a visible layer and set it active.' if value and not self.active else ''
        if value: self.dock.show()
        self.sync_actions(); self.refresh_properties(); self.overlay.schedule()

    def set_tool(self,tool):
        if not self.building: return
        self.cancel(); self.tool=tool; self.sync_checks(); self.update_status_only(); self.globe.setFocus()

    def sync_checks(self):
        if not hasattr(self,'actions'): return
        values={'build':self.building,'select':self.tool=='select','node':self.tool=='node','edge':self.tool=='edge',
                'declutter':self.document.settings['declutter'],'dim':bool(self.document.settings['dim']),'panel':self.dock.isVisible()}
        for k,v in values.items():
            a=self.actions[k]; a.blockSignals(True); a.setChecked(v); a.blockSignals(False)
        if hasattr(self,'hotbar'): self.hotbar.sync()

    def sync_actions(self):
        if not hasattr(self,'actions'): return
        busy=self.reader is not None
        b=self.building and not busy; editable=self.can_edit(self.selected); has=self.selected in self.document.nodes or self.selected in self.document.edges
        edge=self.selected in self.document.edges
        target=self.layer_target()
        for label,button in self.layer_buttons:
            button.setEnabled(not busy and (label=='Clear active' or (label=='Active' and target is not None and self.document.layers[target].visible) or (b and (label=='Add' or target is not None))))
        for key in ('select','node','edge','definitions','add_layer','declutter','dim','pin'):
            self.actions[key].setEnabled(b and (has if key=='pin' else True))
        for key in ('rename_layer','color_layer','delete_layer','visible_layer','up_layer','down_layer'):
            self.actions[key].setEnabled(b and target is not None)
        self.actions['active_layer'].setEnabled(not busy and target is not None and self.document.layers[target].visible)
        for key in ('delete','reverse','waypoint','remove_waypoint'):
            self.actions[key].setEnabled(editable and (edge if key!='delete' else has))
        self.actions['coordinate'].setEnabled(self.can_edit())
        self.actions['undo'].setEnabled(b and self.document.cursor>0)
        self.actions['redo'].setEnabled(b and self.document.cursor<len(self.document.history))
        self.actions['undo'].setText('Undo '+(self.document.history[self.document.cursor-1].label if self.document.cursor else ''))
        self.actions['redo'].setText('Redo '+(self.document.history[self.document.cursor].label if self.document.cursor<len(self.document.history) else ''))
        self.actions['properties'].setEnabled(has)
        self.actions['reveal'].setEnabled(self.selected in self.document.nodes)
        self.actions['clear_reveal'].setEnabled(self.reveal)
        self.actions['clear_active'].setEnabled(self.active is not None)
        for key in ('new','open','save','save_as','build'): self.actions[key].setEnabled(not busy)
        self.sync_checks(); self.update_status_only()

    def update_status_only(self):
        d=self.document
        active=d.layers[self.active].name if self.active in d.layers else 'none'
        mode=('BUILD · '+{'select':'Select / Move','node':'Add Node','edge':'Add Edge'}[self.tool]) if self.building else 'VIEW · read-only'
        stats=self.overlay.stats
        capacity=' · display capacity reached; inspect members individually' if stats.get('capacity') else ''
        self.mode_label.setText(f'{mode}\nActive layer: {active}')
        self.status.setText(f'{mode} · Active: {active} · {len(d.nodes)} nodes / {len(d.edges)} edges'+capacity+(' · '+self.message if self.message else ''))
        self.window.setWindowTitle(f'StrataScry GGM — {Path(self.path).name if self.path else "Untitled graph"}{" *" if d.dirty else ""}')

    def changed(self,full=False):
        d=self.document
        if self.active not in d.layers or not d.layers[self.active].visible: self.active=None; self.cancel()
        if self.selected:
            obj=d.nodes.get(self.selected) or d.edges.get(self.selected)
            if obj is None or not d.layers[obj.layer].visible: self.selected=None; self.reveal=False
        previous=self.layer_target()
        self.layer_list.blockSignals(True); self.layer_list.clear()
        for k in d.settings['order']:
            l=d.layers[k]; prefix='●' if l.visible else '○'
            self.layer_list.addItem(f'{prefix} {l.name}'+('  [active]' if k==self.active else ''))
            item=self.layer_list.item(self.layer_list.count()-1); item.setData(Qt.ItemDataRole.UserRole,k); item.setForeground(QColor(l.color))
            if k==previous: self.layer_list.setCurrentItem(item)
        if self.layer_list.currentRow()<0 and self.layer_list.count(): self.layer_list.setCurrentRow(0)
        self.layer_list.blockSignals(False)
        self.overlay.invalidate(full)
        self.refresh_properties(); self.sync_actions()

    def layer_target(self):
        item=self.layer_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def add_layer(self):
        if not self.building: return
        name,ok=QInputDialog.getText(self.window,'Add Layer','Unique layer name:')
        if ok:
            key=self.safe(self.document.new_layer,name)
            if key: self.active=key; self.changed()

    def rename_layer(self):
        if not self.building or not self.layer_target(): return
        key=self.layer_target(); name,ok=QInputDialog.getText(self.window,'Rename Layer','Name:',text=self.document.layers[key].name)
        if ok: self.safe(lambda:self.document.update_layer(key,name=name)); self.changed()

    def color_layer(self):
        if not self.building or not self.layer_target(): return
        key=self.layer_target(); color=QColorDialog.getColor(QColor(self.document.layers[key].color),self.window,'Layer color')
        if color.isValid(): self.document.update_layer(key,color=color.name()); self.changed()

    def activate_layer(self):
        key=self.layer_target()
        if key and self.document.layers[key].visible:
            self.cancel(); self.active=key; self.changed(); self.globe.setFocus()
    def clear_active(self): self.cancel(); self.active=None; self.changed()
    def toggle_layer(self):
        if not self.building or not self.layer_target(): return
        key=self.layer_target(); self.cancel()
        self.document.update_layer(key,visible=not self.document.layers[key].visible); self.changed()
    def reorder_layer(self,step):
        if not self.building or not self.layer_target(): return
        order=list(self.document.settings['order']); i=order.index(self.layer_target()); j=i+step
        if 0<=j<len(order):
            self.cancel(); order[i],order[j]=order[j],order[i]
            self.document.setting('order',order,'Reorder layers'); self.changed()
    def delete_layer(self):
        if not self.building or not self.layer_target(): return
        key=self.layer_target(); d=self.document
        nodes=sum(n.layer==key for n in d.nodes.values()); edges=[e for e in d.edges.values() if e.layer==key]
        if QMessageBox.question(self.window,'Delete Layer?',f'Are you sure you want to delete “{d.layers[key].name}”?\n\n{nodes} nodes, {len(edges)} edges and {sum(len(e.waypoints) for e in edges)} shape waypoints will be removed.\nThis is one undoable edit.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)==QMessageBox.StandardButton.Yes:
            self.cancel(); self.safe(d.delete_layer,key); self.changed()

    def select(self,key,hits=None):
        if isinstance(key,tuple): key=key[0]
        if self.selected!=key: self.reveal=False
        self.selected=key; self.overlaps=list(dict.fromkeys(k[0] if isinstance(k,tuple) else k for k in (hits or ([key] if key else []))))
        self.refresh_properties(); self.sync_actions(); self.overlay.geometry_revision=-1; self.overlay.schedule()

    def choose_overlap(self,index):
        if index<0: return
        key=self.candidates.itemData(index)
        if key and key!=self.selected: self.select(key,self.overlaps)

    def refresh_properties(self):
        d=self.document; obj=d.nodes.get(self.selected) or d.edges.get(self.selected)
        self.candidates.blockSignals(True); self.candidates.clear()
        for key in self.overlaps:
            o=d.nodes.get(key) or d.edges.get(key)
            if o:
                self.candidates.addItem(d.label(o)+' · '+o.id[:8],key)
                if key==self.selected: self.candidates.setCurrentIndex(self.candidates.count()-1)
        self.candidates.blockSignals(False)
        editable=bool(obj and self.can_edit(obj.id)); node=isinstance(obj,Node); edge=isinstance(obj,Edge)
        for widget in (self.name,self.kind,self.longitude,self.latitude,self.directed,self.weight_mode,self.weight_value,self.weight_scale,self.weight_unit,self.attributes,self.waypoints): widget.setEnabled(editable)
        self.apply_button.setEnabled(editable)
        for w in (self.kind,self.longitude,self.latitude): w.setEnabled(editable and node)
        for w in (self.directed,self.weight_mode,self.weight_value,self.weight_scale,self.weight_unit,self.waypoints): w.setEnabled(editable and edge)
        if not obj:
            self.identity.setText('Select an object on the globe.'); self.name.clear(); self.attributes.setPlainText('{}'); self.waypoints.setRowCount(0); return
        self.identity.setText(f'{d.label(obj)}\nLayer: {d.layers[obj.layer].name}\nID: {obj.id}\n'+('Editable' if editable else 'Read-only'))
        self.name.setText(obj.name); self.attributes.setPlainText(json.dumps(obj.attributes,ensure_ascii=False,indent=2))
        self.waypoints.setRowCount(0)
        if node:
            self.longitude.setValue(obj.lon); self.latitude.setValue(obj.lat); self.kind.setText(obj.kind)
            self.length_label.setText('—'); self.weight_label.setText('—')
        else:
            self.kind.clear(); self.directed.setChecked(obj.directed)
            self.length_label.setText(f'{d.edge_length(obj):,.2f} m (spherical)')
            self.weight_mode.setCurrentIndex(('unassigned','manual','length').index(obj.weight_mode))
            self.weight_value.setText(str(obj.weight_value)); self.weight_scale.setText(str(obj.weight_scale)); self.weight_unit.setText(obj.weight_unit)
            value=d.weight(obj); self.weight_label.setText('Unassigned' if value is None else f'{value:g} {obj.weight_unit}')
            self.waypoints.setRowCount(len(obj.waypoints))
            for i,w in enumerate(obj.waypoints):
                self.waypoints.setItem(i,0,QTableWidgetItem(str(w.lon))); self.waypoints.setItem(i,1,QTableWidgetItem(str(w.lat)))

    def validate_attributes(self,attrs):
        self.document.check_attributes(attrs)
        for key,value in attrs.items():
            definition=self.document.settings['definitions'].get(key)
            if definition:
                kind='boolean' if isinstance(value,bool) else 'text' if isinstance(value,str) else 'list' if isinstance(value,list) else 'number'
                if kind!=definition['type']: raise ValueError(f'Attribute {key} requires {definition["type"]}')

    def apply_properties(self):
        self.require_edit(self.selected)
        attrs=json.loads(self.attributes.toPlainText(),object_pairs_hook=persistence.no_duplicates)
        self.validate_attributes(attrs)
        if self.selected in self.document.nodes:
            self.document.update_node(self.selected,name=self.name.text(),kind=self.kind.text().strip() or 'generic',lon=self.longitude.value(),lat=self.latitude.value(),attributes=attrs)
        else:
            old=self.document.edges[self.selected]
            points=[Waypoint(w.id,*coordinate(float(self.waypoints.item(i,0).text()),float(self.waypoints.item(i,1).text()))) for i,w in enumerate(old.waypoints)]
            self.document.update_edge(self.selected,name=self.name.text(),directed=self.directed.isChecked(),waypoints=points,attributes=attrs,
                weight_mode=('unassigned','manual','length')[self.weight_mode.currentIndex()],weight_value=float(self.weight_value.text()),
                weight_scale=float(self.weight_scale.text()),weight_unit=self.weight_unit.text())
        self.changed()

    def definitions(self):
        if not self.building: return
        dialog=QDialog(self.window); dialog.setWindowTitle('Attribute Definitions'); layout=QVBoxLayout(dialog)
        layout.addWidget(QLabel('Define keys as {type, label, unit, description}. Types: text, number, boolean, list.'))
        text=QPlainTextEdit(json.dumps(self.document.settings['definitions'],indent=2)); text.setMinimumSize(560,320); layout.addWidget(text)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel); layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject)
        if dialog.exec():
            def apply():
                definitions=json.loads(text.toPlainText(),object_pairs_hook=persistence.no_duplicates)
                data=self.document.to_dict(); data['display']['definitions']=definitions
                Document.from_dict(data)
                for obj in [*self.document.nodes.values(),*self.document.edges.values()]:
                    for key,value in obj.attributes.items():
                        if key in definitions:
                            kind='boolean' if isinstance(value,bool) else 'text' if isinstance(value,str) else 'list' if isinstance(value,list) else 'number'
                            if definitions[key]['type']!=kind: raise ValueError('Definition conflicts with existing attribute '+key)
                self.document.setting('definitions',definitions,'Edit attribute definitions'); self.changed()
            self.safe(apply)

    def place_coordinates(self):
        if not self.can_edit(): return
        text,ok=QInputDialog.getText(self.window,'Place Node','Longitude, latitude (degrees):')
        if ok:
            def add():
                coords=coordinate(*[float(v.strip()) for v in text.split(',')]); key=self.document.add_node(self.active,*coords); self.changed(); self.select(key)
            self.safe(add)

    def insert_waypoint(self):
        if not self.can_edit(self.selected) or self.selected not in self.document.edges: return
        edge=self.document.edges[self.selected]
        text,ok=QInputDialog.getText(self.window,'Insert Shape Waypoint','Insert index (0 = first), longitude, latitude:')
        if ok:
            def insert():
                parts=text.split(',')
                if len(parts)!=3: raise ValueError('Enter index, longitude, latitude')
                index=int(parts[0]); coords=coordinate(float(parts[1]),float(parts[2]))
                if len(parts)!=3 or not 0<=index<=len(edge.waypoints): raise ValueError('Invalid insertion index')
                points=list(edge.waypoints); points.insert(index,Waypoint(uid(),*coords)); self.document.update_edge(edge.id,waypoints=points); self.changed()
            self.safe(insert)
    def remove_waypoint(self):
        if not self.can_edit(self.selected) or self.selected not in self.document.edges: return
        row=self.waypoints.currentRow(); e=self.document.edges[self.selected]
        if 0<=row<len(e.waypoints): self.document.update_edge(e.id,waypoints=e.waypoints[:row]+e.waypoints[row+1:]); self.changed()
        else: self.message='Select a waypoint row in Properties first.'; self.show_properties()
    def reverse(self):
        if self.can_edit(self.selected) and self.selected in self.document.edges:
            e=self.document.edges[self.selected]; self.document.update_edge(e.id,source=e.target,target=e.source,waypoints=list(reversed(e.waypoints))); self.changed()
    def delete_selected(self):
        if not self.can_edit(self.selected): return
        key=self.selected
        if key in self.document.nodes:
            count=len(self.document.adjacency[key])
            if count and QMessageBox.question(self.window,'Delete Node?',f'Delete this node and its {count} incident edges?\nUndo restores the complete deletion.')!=QMessageBox.StandardButton.Yes: return
        self.cancel(); self.document.delete_object(key); self.changed()
    def undo(self):
        if self.building and not self.reader: self.cancel(); self.document.undo(); self.changed()
    def redo(self):
        if self.building and not self.reader: self.cancel(); self.document.redo(); self.changed()
    def pin(self):
        if not self.building or not self.selected: return
        pins=list(self.document.settings['pins'])
        if self.selected in pins: pins.remove(self.selected)
        else: pins.append(self.selected)
        self.document.setting('pins',pins,'Pin / unpin object'); self.changed()
    def reveal_neighbors(self): self.reveal=self.selected in self.document.nodes; self.overlay.schedule(); self.sync_actions()
    def clear_reveal(self): self.reveal=False; self.overlay.schedule(); self.sync_actions()
    def toggle_declutter(self,value):
        if self.building: self.document.setting('declutter',bool(value),'Change decluttering'); self.changed()
        else: self.sync_checks()
    def toggle_dim(self,value):
        if self.building: self.document.setting('dim',0.45 if value else 0.0,'Change basemap dimming'); self.changed()
        else: self.sync_checks()
    def toggle_panel(self,value): self.dock.setVisible(value)
    def show_properties(self): self.dock.show(); self.tabs.setCurrentIndex(1); self.refresh_properties(); self.sync_checks()
    def show_stats(self):
        s=self.overlay.stats
        QMessageBox.information(self.window,'Graph Display Capacity',f'Displayed nodes: {s.get("nodes",0)} / 1200\nEligible edges: {s.get("edges",0)} / 1200\nClipped segments: {s.get("segments",0)}\nGeometry cache: {s.get("cache_mib",0):.2f} / 32 MiB\nDerived vertex budget: 120,000\nUndo commands: {len(self.document.history)} / 200\nUndo bytes: {sum(c.size for c in self.document.history)/1024**2:.2f} / 32 MiB\nOlder undo entries discarded: {self.document.history_trimmed}\n\nDisplay limits never remove graph data. Use layers and zoom to inspect dense areas.')

    def cancel(self):
        self.ghost=None; self.press=None; self.move_key=None; self.move_preview=None; self.dragged=False
        self.draft_source=None; self.draft_points=[]; self.message=''
        if hasattr(self,'overlay'): self.overlay.update()
    def cancel_drag(self):
        self.press=None; self.move_key=None; self.move_preview=None; self.dragged=False; self.ghost=None; self.overlay.update()
    def focus_lost(self): self.cancel_drag()
    def camera_changed(self):
        self.overlay.schedule()
        # Ghost projection must use the new camera immediately, not the queued overlay.
        from .geometry import Projection
        self.overlay.projection=Projection(self.globe.navigation,self.globe.width(),self.globe.height())
        if self.pointer is not None: self.update_ghost(self.pointer)
    def update_ghost(self,pos):
        self.pointer=QPointF(pos)
        self.ghost=self.overlay.projection.pick(pos.x(),pos.y()) if self.can_edit() and self.tool in ('node','edge') else None
        self.overlay.update()

    def pointer_press(self,pos):
        self.pointer=QPointF(pos); self.press=QPointF(pos); self.dragged=False; self.move_key=None
        hits=self.overlay.hits(pos.x(),pos.y())
        if self.tool=='select' or not self.building:
            hit=hits[0] if hits else None; self.select(hit,hits)
            key=hit[0] if isinstance(hit,tuple) else hit
            if hit and self.can_edit(key) and (isinstance(hit,tuple) or key in self.document.nodes):
                self.move_key=hit
                if isinstance(hit,tuple):
                    w=next(w for w in self.document.edges[key].waypoints if w.id==hit[1]); coords=(w.lon,w.lat)
                else:
                    n=self.document.nodes[key]; coords=(n.lon,n.lat)
                anchor=self.overlay.projection.project(unit([coords]))[0]
                self.grab_offset=QPointF(pos.x()-anchor[0],pos.y()-anchor[1])

    def pointer_move(self,pos):
        self.pointer=QPointF(pos)
        if self.press is not None and (pos-self.press).manhattanLength()>=QApplication.startDragDistance(): self.dragged=True
        if self.move_key and self.dragged:
            coords=self.overlay.projection.pick(pos.x()-self.grab_offset.x(),pos.y()-self.grab_offset.y())
            if coords: self.move_preview=coords
            self.overlay.update()
        else: self.update_ghost(pos)

    def pointer_release(self,pos):
        if self.press is None: return
        dragged=self.dragged or (pos-self.press).manhattanLength()>=QApplication.startDragDistance()
        self.press=None
        if self.move_key and dragged:
            key=self.move_key; coords=self.move_preview
            if coords:
                def commit():
                    objid=key[0] if isinstance(key,tuple) else key; self.require_edit(objid)
                    if isinstance(key,tuple):
                        e=self.document.edges[objid]; points=[replace(w,lon=coords[0],lat=coords[1]) if w.id==key[1] else w for w in e.waypoints]
                        self.document.update_edge(objid,waypoints=points)
                    else: self.document.update_node(objid,lon=coords[0],lat=coords[1])
                self.safe(commit); self.changed()
            self.move_key=None; self.move_preview=None; self.overlay.update(); return
        self.move_key=None
        if dragged or not self.can_edit(): return
        coords=self.overlay.projection.pick(pos.x(),pos.y())
        if coords is None: return
        if self.tool=='node':
            key=self.safe(self.document.add_node,self.active,*coords)
            if key: self.changed(); self.select(key)
        elif self.tool=='edge':
            hits=self.overlay.hits(pos.x(),pos.y()); hit=hits[0] if hits else None
            if isinstance(hit,tuple): hit=hit[0]
            if hit:
                if hit not in self.document.nodes or not self.can_edit(hit):
                    self.message='Choose a node in the active topmost layer; covering objects block picking.'; self.update_status_only(); return
                if self.draft_source is None: self.draft_source=hit; self.draft_points=[]
                else:
                    a=self.draft_source; b=hit
                    if a==b: self.message='Self-loops are deferred; choose another node.'; self.update_status_only(); return
                    duplicates=[e for e in self.document.edges.values() if not e.directed and {e.source,e.target}=={a,b}]
                    if duplicates and QMessageBox.question(self.window,'Create Another Edge?',f'{len(duplicates)} undirected connection(s) already join these nodes. Create a distinct additional edge?')!=QMessageBox.StandardButton.Yes: return
                    key=self.safe(self.document.add_edge,a,b,self.draft_points)
                    if key: self.draft_source=None; self.draft_points=[]; self.changed(); self.select(key)
            elif self.draft_source:
                if len(self.draft_points)<Document.MAX_WAYPOINTS: self.draft_points.append(coords)
                else: self.message='Waypoint limit reached.'
        self.update_ghost(pos); self.update_status_only()

    def preview_routes(self):
        if not self.move_key or not self.move_preview: return []
        d=self.document; key=self.move_key; coords=self.move_preview
        if isinstance(key,tuple):
            e=d.edges[key[0]]; points=d.route(e)
            for i,w in enumerate(e.waypoints):
                if w.id==key[1]: points[i+1]=coords
            return [points]
        result=[]
        for eid in d.adjacency[key]:
            e=d.edges[eid]; points=d.route(e)
            if e.source==key: points[0]=coords
            if e.target==key: points[-1]=coords
            result.append(points)
        return result

    def maybe_save(self):
        if not self.document.dirty: return True
        answer=QMessageBox.question(self.window,'Unsaved Graph Project','Save changes before continuing?',QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Save)
        if answer==QMessageBox.StandardButton.Cancel: return False
        return self.save() if answer==QMessageBox.StandardButton.Save else True
    def install_document(self,doc,path=None):
        self.cancel(); self.document=doc; self.path=path; self.active=None; self.selected=None; self.overlaps=[]; self.reveal=False
        self.changed(full=True)
    def new_project(self):
        if self.reader or not self.maybe_save(): return
        self.install_document(Document())
    def open_project(self):
        if self.reader or not self.maybe_save(): return
        path,_=QFileDialog.getOpenFileName(self.window,'Open Graph Project','','StrataScry graph (*.ssg.json *.json)')
        if not path: return
        self.cancel(); self.reader=ProjectReader(path,self)
        self.reader.loaded.connect(self.install_document)
        self.reader.failed.connect(lambda message:QMessageBox.warning(self.window,'Cannot Open Project',message))
        self.reader.finished.connect(self.reader_finished); self.reader.start(); self.sync_actions()
    def reader_finished(self):
        worker=self.reader; self.reader=None
        if worker: worker.deleteLater()
        self.sync_actions()
    def save(self,save_as=False):
        if self.reader: return False
        path=self.path
        if not path or save_as:
            path,_=QFileDialog.getSaveFileName(self.window,'Save Graph Project',path or 'Untitled.ssg.json','StrataScry graph (*.ssg.json)')
            if not path: return False
            if not path.endswith('.json'): path+='.ssg.json'
        try: persistence.save(self.document,path)
        except (ValueError,OSError) as e:
            QMessageBox.warning(self.window,'Cannot Save Project',str(e)); return False
        self.path=path; self.sync_actions(); return True
    def request_close(self):
        if self.reader:
            self.message='Wait for project validation to finish before closing.'; self.update_status_only(); return False
        if not self.closing:
            if not self.maybe_save(): return False
            self.closing=True; self.cancel(); self.overlay.timer.stop()
        return True
