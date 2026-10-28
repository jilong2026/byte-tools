# -*- coding: utf-8 -*-
"""WSL 环境（Ubuntu 24.04）一键安装的规格测试（离线）。

设计边界（用户 2026-10-21 明确要求，见 main.py 里 WSL 模块注释）：
  · 只提示重启，**绝不自动重启**；
  · 系统功能 + 运行时只弹一次 UAC，结果以脚本写的 JSON 为准；
  · 下载走工具的多源故障转移（镜像在前、官方末位）。

本文件一律不真的调用 wsl.exe / dism / msiexec：所有接缝（wsl_exe / wsl_run /
run_elevated_process）都在用例里打桩，可在无 WSL、无管理员权限的机器上跑。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import _btprelude  # noqa: F401  必须早于 import main：打 WMI 桩 + offscreen + sys.path

REPO_ROOT = str(_btprelude.REPO_ROOT)

import main  # noqa: E402


class _CfgSandbox(unittest.TestCase):
    """把 CONFIG_DIR 指到临时目录（WSL 的下载/导入都落在 CONFIG_DIR/wsl 下）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = self.root / "env-tools"
        self.cfg.mkdir()
        self._saved = {k: getattr(main, k) for k in ("CONFIG_DIR", "CONFIG_FILE")}
        main.CONFIG_DIR = self.cfg
        main.CONFIG_FILE = self.cfg / "config.json"
        self.addCleanup(lambda: [setattr(main, k, v) for k, v in self._saved.items()])

    def patch(self, obj, name, value):
        self.assertTrue(hasattr(obj, name), f"要打桩的 {name} 不存在")
        original = getattr(obj, name)
        setattr(obj, name, value)
        self.addCleanup(setattr, obj, name, original)


class SourceListTests(unittest.TestCase):
    def test_rootfs_has_four_mainland_mirrors_then_official(self):
        urls = main.wsl_rootfs_urls()
        self.assertEqual(len(urls), 5)
        for host in ("mirrors.nju.edu.cn", "mirrors.ustc.edu.cn",
                     "mirrors.aliyun.com", "mirrors.tuna.tsinghua.edu.cn"):
            self.assertIn(host, urls[[i for i, u in enumerate(urls) if host in u][0]])
        self.assertTrue(urls[-1].startswith("https://cdimage.ubuntu.com/"),
                        f"末位必须是官方：{urls[-1]}")
        self.assertNotIn("cdimage.ubuntu.com/ubuntu-cdimage", urls[-1],
                         "官方域本身就带 /ubuntu-cdimage/ 以外的路径结构，别重复拼")
        for u in urls:
            self.assertTrue(
                u.endswith(f"ubuntu-base/releases/{main.WSL_UBUNTU_SERIES}/release/"
                           f"{main.WSL_ROOTFS_FILE}"), u)

    def test_runtime_is_accelerated_then_bare_github(self):
        urls = main.wsl_runtime_urls()
        self.assertEqual(urls[-1],
                         "https://github.com/microsoft/WSL/releases/download/"
                         f"{main.WSL_RUNTIME_TAG}/{main.WSL_RUNTIME_FILE}")
        for u in urls[:-1]:
            self.assertTrue(u.endswith("github.com/microsoft/WSL/releases/download/"
                                       f"{main.WSL_RUNTIME_TAG}/{main.WSL_RUNTIME_FILE}"), u)
            self.assertTrue(u.startswith(tuple(main.GH_ACCELERATORS)), u)

    def test_sizes_and_magics_match_the_measured_artifacts(self):
        self.assertEqual(main.WSL_ROOTFS_SIZE, 29_983_772)
        self.assertEqual(main.WSL_RUNTIME_SIZE, 367_575_040)
        self.assertEqual(main.WSL_ROOTFS_MAGIC, b"\x1f\x8b\x08")
        self.assertEqual(main.WSL_RUNTIME_MAGIC, b"\xd0\xcf\x11\xe0")


class DecodeAndParseTests(unittest.TestCase):
    def test_utf16_without_bom_is_decoded(self):
        raw = "Ubuntu-24.04\r\n".encode("utf-16-le")
        self.assertEqual(main.wsl_decode(raw), "Ubuntu-24.04\r\n")

    def test_utf8_is_decoded(self):
        self.assertEqual(main.wsl_decode("WSL 版本：3.0.3".encode("utf-8")),
                         "WSL 版本：3.0.3")

    def test_distro_list_strips_star_and_skips_localized_hint(self):
        text = "Ubuntu-24.04\r\n* docker-desktop\r\n适用于 Linux 的 Windows 子系统没有已安装的分发版。\r\n\r\n"
        self.assertEqual(main.parse_wsl_distros(text),
                         ["Ubuntu-24.04", "docker-desktop"])

    def test_empty_output_is_empty_list(self):
        self.assertEqual(main.parse_wsl_distros(""), [])


