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
import platform as _platform
import sys
import threading
import time
import unittest

import _btprelude  # noqa: F401  必须早于 import main：打 WMI 桩 + offscreen + sys.path

REPO_ROOT = str(_btprelude.REPO_ROOT)

import main  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


FAIL_KEY = "rabbitmq"  # 故意让它抛异常，模拟「官网版本获取失败」


class RefreshVersionsFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        import tempfile
        cls.app = QApplication.instance() or QApplication([])
        # 抓成功现在会落盘 version_cache.json：不挪走 CONFIG_DIR 就是测试写用户真目录
        cls._tmp = tempfile.TemporaryDirectory()
        cls._orig_dir = main.CONFIG_DIR
        main.CONFIG_DIR = Path(cls._tmp.name)
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
        main.CONFIG_DIR = cls._orig_dir
        cls._tmp.cleanup()
        cls.win.deleteLater()

    def setUp(self):
        self.logs = []
        self.set_versions_calls = []
        main.version_cache_path().unlink(missing_ok=True)   # 上一用例留下的缓存会让本轮 0 派发
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
            if not card.component.versions:
                # 「官网下载」型组件（official_page_only，R21）**没有版本表**，也就永远
                # 没有可抓的清单 —— 生产里 FETCHERS 根本不会登记它们。这里不登记，
                # 否则 `_cached_versions_from` 拿到空列表会判"没缓存"而每轮都重派 worker，
                # 与"缓存新鲜就一个线程都不起"这条断言假冲突。
                continue
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

        # 其余所有组件：set_versions 被调用（在线列表覆盖内置清单）。
        # 排除 FAIL_KEY，以及**没有版本表**的组件（official_page_only）：它们没有 fetcher，
        # 抓取流程压根不会碰它们（见 setUp 里注册假 fetcher 时的同一条跳过）。
        ok_keys = {c.component.key for c in self.win.cards
                   if c.component.key != FAIL_KEY and c.component.versions}
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


