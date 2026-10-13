"""2026-10-12 新增四组件（Kotlin / GraalVM / Rust / Redis）的规格测试。

全部离线断言。每一条写死的取值都来自本机实测，台账在 DEVELOPMENT.md R1.5：
  Kotlin   zip 顶层是 `kotlinc/`，里面有 `bin/kotlinc.bat` ⇒ path_subdir="bin"
  GraalVM  env_var 必须是 GRAALVM_HOME —— 写 JAVA_HOME 会和 Temurin 抢同一个变量
  Rust     官方 .exe(NSIS) 已停发；合并 tar.xz 里没有统一 bin/；
           `msiexec /a` 免提权提取出统一 prefix，rustc/cargo/rustfmt 实测能跑
  Redis    官方不发 Windows 二进制，用 redis-windows 社区构建；
           真机 drill：exe 在包根目录、--port 能改口、--dir+SAVE 落 dump.rdb、
           按登记 PID terminate() 立即退出并释放端口
  Dart     zip 顶层单目录 dart-sdk/、根上 0 散文件 ⇒ collapse 后 install_dir
           即 dart-sdk 内容，`bin/dart.exe` 在 bin/ ⇒ path_subdir="bin"

本机 WMI 服务卡死会让 platform.system() 永久阻塞，先 stub 掉再 import main。
"""
import os
import shutil
import sys
import unittest
from pathlib import Path

import platform as _platform


def _no_wmi(*_a, **_k):
    raise OSError("WMI disabled for test process")


_platform._wmi_query = _no_wmi
if hasattr(_platform.uname, "cache_clear"):
    _platform.uname.cache_clear()

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import main  # noqa: E402

COMPS = {c.key: c for c in main.build_components()}
NEW_KEYS = ("kotlin", "graalvm", "rust", "redis", "dart")


def win_urls(key):
    """该组件默认版本在 Windows 上的候选源列表。"""
    cv = COMPS[key].versions[0]
    return list((cv.url_list_map or {}).get("Windows")
                or (cv.url_map or {}).get("Windows")
                or [])


class AllFiveRegistered(unittest.TestCase):
    def test_every_new_key_exists(self):
        for key in NEW_KEYS:
            self.assertIn(key, COMPS, f"{key} 没进 build_components()")

    def test_none_of_them_is_download_only(self):
        """五个都是要真装到 ~/.env-tools/<key>/ 的组件，不是「开发工具」那批。"""
        for key in NEW_KEYS:
            self.assertFalse(COMPS[key].download_only, key)
            self.assertTrue(COMPS[key].multi_version, key)

    def test_each_has_a_fetcher_registered(self):
        missing = [k for k in NEW_KEYS if k not in main.FETCHERS]
        self.assertEqual(missing, [], f"这些 key 没有 fetcher，刷新版本时不会更新：{missing}")


class KotlinSpec(unittest.TestCase):
    def test_lands_in_dev_env(self):
        self.assertEqual(COMPS["kotlin"].category, "开发环境")

    def test_path_subdir_is_bin_because_zip_root_is_kotlinc(self):
        c = COMPS["kotlin"]
        self.assertEqual(c.path_subdir, "bin")
        self.assertEqual(c.exec_name, "kotlinc")
        # 编译器不需要 XXX_HOME；留空 = 只收敛 PATH（同 docker / kubectl）
        self.assertIsNone(c.env_var)

    def test_windows_sources_put_accelerators_first_and_bare_github_last(self):
        urls = win_urls("kotlin")
        self.assertGreaterEqual(len(urls), 2, "GitHub 裸地址本机连不上，必须有加速器")
        # 末位才是裸 github.com，前面几条都是"加速器前缀 + 同一个产物地址"
        self.assertTrue(urls[-1].startswith("https://github.com/"), urls[-1])
        self.assertFalse(urls[0].startswith("https://github.com/"), urls[0])
        for u in urls[:-1]:
            self.assertIn("https://github.com/", u, u)
        self.assertIn("kotlin-compiler-", urls[-1])
        self.assertTrue(urls[-1].endswith(".zip"), "只认 zip，别把 .sha256/.spdx.json 当包")