class ElevatedScriptTests(_CfgSandbox):
    def test_script_enables_both_features_and_installs_msi(self):
        s = main.wsl_elevated_script(Path(r"C:\a b\wsl.msi"), Path(r"C:\r\out.json"))
        self.assertIn("Microsoft-Windows-Subsystem-Linux", s)
        self.assertIn("VirtualMachinePlatform", s)
        self.assertIn("/norestart", s)
        self.assertIn(r'"C:\a b\wsl.msi"', s, "带空格的 MSI 路径必须加引号")
        self.assertIn(r"'C:\r\out.json'", s)

    def test_script_never_reboots_the_machine(self):
        """用户红线：装完只提示重启，工具绝不替他重启。"""
        s = main.wsl_elevated_script(Path("x.msi"), Path("y.json")).lower()
        for forbidden in ("restart-computer", "shutdown", "shutdown.exe",
                          "-force", "reboot"):
            self.assertNotIn(forbidden, s, f"脚本里不许出现 {forbidden}")


class RuntimeResultTests(_CfgSandbox):
    def _run_with(self, payload, proc=None):
        def fake_process(exe, params, timeout=0):
            (main.wsl_work_dir()).mkdir(parents=True, exist_ok=True)
            (main.wsl_work_dir() / "install-result.json").write_text(
                json.dumps(payload), encoding="utf-8")
            return proc or {"ok": True, "cancelled": False, "exit_code": 0, "error": ""}
        self.patch(main, "run_elevated_process", fake_process)
        return main.wsl_install_runtime(self.cfg / "wsl" / "x.msi", log=lambda _m: None)

    def test_codes_zero_or_3010_are_success_and_3010_means_reboot(self):
        res = self._run_with({"dism_wsl": 0, "dism_vmp": 3010, "msi": 0,
                              "wsl_feature": "Enabled", "vmp_feature": "Enabled"})
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["reboot_needed"])

    def test_installer_failure_is_not_masked_by_process_exit_zero(self):
        """脚本自己 catch 掉了异常也会以 0 退出 —— 只认 JSON 里的三个码。"""
        res = self._run_with({"dism_wsl": 0, "dism_vmp": 0, "msi": 1603})
        self.assertFalse(res["ok"])
        self.assertIn("1603", res["error"])

    def test_cancelled_uac_changes_nothing(self):
        def fake_process(exe, params, timeout=0):
            return {"ok": False, "cancelled": True, "exit_code": -1,
                    "error": "已取消管理员权限请求"}
        self.patch(main, "run_elevated_process", fake_process)
        res = main.wsl_install_runtime(self.cfg / "wsl" / "x.msi")
        self.assertTrue(res["cancelled"])
        self.assertFalse(res["ok"])


class ImportTests(_CfgSandbox):
    def test_import_uses_wsl2_first(self):
        calls = []

        def fake_run(args, timeout=0):
            calls.append(list(args))
            return 0, ""

        self.patch(main, "wsl_run", fake_run)
        rootfs = self.cfg / "wsl" / "rootfs.tar.gz"
        rootfs.parent.mkdir(parents=True, exist_ok=True)
        rootfs.write_bytes(b"\x1f\x8b\x08")
        res = main.wsl_import_distro(rootfs)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["version"], "2")
        self.assertEqual(calls[0][:4], ["--import", main.WSL_DISTRO,
                                        str(self.cfg / "wsl" / main.WSL_DISTRO),
                                        str(rootfs)])
        self.assertEqual(calls[0][-2:], ["--version", "2"])

    def test_falls_back_to_wsl1_and_says_so(self):
        calls = []

        def fake_run(args, timeout=0):
            calls.append(list(args))
            return (1, "WSL2 is not supported") if args[-1] == "2" else (0, "")

        self.patch(main, "wsl_run", fake_run)
        logs = []
        rootfs = self.cfg / "wsl" / "rootfs.tar.gz"
        rootfs.parent.mkdir(parents=True, exist_ok=True)
        rootfs.write_bytes(b"\x1f\x8b\x08")
        res = main.wsl_import_distro(rootfs, log=logs.append)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["version"], "1")
        self.assertTrue(any("WSL1" in m and "虚拟化" in m for m in logs), logs)
        self.assertEqual(len(calls), 2)

    def test_missing_rootfs_is_rejected_without_running_anything(self):
        def fake_run(args, timeout=0):
            raise AssertionError("rootfs 不存在时不该调用 wsl.exe")

        self.patch(main, "wsl_run", fake_run)
        res = main.wsl_import_distro(self.cfg / "wsl" / "nope.tar.gz")
        self.assertFalse(res["ok"])