class VersionListCache(unittest.TestCase):
    """GitHub 匿名额度是 60 次/小时/IP，而本工具一次启动要打 26 次 api.github.com。

    2026-10-11 本机实测：`api.github.com/rate_limit` 回 `remaining=0/60`，用户日志里
    11 个组件集体"官网版本获取失败"，真实原因（限流）只在 stdout 打了一句 ——
    打包成 exe 后没有控制台，那句话永远不会出现在界面上。
    所以这一层要保证：**当天抓过的清单不再重抓**、**刷新按钮仍能强制重抓**、
    **额度用尽时快速失败并把原因说进日志**。
    """

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        import tempfile
        cls.app = QApplication.instance() or QApplication([])
        cls._orig_detect = main.ComponentCard._detect_status
        main.ComponentCard._detect_status = lambda self, *a, **k: None
        cls._orig_fetch = main.MainWindow._start_fetch_versions
        main.MainWindow._start_fetch_versions = lambda self, *a, **k: None
        # 缓存文件写在 CONFIG_DIR 下：不挪走就是测试写真用户的 ~/.env-tools
        cls._tmp = tempfile.TemporaryDirectory()
        cls._orig_dir = main.CONFIG_DIR
        main.CONFIG_DIR = Path(cls._tmp.name)
        cls.win = main.MainWindow()
        cls._orig_fetchers = main.FETCHERS

    @classmethod
    def tearDownClass(cls):
        main.FETCHERS = cls._orig_fetchers
        main.ComponentCard._detect_status = cls._orig_detect
        main.MainWindow._start_fetch_versions = cls._orig_fetch
        main.CONFIG_DIR = cls._orig_dir
        cls._tmp.cleanup()
        cls.win.deleteLater()

    def setUp(self):
        main.version_cache_path().unlink(missing_ok=True)
        self.logs = []
        self.set_versions_calls = []
        self._orig_append = self.win._append_log
        self.win._append_log = lambda level, msg: self.logs.append((level, msg))
        self._orig_setv = main.ComponentCard.set_versions

        def _spy(self_card, versions):
            self.set_versions_calls.append((self_card.component.key, versions))
            return self._orig_setv(self_card, versions)

        main.ComponentCard.set_versions = _spy
        self.win._fetch_pending = 0
        self.win._fetch_workers = []
        fake = {}
        for card in self.win.cards:
            key = card.component.key
            if not card.component.versions:
                # 同 RefreshVersionsFlow.setUp：没有版本表的组件（official_page_only，
                # R21）生产里不会登记 fetcher，这里也不登记 —— 否则空清单永远"缓存不命中"，
                # "缓存新鲜就零派发"那条断言会假红。
                continue
            fake[key] = (lambda c: (lambda: list(c.component.versions)))(card)
        main.FETCHERS = fake
        self._fake_fetchers = fake

    def tearDown(self):
        main.ComponentCard.set_versions = self._orig_setv
        self.win._append_log = self._orig_append

    def _run_real(self, **kw):
        self.__class__._orig_fetch(self.win, **kw)

    def _pump(self, timeout=25):
        deadline = time.time() + timeout
        while self.win._fetch_pending > 0 and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.05)
        return time.time() < deadline

    def test_refresh_writes_cache_and_cached_versions_reload_as_objects(self):
        """抓成功要能存下来，取回来必须还是可用的 ComponentVersion
        （url_map / url_list_map 丢了就等于"看得见点不动"）。"""
        self._run_real()
        self.assertTrue(self._pump(), "刷新没在超时内完成")
        self.assertTrue(main.version_cache_path().exists(), "抓成功却没落盘")
        data = main.load_version_cache()
        self.assertIn("jdk", data)
        # 读回来喂给卡片，再核对下载 URL 还在
        rows = main.cached_versions_for("jdk", now=time.time())
        self.assertTrue(rows, "缓存里读不回 jdk 的清单")
        card = next(c for c in self.win.cards if c.component.key == "jdk")
        want = [v.version for v in card.component.versions]
        self.assertEqual([v.version for v in rows], want)
        for v in rows:
            self.assertTrue(isinstance(v, main.ComponentVersion), "缓存还原必须是数据类不是 dict")
        first = rows[0]
        self.assertTrue(first.urls_for_current() if hasattr(first, "urls_for_current") else True)

    def test_fresh_cache_skips_network_and_still_fills_the_cards(self):
        """缓存新鲜时：**一个抓取线程都不许起、一个 fetcher 都不许被调用**，
        但卡片必须拿到缓存里的清单（不然界面还是空下拉框）。"""
        self._run_real()
        self.assertTrue(self._pump())
        for card in self.win.cards:
            card.set_versions([])                    # 抹掉上一轮结果，证明下面这轮是缓存喂的
        self.set_versions_calls.clear()
        self.win._fetch_workers.clear()

        # fetcher 仍然注册着，但换成"被调用就记一笔"的假实现：
        # 直接把 FETCHERS 清空的话卡片会因为"没有 fetcher"被跳过，测不到缓存那一支
        hits = []
        main.FETCHERS = dict(self._fake_fetchers)
        for k in list(main.FETCHERS):
            main.FETCHERS[k] = (lambda k=k: (hits.append(k), list(
                next(c.component.versions for c in self.win.cards
                     if c.component.key == k)))[1])

        self._run_real()                             # 默认走缓存
        self.assertEqual(self.win._fetch_workers, [], "清单还是新鲜的，不该再派抓取线程")
        self.assertEqual(hits, [], f"缓存命中还调用了 fetcher：{hits[:5]}")
        keys = {k for k, _v in self.set_versions_calls}
        self.assertIn("jdk", keys, "缓存命中时也要把清单喂回卡片")
        msgs = [m for (_lvl, m) in self.logs]
        self.assertTrue(any("沿用" in m for m in msgs), f"要说清这次没打网络：{msgs}")

    def test_refresh_button_bypasses_the_fresh_cache(self):
        """用户点「⟳ 刷新版本」就是要重抓：缓存再新鲜也必须打网络。"""
        self._run_real()
        self.assertTrue(self._pump())
        self.win._fetch_workers.clear()
        main.FETCHERS = self._fake_fetchers

        self._run_real(force=True)
        self.assertTrue(self.win._fetch_workers, "force=True 还走缓存，按钮就永远刷不动")
        self._pump()

    def test_button_wiring_does_not_swallow_checked_argument(self):
        """QPushButton.clicked 会把 checked=False 当第一个实参传进来。
        直接 `connect(self._start_fetch_versions)` 的话，那个 False 就落进 force，
        于是"点刷新"等于"用缓存"，用户怎么点都刷不动 —— 必须显式包一层。"""
        import inspect
        src = inspect.getsource(main.MainWindow._build_ui)
        self.assertNotIn("clicked.connect(self._start_fetch_versions)", src,
                         "裸 connect 会把 checked=False 当 force 传进去")
        self.assertIn("self._start_fetch_versions(force=True)", src,
                      "刷新按钮没接强制重抓")

    def test_corrupt_cache_is_ignored_not_fatal(self):
        main.version_cache_path().parent.mkdir(parents=True, exist_ok=True)
        main.version_cache_path().write_text("{这不是 JSON", encoding="utf-8")
        main.FETCHERS = self._fake_fetchers
        self._run_real()                              # 坏了就退回正常抓取，不能抛
        self.assertTrue(self.win._fetch_workers, "缓存坏了应该照常抓取，而不是打不开")
        self._pump()

    def test_request_stub_point_is_main_http_session(self):
        """请求必须经由 main.http_session() 发出，而不是裸 requests.get。

        这不是风格问题，是**正确性**：全套测试都靠替换
        `main.http_session` / `main._get` / `main._github_api_json` 这几个
        接缝来保证"不联网"。2026-10-14 把请求改成走线程本地 Session 复用连接
        之后，有两处用例的桩还挂在 `main.requests.get` 上 —— 桩静默失效，
        用例照样跑完，只是**网络真出去了**，报出来的是 404 / 连接超时这类
        与被测行为无关的失败（实测踩过一次）。

        所以这里直接把"代码里不该再出现裸 requests.get"钉住。
        """
        import inspect
        offenders = []
        for name, obj in vars(main).items():
            if name.startswith("__"):
                continue
            if inspect.isfunction(obj) and getattr(obj, "__module__", None) == main.__name__:
                try:
                    src = inspect.getsource(obj)
                except (OSError, TypeError):
                    continue
                if "requests.get(" in src:
                    offenders.append(name)
        self.assertEqual(
            offenders, [],
            f"这些函数还在裸调 requests.get（不走 http_session，连接池无法复用，"
            f"且测试桩挂不住）：{offenders}",
        )

    def test_http_session_is_thread_local(self):
        """每个线程拿到自己的 Session —— Session 不是线程安全的。"""
        import threading
        sess = main.http_session()
        self.assertIs(sess, main.http_session(),
                      "同一线程两次调用应拿到同一个 Session（连接才能复用）")
        self.assertEqual(sess.headers.get("User-Agent"), main.HTTP_UA["User-Agent"],
                         "Session 上必须带专用 UA：部分高校镜像站对默认 UA 一律 403")

        box = {}

        def _other():
            box["sess"] = main.http_session()

        t = threading.Thread(target=_other)
        t.start()
        t.join(5)
        self.assertIn("sess", box, "另一个线程没拿到 Session")
        self.assertIsNot(box["sess"], sess,
                         "跨线程拿到了同一个 Session —— 连接池会被并发使用，是 bug")

    def test_fetch_concurrency_gate_exists(self):
        """版本抓取必须有并发上限。

        错峰定时器只解决"同一瞬间齐发"，不解决"87 条长时间同时在飞"；
        而 GitHub 匿名 API 是每 IP 每小时 60 次，其中 30 多个 fetcher 直连它。
        首启与「⟳ 刷新版本」都会瞬间打满，剩余组件拿到 403 集体降级到内置清单，
        现象是"明明联网了却版本很旧"。
        """
        self.assertGreater(
            main.VERSION_FETCH_CONCURRENCY, 1,
            "并发上限被设成 1 —— 87 个组件会串成 87 轮，慢到不能忍",
        )
        self.assertLessEqual(
            main.VERSION_FETCH_CONCURRENCY, 16,
            "并发上限过高：GitHub 匿名额度是每 IP 每小时 60 次，"
            "同时在飞太多会直接打满",
        )

    def test_rate_limit_fails_fast_for_the_rest_of_the_batch(self):
        """命中 403 remaining=0 之后还按 5s/10s 退避重试 = 每个组件白等 31 秒、
        并且继续烧已经见底的额度。第一次看见限流就该立旗，后面快速失败。"""
        orig_session, orig_abort = main.http_session, main.FETCH_ABORT
        self.addCleanup(setattr, main, "http_session", orig_session)
        self.addCleanup(main.FETCH_ABORT.clear)
        main.FETCH_ABORT.clear()
        calls = []

        class Resp:
            status_code = 403
            headers = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "20"}

            def raise_for_status(self):
                raise RuntimeError("403 rate limited")

            def json(self):
                return {}

        class _Sess:
            def get(self, url, *a, **k):
                calls.append(url)
                return Resp()

        # 2026-10-14：桩点从 main.requests.get 移到 main.http_session ——
        # 请求改走线程本地 Session 复用连接。桩挂在旧位置会**静默失效**，
        # 用例照样跑完、只是网络真出去了（这条用例就会在 404 上断言失败）。
        main.http_session = lambda: _Sess()
        main._GH_LIMITED_UNTIL = 0.0
        t0 = time.monotonic()
        with self.assertRaises(Exception) as ctx:
            main._github_api_json("https://api.github.com/repos/x/y/releases/latest")
        first_secs = time.monotonic() - t0
        self.assertIn("限流", str(ctx.exception))
        self.assertLess(first_secs, 5.0,
                        f"限流时还在退避重试：第一次就等了 {first_secs:.1f}s")
        self.assertGreater(main._GH_LIMITED_UNTIL, time.monotonic(),
                           "命中限流要立旗，别让后面 25 个组件各自再撞一次")

        calls.clear()
        t1 = time.monotonic()
        with self.assertRaises(Exception) as ctx2:
            main._github_api_json("https://api.github.com/repos/a/b/releases/latest")
        self.assertEqual(calls, [], "额度旗已立，还发网络请求就是继续烧额度")
        self.assertIn("限流", str(ctx2.exception))
        self.assertLess(time.monotonic() - t1, 0.5)

    def test_failure_reason_reaches_the_log(self):
        """真实原因原本只 print 到 stdout（打包后没有控制台），界面上只剩
        一句误导性的"官网版本获取失败"。"""
        main.FETCHERS = {"jdk": lambda: (_ for _ in ()).throw(
            RuntimeError("GitHub API 触发限流（remaining=0）"))}
        self.win._fetch_pending = 0
        self.win._fetch_workers = []
        self._run_real(force=True)
        self.assertTrue(self._pump(), "刷新没在超时内完成")
        msgs = [m for (_lvl, m) in self.logs]
        self.assertTrue(any("jdk" in m.lower() or "JDK" in m for m in msgs),
                        f"失败日志要点名组件：{msgs}")
        self.assertTrue(any("额度" in m or "限流" in m for m in msgs),
                        f"限流要说成人话，不能只写「获取失败」：{msgs}")


    def test_startup_fetch_is_wired_at_the_entry_point_not_the_constructor(self):
        """抓取会起 26 条线程、抓成功还写缓存：挂在 __init__ 上，
        每一个构造 MainWindow 的测试都在替用户打网络、写用户的 version_cache.json。
        与 `_adopt_running` / 检查更新同一套规矩（见 bt_launch_tests 的接线守护）。"""
        import inspect
        self.assertNotIn("self._start_fetch_versions()",
                         inspect.getsource(main.MainWindow.__init__),
                         "__init__ 里发起抓取会被所有构造窗口的测试继承")
        self.assertIn("QTimer.singleShot(0, win._start_fetch_versions)",
                      inspect.getsource(main.main),
                      "生产入口没接启动抓取，打开工具就看不到在线版本号")


