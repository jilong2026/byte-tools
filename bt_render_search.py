"""离屏渲染主窗口：验证搜索条的位置与过滤后的可见卡片数。

截图只能看布局（本机 offscreen 平台中文会渲染成方框，是已知现象，不代表回归）；
所以这里同时用代码断言几何与可见性，不靠眼睛判断。
"""
import importlib.util
import platform
import sys

platform._wmi_query = lambda *_a, **_k: (_ for _ in ()).throw(OSError("stub"))
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

spec = importlib.util.spec_from_file_location(
    "btmain", os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py"))
main = importlib.util.module_from_spec(spec)
sys.modules["btmain"] = main
spec.loader.exec_module(main)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
main.MainWindow._start_fetch_versions = lambda self, *a, **k: None
main.ComponentCard._detect_status = lambda self, *a, **k: None

win = main.MainWindow()
win.resize(1180, 780)
win.show()
app.processEvents()

OUT = r"C:\Users\E5430\AppData\Local\Temp"


def snap(name):
    pix = win.grab()
    path = f"{OUT}\\{name}.png"
    pix.save(path, "PNG")
    print("saved", path, pix.width(), "x", pix.height())


def state(tag):
    vis = [c.component.key for c in win.cards if not c.isHidden()]
    labels = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    print(f"{tag:22} 可见 {len(vis):2} 当前Tab={win.tabs.currentIndex()} "
          f"标题={labels} keys={vis}")
    return vis


# 1) 默认全量
all_vis = state("默认")
snap("search_0_默认")
box = win.search_box
from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QTabWidget  # noqa: E402


def win_top(w):
    """控件在窗口坐标系里的顶边（geometry() 是相对父件的，不能直接比）。"""
    return w.mapTo(win, QPoint(0, 0)).y()


print(f"搜索框 windowY={win_top(box)}  标题栏底={win_top(win.title_bar) + win.title_bar.height()}  "
      f"Tab 顶={win_top(win.tabs)}")
print("搜索框在标题栏之下、Tab 之上：",
      win_top(win.title_bar) + win.title_bar.height() <= win_top(box) < win_top(win.tabs))
node, inside_tab = box.parent(), False
while node is not None:
    if isinstance(node, QTabWidget):
        inside_tab = True
    node = node.parent()
print("搜索框不在任何 Tab 页里（父链无 QTabWidget）：", not inside_tab)

# 2) 搜「sql」
win.search_box.setText("sql")
app.processEvents()
state("搜索 sql")
snap("search_1_sql")

# 3) 搜 nginx（新组件）
win.search_box.setText("nginx")
app.processEvents()
state("搜索 nginx")
snap("search_2_nginx")

# 4) 大小写 + key 命中（powershell 的显示名是 PowerShell 7）
win.search_box.setText("POWERSHELL")
app.processEvents()
state("搜索 POWERSHELL")

# 5) 无结果
win.search_box.setText("zzzz")
app.processEvents()
state("无结果")
snap("search_3_无结果")

# 6) 清空恢复
win.search_box.setText("")
app.processEvents()
back = state("清空后")
print("恢复完整：", back == all_vis, len(back))
snap("search_4_清空")
