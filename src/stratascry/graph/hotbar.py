# SPDX-License-Identifier: Apache-2.0
"""Extensible graph tools backed by the controller's existing commands."""
from dataclasses import dataclass
from importlib.resources import files

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QToolBar, QToolButton


@dataclass(frozen=True)
class ToolChoice:
    action: str
    label: str


@dataclass(frozen=True)
class ToolSpec:
    action: str
    label: str
    icon: str
    description: str
    choices: tuple[ToolChoice, ...] = ()


GRAPH_TOOLS = (
    ToolSpec('select', 'Select / Move', 'select-move.svg',
             'Select an object; drag an editable node or shape handle to move it.'),
    ToolSpec('node', 'Add Node', 'add-node.svg',
             'Click on the globe to place a node. Click this selected tool again for placement options.',
             (ToolChoice('node', 'Add node by clicking'),
              ToolChoice('coordinate', 'Add node by coordinates…'))),
    ToolSpec('edge', 'Add Edge', 'add-edge.svg',
             'Click a source node, optional shape points, then a target node.'),
)


class GraphHotbar(QToolBar):
    """Normal toolbar actions retain Qt's overflow and keyboard behavior.

    Presentation actions give menu choices their own labels without renaming
    shared commands. Checked/enabled state always comes from those commands;
    clicking an already selected tool opens its options instead of toggling it.
    """
    def __init__(self, controller, specs=GRAPH_TOOLS):
        super().__init__('Graph tools', controller.window)
        self.controller = controller
        self.setObjectName('graph_hotbar')
        self.setAccessibleName('Graph tools')
        self.setMovable(False)
        self.setFloatable(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.setIconSize(QSize(22, 22))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setMinimumWidth(0)
        self.buttons = {}
        self.tool_actions = {}
        self.menus = {}
        self.bindings = []
        self.setStyleSheet('''
            QToolBar#graph_hotbar {
                background: #101c2b; border: 0;
                border-bottom: 1px solid #203145; padding: 5px 12px; spacing: 5px;
            }
            QToolBar#graph_hotbar QToolButton {
                background: transparent; color: #d6e6f2; border: 1px solid transparent;
                border-radius: 5px; padding: 6px;
            }
            QToolBar#graph_hotbar QToolButton[hasOptions="true"] { padding-right: 21px; }
            QToolBar#graph_hotbar QToolButton:hover { background: #203449; }
            QToolBar#graph_hotbar QToolButton:checked { background: #18445b; border-color: #459ec1; }
            QToolBar#graph_hotbar QToolButton:focus { border-color: #b2e4fa; }
            QToolBar#graph_hotbar QToolButton:disabled { background: transparent; border-color: transparent; }
            QToolBar#graph_hotbar QToolButton::menu-button {
                border-left: 1px solid #31485e; width: 13px;
            }
        ''')
        for spec in specs:
            action = self._presentation(spec.action, spec.label, self)
            action.setObjectName('hotbar_' + spec.action)
            action.setIcon(QIcon(str(files('stratascry').joinpath('assets/icons', spec.icon))))
            action.setToolTip(spec.label + '\n' + spec.description + '\nB enables graph editing; choose a visible active layer.')
            action.triggered.connect(lambda checked=False, s=spec: self.activate(s))
            if spec.choices:
                menu = QMenu(spec.label, self)
                menu.setObjectName('hotbar_' + spec.action + '_options')
                for choice in spec.choices:
                    item = self._presentation(choice.action, choice.label, menu)
                    item.triggered.connect(lambda checked=False, key=choice.action: self.run_command(key))
                    menu.addAction(item)
                menu.aboutToShow.connect(self.sync)
                menu.aboutToHide.connect(self.controller.globe.setFocus)
                action.setMenu(menu)
                self.menus[spec.action] = menu
            self.addAction(action)
            button = self.widgetForAction(action)
            button.setObjectName('hotbar_button_' + spec.action)
            button.setAccessibleName(spec.label)
            button.setAccessibleDescription(spec.description)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            if spec.choices:
                button.setProperty('hasOptions', True)
                button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
            self.buttons[spec.action] = button
            self.tool_actions[spec.action] = action
        for key in {key for _, key in self.bindings}:
            controller.actions[key].changed.connect(self.sync)
        self.sync()

    def _presentation(self, key, label, parent):
        action = QAction(label, parent)
        action.setCheckable(self.controller.actions[key].isCheckable())
        self.bindings.append((action, key))
        return action

    def sync(self):
        for action, key in self.bindings:
            command = self.controller.actions[key]
            action.setEnabled(command.isEnabled())
            action.setChecked(command.isChecked())
        for key, menu in self.menus.items():
            if not self.controller.actions[key].isEnabled():
                menu.hide()

    def activate(self, spec):
        command = self.controller.actions[spec.action]
        self.sync()  # Undo the presentation action's own automatic check toggle.
        if not command.isEnabled():
            return
        if command.isChecked() and spec.action in self.menus:
            button = self.buttons[spec.action]
            self.menus[spec.action].popup(button.mapToGlobal(QPoint(0, button.height())))
        else:
            self.run_command(spec.action)

    def run_command(self, key):
        command = self.controller.actions[key]
        if command.isEnabled():
            command.trigger()
        self.sync()
        self.controller.globe.setFocus()