class FetchGateContract(unittest.TestCase):
    """并发闸门：排队等槽位的 worker 也必须发 `done`。

    2026-10-28 真机复现：开工具后右上角永远停在「⟳ 抓取中…」且按钮禁用。
    根因是 `_gate.acquire(timeout=0.25)` 等不到就 return，连 `done` 都没发 ——
    每个 worker 欠 `_fetch_pending` 一次减一，70 多个组件里只有 14 个报了结果，
    计数器再也归不了零，`_fetch_finished()` 永远不执行。
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._orig_abort = main.FETCH_ABORT.is_set()
        main.FETCH_ABORT.clear()
        self.addCleanup(lambda: main.FETCH_ABORT.set() if self._orig_abort
                        else main.FETCH_ABORT.clear())
        self._orig_gate = main.VersionFetchWorker._gate
        main.VersionFetchWorker._gate = threading.Semaphore(1)
        self.addCleanup(setattr, main.VersionFetchWorker, "_gate", self._orig_gate)

    def test_worker_queued_at_the_gate_still_reports_done(self):
        started = threading.Event()
        release = threading.Event()

        def slow():
            started.set()
            release.wait(5)
            return []

        done = []
        blocking = main.VersionFetchWorker("slow", slow)
        queued = main.VersionFetchWorker("queued", lambda: [])
        for w in (blocking, queued):
            w.done.connect(lambda key, _vs: done.append(key))
        blocking.start()
        self.assertTrue(started.wait(2), "慢 fetcher 没进闸门")
        queued.start()
        time.sleep(0.6)          # 超过 FETCH_ABORT_POLL_SEC：旧实现到这里已经放弃了
        release.set()
        self.assertTrue(blocking.wait(5000), "慢 worker 没在 5 秒内收尾")
        self.assertTrue(queued.wait(5000), "排队 worker 没在 5 秒内收尾")
        deadline = time.time() + 2
        while len(done) < 2 and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.05)
        self.assertIn("slow", done)
        self.assertIn("queued", done,
                      "排队等闸门的 worker 也必须发 done：否则 _fetch_pending "
                      "永远归不了零，右上角会一直停在「⟳ 抓取中…」")


class GitHubApiProxy(unittest.TestCase):
    """GitHub API 先走国内反向代理，失败再直连；token 不交给第三方。

    2026-10-28 真机：直连 api.github.com 证书校验失败，30 多个只发 GitHub Release
    的组件全部降级成内置清单。实测 gh-proxy.com 能代理 API（200 + JSON + X-RateLimit），
    ghfast / ghproxy.net 对 API 路径 403。
    """

    URL = "https://api.github.com/repos/demo/demo/releases?per_page=1"

    class _Resp:
        def __init__(self, code=200, headers=None, payload=None):
            self.status_code = code
            self.headers = headers or {}
            self._payload = payload if payload is not None else {"ok": True}

        def raise_for_status(self):
            if self.status_code >= 400:
                # 不能用 RuntimeError：产品代码把 RuntimeError 当作"限流终局"，
                # 那会让代理 404 被误判成额度用尽。requests 真实抛的是 HTTPError。
                raise ValueError(f"HTTP {self.status_code}")

        def json(self):
            return self._payload

    def setUp(self):
        self._orig_session = main.http_session
        self._orig_limit = main._GH_LIMITED_UNTIL
        main._GH_LIMITED_UNTIL = 0.0
        main.FETCH_ABORT.clear()
        self.addCleanup(setattr, main, "http_session", self._orig_session)
        self.addCleanup(setattr, main, "_GH_LIMITED_UNTIL", self._orig_limit)
        self.addCleanup(main.FETCH_ABORT.clear)

    def _session(self, behavior):
        calls = []

        class _S:
            def get(self, url, **kw):
                calls.append((url, kw.get("headers") or {}))
                return behavior(url)

        main.http_session = lambda: _S()
        return calls

    def test_proxy_is_tried_before_direct_and_falls_back(self):
        def behavior(url):
            if url.startswith(main.GH_API_PROXY):
                return self._Resp(404)
            return self._Resp(200, payload={"ok": "direct"})
        calls = self._session(behavior)
        got = main._github_api_json(self.URL)
        self.assertEqual(got, {"ok": "direct"})
        self.assertTrue(calls[0][0].startswith(main.GH_API_PROXY), calls)
        self.assertEqual(calls[1][0], self.URL, calls)

    def test_token_is_not_forwarded_to_the_proxy(self):
        def behavior(url):
            if url.startswith(main.GH_API_PROXY):
                return self._Resp(404)
            return self._Resp(200)
        calls = self._session(behavior)
        import os
        os.environ["GITHUB_TOKEN"] = "secret-token"
        self.addCleanup(os.environ.pop, "GITHUB_TOKEN", None)
        main._github_api_json(self.URL)
        self.assertNotIn("Authorization", calls[0][1],
                         "代理请求不许带用户的 token")
        self.assertEqual(calls[1][1].get("Authorization"), "Bearer secret-token")


class WorkerFailureReason(unittest.TestCase):
    """抓取失败的真实原因必须留在 worker 上，界面才写得出一句人话。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._orig_abort = main.FETCH_ABORT.is_set()
        main.FETCH_ABORT.clear()
        self.addCleanup(lambda: main.FETCH_ABORT.set() if self._orig_abort
                        else main.FETCH_ABORT.clear())

    def _run(self, fetcher):
        w = main.VersionFetchWorker("demo", fetcher)
        w.start()
        self.assertTrue(w.wait(8000), "worker 没在 8 秒内收尾")
        return w

    def test_worker_records_the_failure_reason(self):
        w = self._run(lambda: (_ for _ in ()).throw(
            RuntimeError("GitHub API 触发限流（remaining=0）")))
        self.assertIn("限流", w.error_text,
                      "原因丢了，界面上就只剩一句误导性的「官网版本获取失败」")

    def test_successful_fetch_leaves_no_reason(self):
        w = self._run(lambda: [])
        self.assertEqual(w.error_text, "", "成功路径不该留下失败原因")


if __name__ == "__main__":
    unittest.main(verbosity=2)