class GraalVMSpec(unittest.TestCase):
    def test_uses_GRAALVM_HOME_not_JAVA_HOME(self):
        """写 JAVA_HOME 会和 jdk(Temurin) 抢同一个变量 —— 两个组件互相覆盖。"""
        c = COMPS["graalvm"]
        self.assertEqual(c.env_var, "GRAALVM_HOME")
        self.assertNotEqual(c.env_var, COMPS["jdk"].env_var)

    def test_is_a_jdk_shaped_package(self):
        c = COMPS["graalvm"]
        self.assertEqual(c.path_subdir, "bin")
        self.assertEqual(c.exec_name, "java")
        self.assertEqual(c.category, "开发环境")


class RustSpec(unittest.TestCase):
    def test_lands_in_dev_env_with_bin_prefix(self):
        c = COMPS["rust"]
        self.assertEqual(c.category, "开发环境")
        self.assertEqual(c.path_subdir, "bin")
        self.assertEqual(c.exec_name, "rustc")
        self.assertIsNone(c.env_var)

    def test_windows_artifact_is_the_msi_not_the_stopped_exe(self):
        cv = COMPS["rust"].versions[0]
        self.assertEqual(cv.archive_for_current(), "msi")
        for u in win_urls("rust"):
            self.assertTrue(u.endswith(".msi"), f"官方 .exe 已停发，源里不许出现：{u}")

    def test_url_carries_the_dated_directory(self):
        """Rust 的 dist 是 /dist/<日期>/ 分层；不写日期目录的 URL 实测 404。"""
        import re
        for u in win_urls("rust"):
            self.assertRegex(u, r"/dist/\d{4}-\d{2}-\d{2}/", u)

    def test_has_mainland_mirror_and_official(self):
        urls = win_urls("rust")
        hosts = " ".join(urls)
        self.assertIn("rsproxy.cn", hosts, "实测 206 + 与官方同字节数，必须进源序")
        self.assertIn("static.rust-lang.org", hosts)

    def test_card_warns_that_a_linker_is_still_required(self):
        """实测：本机没有 VS Build Tools 时 rustc 能编译、链接不过（Git 自带 link.exe 冒充）。"""
        note = COMPS["rust"].data_note or ""
        self.assertTrue(any(k in note for k in ("Build Tools", "link.exe", "mingw")),
                        f"卡片没讲清链接器前置：{note[:80]}")


class RedisSpec(unittest.TestCase):
    def test_is_a_launchable_service_so_it_sits_in_the_launch_tab(self):
        c = COMPS["redis"]
        self.assertIsNotNone(c.launch, "redis 要接一键启停")
        self.assertEqual(c.category, "一键启停")

    def test_executables_sit_at_the_package_root(self):
        """实测 zip 顶层 Redis-8.10.2-Windows-x64-msys2/ 下直接就是 exe，没有 bin/。"""
        c = COMPS["redis"]
        self.assertEqual(c.path_subdir, "")
        self.assertEqual(c.exec_name, "redis-server")

    def test_launch_spec_matches_the_real_machine_drill(self):
        sp = COMPS["redis"].launch
        self.assertEqual(sp.main_port, 6379)
        self.assertEqual(sp.port_writeback, "cli_flag")   # 实测 --port 生效
        self.assertEqual(sp.stop_kind, "pid")             # 实测 terminate 登记 PID 即可
        argv = " ".join(sp.commands["Windows"])
        self.assertIn("--port", argv)
        self.assertIn("--dir", argv)                      # 实测 dump.rdb 落到 --dir
        self.assertNotIn("RedisService", argv, "不注册 Windows 服务，进程归本工具管")

    def test_card_says_the_build_is_not_official(self):
        self.assertIn("非官方", COMPS["redis"].data_note or "")

    def test_windows_sources_are_the_accelerated_github_asset(self):
        urls = win_urls("redis")
        self.assertTrue(urls[-1].startswith("https://github.com/"))
        self.assertIn("Windows-x64", urls[-1])


