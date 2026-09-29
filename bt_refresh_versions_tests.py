"""「刷新版本」按钮端到端链路测试（离线、确定性、不联网）。

验证 _start_fetch_versions 在我这次改造后仍然工作正常：
  - 按钮点击 → 错峰启动 VersionFetchWorker（不再 24 路并发打爆 GitHub）
  - 抓取成功 → card.set_versions() 用在线列表覆盖内置清单
  - 抓取失败（模拟官网获取失败）→ 保留内置默认清单，并打印降级日志
  - 全部完成后按钮恢复「⟳ 刷新版本」、日志打印「版本列表获取完成」
  - 重复点击（错峰未启动时）被「请稍候」守卫拦下，不会重复派发

做法：用假 FETCHERS 替换真实抓取器（真实抓取器会联网），完全避免网络。
"""

import os
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = r"E:\file\test\byte-tools"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import main  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


FAIL_KEY = "rabbitmq"  # 故意让它抛异常，模拟「官网版本获取失败」


class RefreshVersionsFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        # 关掉 MainWindow 构造期间的「已装版本探测」网络行为
        cls._orig_detect = main.ComponentCard._detect_status
        main.ComponentCard._detect_status = lambda self, *a, **k: None
        # 关掉构造期可能自动触发的版本抓取（避免真实联网）；测试里显式调用真实方法
        cls._orig_fetch = main.MainWindow._start_fetch_versions
        main.MainWindow._start_fetch_versions = lambda self, *a, **k: None
        cls.win = main.MainWindow()
        cls._orig_fetchers = main.FETCHERS

    @classmethod
    def tearDownClass(cls):
        main.FETCHERS = cls._orig_fetchers
        main.ComponentCard._detect_status = cls._orig_detect
        main.MainWindow._start_fetch_versions = cls._orig_fetch
        cls.win.deleteLater()

    def setUp(self):
        self.logs = []
        self.set_versions_calls = []
        self._orig_append = self.win._append_log

        def _rec(level, msg):
            self.logs.append((level, msg))
            return self._orig_append(level, msg)

        self.win._append_log = _rec

        # 记录 set_versions 被哪些组件调用
        self._orig_setv = main.ComponentCard.set_versions

        def _spy(self_card, versions):
            self.set_versions_calls.append(self_card.component.key)
            return self._orig_setv(self_card, versions)

        main.ComponentCard.set_versions = _spy

        self.win._fetch_pending = 0
        self.win._fetch_workers = []

        # 假 FETCHERS：除 FAIL_KEY 抛异常外，其余返回各自内置版本列表（List[ComponentVersion]）
        fake = {}
        for card in self.win.cards:
            key = card.component.key
            if key == FAIL_KEY:
                def _raise():
                    raise RuntimeError("simulated upstream failure")
                fake[key] = _raise
            else:
                # 用默认参数捕获 card，返回内置版本的副本，走 set_versions 成功路径
                fake[key] = (lambda c: (lambda: list(c.component.versions)))(card)
        main.FETCHERS = fake

    def tearDown(self):
        main.ComponentCard.set_versions = self._orig_setv
        self.win._append_log = self._orig_append

    # ---- 工具 ----
    def _pump_until_done(self, timeout=25):
        deadline = time.time() + timeout
        while self.win._fetch_pending > 0 and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.05)
        return time.time() < deadline

    def _run_real_refresh(self):
        """显式调用真实 _start_fetch_versions（绕过类上的 no-op mock）。

        注意：经 self._orig_fetch 访问会被绑定到测试实例，故用类名访问拿回未绑定函数。
        """
        self.__class__._orig_fetch(self.win)

    def test_refresh_completes_and_restores_button(self):
        self._run_real_refresh()
        ok = self._pump_until_done()
        self.assertTrue(ok, "刷新未能在超时内完成（_fetch_pending 未归零）")
        self.assertEqual(self.win._fetch_pending, 0)

        # 按钮恢复
        self.assertTrue(self.win.btn_refresh.isEnabled())
        self.assertEqual(self.win.btn_refresh.text(), "⟳ 刷新版本")

        # 完成日志
        msgs = [m for (_lvl, m) in self.logs]
        self.assertIn("版本列表获取完成。", msgs)

    def test_success_replaces_builtin_and_failure_keeps_it(self):
        rmq = next(c for c in self.win.cards if c.component.key == FAIL_KEY)
        rmq_original = rmq.component.versions  # 抓取前的「内置默认清单」

        self._run_real_refresh()
        self._pump_until_done()

        # 失败组件：set_versions 未被调用，内置清单原样保留
        self.assertNotIn(FAIL_KEY, self.set_versions_calls)
        self.assertIs(rmq.component.versions, rmq_original,
                      "失败组件的版本列表应保留内置默认清单（引用不变）")
        msgs = [m for (_lvl, m) in self.logs]
        # 降级日志打的是组件显示名（RabbitMQ），不是内部 key（rabbitmq）
        name = rmq.component.display_name
        self.assertTrue(
            any(name in m and "官网版本获取失败" in m for m in msgs),
            "应打印失败组件的降级日志",
        )

        # 其余所有组件：set_versions 被调用（在线列表覆盖内置清单）
        ok_keys = {c.component.key for c in self.win.cards if c.component.key != FAIL_KEY}
        self.assertEqual(set(self.set_versions_calls), ok_keys)

    def test_workers_are_staggered_not_burst(self):
        """点下刷新后，所有 worker 应通过 QTimer 错峰启动，而非立即全部 isRunning。"""
        self._run_real_refresh()
        running_right_away = [w.isRunning() for w in self.win._fetch_workers]
        self.assertFalse(any(running_right_away),
                         "不应在点下刷新瞬间就有 worker 在跑（错峰未触发）")
        # 派发的 worker 数量应与有 fetcher 的卡片数一致
        expected = sum(1 for c in self.win.cards if c.component.key in main.FETCHERS)
        self.assertEqual(len(self.win._fetch_workers), expected)
        self.assertEqual(self.win._fetch_pending, expected)
        self._pump_until_done()  # 收尾，避免遗留定时器

    def test_reentry_is_guarded_while_pending(self):
        """错峰未启动期间再次点击，应被「请稍候」守卫拦下，不重复派发。"""
        self._run_real_refresh()
        pending_after_first = self.win._fetch_pending
        workers_after_first = len(self.win._fetch_workers)

        self._run_real_refresh()  # 第二次点击，此时 worker 仍在排期中
        msgs = [m for (_lvl, m) in self.logs]
        self.assertTrue(any("请稍候" in m for m in msgs),
                        "重复点击应打印「请稍候」守卫日志")
        # 不应大于第一次派发的量（守卫直接 return，不新增 worker / 不重置 pending）
        self.assertLessEqual(self.win._fetch_pending, pending_after_first)
        self.assertEqual(len(self.win._fetch_workers), workers_after_first)
        self._pump_until_done()  # 收尾


if __name__ == "__main__":
    unittest.main(verbosity=2)