class StateDetectionTests(_CfgSandbox):
    def _state_with(self, version_rc, version_out, list_rc, list_out):
        self.patch(main, "wsl_exe", lambda: r"C:\Windows\System32\wsl.exe")

        def fake_run(args, timeout=0):
            if args[0] == "--version":
                return version_rc, version_out
            return list_rc, list_out

        self.patch(main, "wsl_run", fake_run)
        self.patch(main, "wsl_distro_base_path", lambda name: r"E:\wsl\Ubuntu-24.04")
        return main.wsl_state()

    def test_ready_state(self):
        st = self._state_with(0, "WSL 版本： 3.0.3.0\n内核版本： 6.6.1",
                              0, "Ubuntu-24.04\r\n")
        self.assertTrue(st["runtime_ok"])
        self.assertIn("3.0.3", st["runtime_version"])
        self.assertTrue(st["ubuntu_installed"])
        self.assertEqual(st["ubuntu_path"], r"E:\wsl\Ubuntu-24.04")

    def test_inbox_wsl_is_not_a_runtime(self):
        st = self._state_with(1, "无效命令行参数", 1, "")
        self.assertFalse(st["runtime_ok"])
        self.assertFalse(st["ubuntu_installed"])

    def test_runtime_without_ubuntu(self):
        st = self._state_with(0, "WSL 版本： 3.0.3.0", 0, "docker-desktop\r\n")
        self.assertTrue(st["runtime_ok"])
        self.assertFalse(st["ubuntu_installed"])


class DialogStateTests(_CfgSandbox):
    def _dialog(self, state):
        _btprelude.ensure_app()
        self.patch(main, "wsl_state", lambda: dict(state, exe="wsl.exe", distros=[]))
        self.patch(main, "windows_reboot_pending", lambda: False)
        return main.WslDialog()

    def test_primary_button_walks_the_two_steps(self):
        d = self._dialog({"runtime_ok": False, "ubuntu_installed": False})
        self.assertIn("一键安装", d.btn_primary.text())
        self.assertFalse(d.btn_terminal.isEnabled())
        d.deleteLater()

        d = self._dialog({"runtime_ok": True, "runtime_version": "WSL 版本： 3.0.3",
                          "ubuntu_installed": False})
        self.assertIn("导入 Ubuntu", d.btn_primary.text())
        self.assertFalse(d.btn_terminal.isEnabled())
        d.deleteLater()

    def test_ready_state_disables_install_and_enables_terminal(self):
        d = self._dialog({"runtime_ok": True, "runtime_version": "WSL 版本： 3.0.3",
                          "ubuntu_installed": True, "ubuntu_path": r"E:\wsl\U"})
        self.assertFalse(d.btn_primary.isEnabled())
        self.assertTrue(d.btn_terminal.isEnabled())
        d.deleteLater()


class SearchAndCardTests(_CfgSandbox):
    """2026-10-21 用户反馈「wsl 搜索不到」—— 现在它是一张真正的卡片。"""

    def _comp(self):
        return next(c for c in main.build_components() if c.key == "wsl")

    def test_searchable_by_wsl_linux_and_ubuntu(self):
        comp = self._comp()
        for q in ("wsl", "linux", "ubuntu", "子系统"):
            with self.subTest(q=q):
                self.assertTrue(main.component_matches(comp, q),
                                f"搜「{q}」应当命中 WSL 卡片")

    def test_card_opens_the_wizard_instead_of_downloading(self):
        """卡片只发 wsl_requested 信号，不沿父指针爬回窗口（依赖方向护栏）。"""
        _btprelude.ensure_app()
        from PySide6.QtWidgets import QWidget

        host = QWidget()
        card = main.ComponentCard(self._comp(), lambda *a: None, host)
        hits = []
        card.wsl_requested.connect(lambda: hits.append(1))
        self.assertEqual(card.btn_install.text(), "安装向导")
        self.assertIn("重启", card.btn_install.toolTip())
        self.assertFalse(card.version_combo.isEnabled(),
                         "向导型卡片没有可选版本，下拉框必须禁掉")
        self.assertEqual(card.version_combo.currentText(), "内置安装器")
        self.assertIn("安装向导", card.status_label.text())
        card.btn_install.click()
        self.assertEqual(hits, [1], "点主按钮要请求打开 WSL 向导")
        card.deleteLater()
        host.deleteLater()

    def test_card_does_not_claim_ready_before_the_distro_exists(self):
        _btprelude.ensure_app()
        from PySide6.QtWidgets import QWidget

        host = QWidget()          # 必须留引用：临时父对象被回收会连带删掉卡片
        card = main.ComponentCard(self._comp(), lambda *a: None, host)
        self.assertIn("未安装", card.status_label.text())
        card.deleteLater()
        host.deleteLater()


if __name__ == "__main__":
    unittest.main(verbosity=2)