class DartSpec(unittest.TestCase):
    """2026-10-12 Dart SDK 的规格护栏（实测值全部来自探源子代理：
    整包下载 219,877,920 B / sha256 `aed8e4a8…` 与官方 .sha256sum 一致 /
    解压 6.6s / `dart --version` 秒回不写盘，台账见 DEVELOPMENT.md R1.5 Dart 一节）。"""

    def test_lands_in_dev_env_with_bin_subdir(self):
        """zip 顶层单目录 dart-sdk/、根上 0 散文件 ⇒ collapse 后 install_dir 即
        dart-sdk 内容，`bin/dart.exe` 就在那里 ⇒ path_subdir="bin"。"""
        c = COMPS["dart"]
        self.assertEqual(c.category, "开发环境")
        self.assertEqual(c.path_subdir, "bin")
        self.assertEqual(c.exec_name, "dart")
        self.assertIsNone(c.env_var, "官方没有 DART_HOME 约定，只加 PATH（同 bun/pwsh）")
        self.assertFalse(c.download_only)

    def test_archive_is_zip_and_version_is_a_clean_semver(self):
        cv = COMPS["dart"].versions[0]
        self.assertEqual(cv.archive_for_current(), "zip")
        self.assertIsNotNone(main._version_parts(cv.version))
        self.assertRegex(cv.version, r"^\d+\.\d+\.\d+$",
                         "默认版本必须是干净 semver，别把 revision 混进去")

    def test_windows_sources_are_two_mainland_mirrors_then_official_last(self):
        """R1.1：≥2 大陆镜像 + 官网末位。镜像路径必须带 /flutter/ 层（不带实测 404）。"""
        urls = win_urls("dart")
        self.assertGreaterEqual(len(urls), 3, f"源不够：{urls}")
        self.assertEqual(urls[-1],
                         "https://storage.googleapis.com/dart-archive/"
                         "channels/stable/release/3.13.5/sdk/"
                         "dartsdk-windows-x64-release.zip")
        self.assertIn("mirrors.nju.edu.cn", urls[0])
        self.assertIn("mirrors.cloud.tencent.com", urls[1])
        for u in urls[:-1]:
            self.assertIn("/flutter/dart-archive/", u,
                          f"镜像路径少了 /flutter/ 一层（实测不带就 404）：{u}")
            self.assertTrue(u.endswith(".zip"), f"只认 zip：{u}")
        self.assertFalse("/flutter/" in urls[-1],
                         f"官网没有 /flutter/ 层，末位应是 storage.googleapis.com：{urls[-1]}")

    def test_no_dl_minio_style_dead_host_or_latest_alias(self):
        """探源实测的坑：`latest` 别名在镜像上回的是**旧版本的不同字节数**，
        登记必须用 `{version}` 拼死版本，任何源的 `latest` 都不许进 URL。"""
        for cv in COMPS["dart"].versions:
            for lst in (cv.url_list_map or {}).values():
                for u in lst:
                    self.assertNotIn("/latest/", u,
                                     f"latest 别名在镜像上会装错版本：{u}")

    def test_fetcher_reads_version_from_official_json_and_sorts_numerically(self):
        """探源实测的两个坑：
        ① GCS 列目录是字典序（3.10.0 排在 3.9.4 前）⇒ 必须逐段 int 排序；
        ② 前缀里混着纯数字垃圾目录（29803/30036/…）⇒ 必须按 semver 形态过滤。"""
        fake_listing = {"prefixes": [
            "channels/stable/release/3.10.0/",
            "channels/stable/release/29803/",
            "channels/stable/release/3.9.4/",
            "channels/stable/release/latest/",
            "channels/stable/release/30036/",
            "channels/stable/release/3.13.5/",
        ]}
        calls = []

        def fake_get(url, timeout=None):
            calls.append(url)
            if url.endswith("/VERSION"):
                return _Json({"version": "3.13.5", "date": "2026-09-29",
                              "revision": "04bcd103"})
            return _Json(fake_listing)

        orig = main._get
        main._get = fake_get
        self.addCleanup(setattr, main, "_get", orig)
        out = main.fetch_dart_versions()
        vers = [v.version for v in out]
        self.assertGreaterEqual(len(vers), 2, f"清单太短：{vers}")
        self.assertEqual(vers[0], "3.13.5", f"最新版必须在最前：{vers}")
        self.assertIn("3.10.0", vers)
        self.assertIn("3.9.4", vers)
        for bad in ("29803", "30036", "latest"):
            self.assertNotIn(bad, vers, f"垃圾目录 {bad} 混进了版本清单")


class SingleTopDirRule(unittest.TestCase):
    """R3.22 第 5 条：`extract_archive` 底部"单顶层即根"的判定边界。

    这组用例原先在 `bt_protoc_uv_tests.py`（2026-10-12 B1 的护栏）。那个文件当时
    **从未提交过**，2026-10-12 收尾时被 `git clean` 误删、无备份可恢复，所以迁到
    本文件（当时就在同一批里，只没提交上）。原文件另有 protoc / uv 的资产名筛选
    断言，那部分仍缺失，见 DEVELOPMENT.md R3.22 的缺口说明。

    三条边界缺一不可：
      ① 只有 1 个目录且根上没有散文件 ⇒ 返回**那层目录**（collapse）
      ② 1 个目录**但根上有散文件**（如 pnpm 的 `dist/` + `pnpm.exe`）⇒ 返回 install_dir，
         否则那些文件被整个留在外面，装完 PATH 指着只有 dist/ 的目录
      ③ ≥2 个目录（如 protoc 的 `bin/` + `include/`）⇒ 返回 install_dir
    后两条是既有组件的保护栏，防止把改动波及 jdk / maven 那一类。
    """

    def _extract(self, entries):
        """造一个只含给定条目的 zip，跑 extract_archive，返回它认定的安装根。"""
        import tempfile
        import zipfile
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        zpath = tmp / "a.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            for name in entries:
                zf.writestr(name, b"x")
        out = tmp / "out"
        try:
            return main.extract_archive(zpath, out)
        except Exception:
            # 解压目标不存在等副作用不在本组用例的断言范围
            return None

    def test_one_dir_and_no_loose_files_collapses_into_it(self):
        root = self._extract(["only/one.txt"])
        self.assertIsNotNone(root, "extract_archive 返回了 None")
        self.assertEqual(root.name, "only",
                         "只有 1 个目录且无散文件时应 collapse 成那层")

    def test_one_dir_plus_loose_files_keeps_install_dir(self):
        """1 目录 + 根上散文件 ⇒ 不许 collapse，否则散文件被留在外面。"""
        root = self._extract(["dist/", "dist/x.txt", "tool.exe"])
        self.assertIsNotNone(root, "extract_archive 返回了 None")
        self.assertNotEqual(root.name, "dist",
                            "根上有散文件时 collapse 会丢掉那些文件（pnpm 实测踩过）")

    def test_two_or_more_dirs_keeps_install_dir(self):
        """≥2 个目录（protoc 的 bin/ + include/）⇒ 不许 collapse。"""
        root = self._extract(["bin/protoc.exe", "include/x.proto", "readme.txt"])
        self.assertIsNotNone(root, "extract_archive 返回了 None")
        self.assertNotEqual(root.name, "bin",
                            "顶层 ≥2 个目录时必须返回 install_dir 本身")


class MsiExtraction(unittest.TestCase):
    """`.msi` 走 msiexec /a 提取，而不是 /i 安装。"""

    def setUp(self):
        self._run = main.subprocess.run
        self.calls = []

        class _P:
            returncode = 0

        def fake_run(cmd, **kw):
            self.calls.append(list(cmd))
            return _P()

        main.subprocess.run = fake_run

    def tearDown(self):
        main.subprocess.run = self._run

    def test_msi_does_not_fall_into_the_single_binary_copy_branch(self):
        """单文件分支只会把文件拷进目录根 —— 那等于"装机完成"是假的。"""
        tmp = Path(os.environ.get("TEMP", "/tmp")) / "bt_msi_probe"
        shutil.rmtree(tmp, ignore_errors=True)
        (tmp).mkdir(parents=True, exist_ok=True)
        (tmp / "x.msi").write_bytes(b"\xd0\xcf\x11\xe0" + b"\0" * 64)
        try:
            main.extract_archive(tmp / "x.msi", tmp / "out")
        except Exception:
            pass
        finally:
            self.assertFalse((tmp / "out" / "x.msi").exists(),
                             "msi 被当成单二进制直接拷贝了，没有走提取")
            shutil.rmtree(tmp, ignore_errors=True)

    def test_extract_archive_runs_msiexec_admin_extract(self):
        tmp = Path(os.environ.get("TEMP", "/tmp")) / "bt_msi_probe"
        tmp.mkdir(exist_ok=True)
        try:
            try:
                main.extract_archive(tmp / "x.msi", tmp / "out")
            except Exception:
                pass    # 目录还不存在之类的副作用不在本用例断言范围
            self.assertTrue(self.calls, "没调用 msiexec")
            cmd = self.calls[0]
            self.assertIn("msiexec", cmd[0].lower())
            self.assertTrue(any(a.upper() == "/A" for a in cmd), "必须用 /a 管理性提取")
            self.assertTrue(any(a.upper() == "/QN" for a in cmd), "必须静默")
            self.assertTrue(any(a.upper().startswith("TARGETDIR=") for a in cmd), cmd)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class _Json(dict):
    """让 `.json()` 直接返回 dict 的最小桩。"""

    def json(self):
        return dict(self)


if __name__ == "__main__":
    unittest.main(verbosity=2)
