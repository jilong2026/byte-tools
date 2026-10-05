"""多版本切换真机测试：每个组件装 2 个版本 → 来回切 → 验每一轮都生效。

**这是真机测试，会写真实的用户环境变量与 PATH。**
测完卸载（已装的那几个不卸），并把环境变量恢复原状。

用法：
  _drill_mv.py install <key> [ver1] [ver2]   # 装两个版本并测切换
  _drill_mv.py switch <key> <ver>            # 切到某版本并复验
  _drill_mv.py uninstall <key>              # 卸掉该组件全部版本
  _drill_mv.py check <key>                  # 只看当前状态
  _drill_mv.py mvn <key> <ver1> <ver2>       # 只测切换，不装
"""
import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

from PySide6.QtCore import QEventLoop  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import main  # noqa: E402

KEYS = ("nacos activemq jenkins maven tomcat nginx mysql postgresql kafka "
        "elasticsearch rabbitmq node go gradle bun python git powershell conda "
        "docker kubectl mongodb seata rocketmq pulsar jdk").split()


def builder(key):
    """取 URL 构造器；没有就返回 None（该组件的下载链路还不通）。"""
    return getattr(main, f"_{key}_urls", None)


def comp_of(key):
    return next(c for c in main.build_components() if c.key == key)


def pick_urls(key, version):
    fn = builder(key)
    if fn is None:
        # jdk / powershell / conda 没有静态 _<key>_urls，但它们的地址在
        # **url_list_map** 里（url_map 是空的 —— 我先读错了字段，取到空 dict，
        # 一度以为"地址还没抓"）。直接调 urls_for_current()：
        # 那是产品真正用的接口，自己会按平台挑 url_list_map 那一栏。
        comp = comp_of(key)
        for cv in comp.versions:
            if cv.version == version:
                return list(cv.urls_for_current())
        return []
    try:
        out = fn(version)
    except Exception as exc:
        print(f"  [WARN] 取下载地址失败：{exc}")
        return []
    if isinstance(out, dict):
        for k in (main.CURRENT_OS, "Windows", "Linux", "Darwin"):
            if out.get(k):
                return out[k]
        return []
    return list(out or [])


def versions_of(key):
    return [cv.version for cv in comp_of(key).versions]


def move_only_candidate(parent, final):
    """解压出的目录名可能不等于 <key>-<version>（厂商包名前缀），归位到期望名。"""
    cands = []
    for p in parent.iterdir():
        if not p.is_dir():
            continue
        if p.name == "downloads" or p.name.startswith("."):
            continue
        if p.name.endswith("-data"):
            continue
        cands.append(p)
    if len(cands) == 1:
        if final.exists():
            shutil.rmtree(final, ignore_errors=True)
        shutil.move(str(cands[0]), str(final))
        return True
    return False


def _archive_ext(dest_name):
    """从我们起的下载文件名里认归档类型（extract_archive 只认文件名后缀）。"""
    n = dest_name.lower()
    for suf in (".tar.gz", ".tgz", ".tar.xz", ".tar.bz2", ".zip"):
        if n.endswith(suf):
            return suf
    return ""


def install_single_file(key, version, archive, comp):
    """单文件组件（kubectl / jenkins 的 war 这类）：包里就是一个可执行文件，没有顶层目录。

    产品那边的处理是「拷贝到安装目录根 + 按 exec_name 改名」，
    我们照做：建出<key>-<version>/ 目录，把文件放进去并改名。
    少了改名这一步，exec_path_in_home() 找不到可执行文件，
    状态探测会判成"没装" —— 整条多版本链路会静默断掉。"""
    final = comp.install_dir(version)
    final.mkdir(parents=True, exist_ok=True)
    exe = comp.exec_name or archive.stem
    if main.CURRENT_OS == "Windows" and not exe.endswith((".exe", ".war")):
        exe += ".exe"
    target = final / exe
    shutil.move(str(archive), str(target))
    print(f"  单文件归档 -> {target}")
    return True


def install(key, version):
    comp = comp_of(key)
    target = comp.install_dir(version)
    if target.is_dir():
        print(f"  [skip] {key}-{version} 已装")
        return True
    urls = pick_urls(key, version)
    if not urls:
        print(f"  [FAIL] {key}-{version} 没有可用下载地址")
        return False
    # 后缀必须按"下载下来是什么"来定，不能猜：
    #  - kubectl 的 URL 直接就是 .../kubectl.exe（单文件，没有归档后缀）
    #  - maven/jenkins 的 URL 是 .zip（归档）
    # 猜错会让 extract_archive 走错分支（tar.gz 打开一个 exe → "not a gzip file"）。
    tail = urls[0].lower().split("?")[0].rstrip("/").split("/")[-1]
    is_archive = tail.endswith((".zip", ".tar.gz", ".tgz", ".tar.xz", ".tar.bz2"))
    if is_archive:
        for suf in (".tar.gz", ".tgz", ".tar.xz", ".tar.bz2", ".zip"):
            if tail.endswith(suf):
                suffix = suf
                break
    else:
        # 单文件：exe / war / 无扩展名
        if tail.endswith((".exe", ".war")):
            suffix = "." + tail.rsplit(".", 1)[-1]
        else:
            suffix = ".exe" if main.CURRENT_OS == "Windows" else ""
    dest = main.CONFIG_DIR / key / "downloads" / f"{key}-{version}{suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    worker = main.DownloadWorker(urls, dest)
    loop = QEventLoop()
    state = {"ok": False, "path": "", "err": ""}
    # 进度只打一次百分比，别把日志刷爆（真机批量跑时输出会看不清）
    seen = {"pct": -1}

    def on_prog(d, t):
        pct = int(d * 100 / t) if t else 0
        if pct // 25 != seen["pct"] // 25:
            seen["pct"] = pct
            print(f"    {pct:3d}%  ({d/1048576:.1f}/{t/1048576:.1f} MB)")

    worker.progress.connect(on_prog)
    worker.finished_ok.connect(lambda p: (state.update(ok=True, path=p), loop.quit()))
    worker.finished_fail.connect(lambda m: (state.update(err=m), loop.quit()))
    worker.finished.connect(loop.quit)
    worker.start()
    loop.exec()
    print()
    if not state["ok"]:
        print(f"  [FAIL] 下载失败：{state['err'][:140]}")
        return False
    final = comp.install_dir(version)
    if not is_archive:
        if install_single_file(key, version, Path(state["path"]), comp):
            return True
    else:
        # 解压到**独立临时目录**再归位（产品和 GUI 那边就是这么干的：
        # _on_download_ok 先 extract 到 .extract-<ver>，再 shutil.move 到 install_dir）。
        # 之前我图省事直接解压到 install_dir 的父目录，结果两个问题：
        #   ① 父目录里躺着上一轮残留/下载缓存，"只有 1 个顶层目录"的前提不成立（tomcat 栽这）；
        #   ② 归位时 move 的源是父目录下的子目录、目标是父目录下的同名目录，
        #      shutil 判定为"把目录移进它自己"→ Error（python 栽这）。
        tmp = target.parent / f".extract-{version}"
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        main.ensure_dir(tmp)
        root = main.extract_archive(Path(state["path"]), tmp)
        if final.exists():
            shutil.rmtree(final, ignore_errors=True)
        src = root if (root and Path(root).is_dir()) else tmp
        shutil.move(str(src), str(final))
        shutil.rmtree(tmp, ignore_errors=True)
    if not final.is_dir():
        print(f"  [FAIL] 解压后没找到 {final}"
              f"（解压根={locals().get('root')}）")
        return False
    print(f"  [ok] {key}-{version} -> {final}")
    return True


def read_user_env(name):
    """读注册表里的用户环境变量（刚写入的进程环境读不到）。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return winreg.QueryValueEx(k, name)[0]
    except Exception:
        return None


def switch(key, version):
    """切到指定版本并复验。返回 (是否成功, 说明)。"""
    comp = comp_of(key)
    home = comp.install_dir(version)
    if not home.is_dir():
        return False, f"目录不存在：{home}"
    try:
        steps = main.apply_active_version(comp, version)
    except main.SwitchError as exc:
        return False, f"切换失败：{exc}"
    main.save_active_version(key, version)
    ok = True
    notes = []
    bad = [s for s in steps if "失败" in s]
    if bad:
        ok = False
        notes.append(f"步骤含失败：{bad[0][:70]}")
    if comp.env_var:
        real = read_user_env(comp.env_var)
        if real is None:
            notes.append(f"{comp.env_var}：盘上读不到")
        elif Path(real).resolve() != home.resolve():
            ok = False
            notes.append(f"{comp.env_var} 指向 {real}，不是 {home}")
        else:
            notes.append(f"{comp.env_var}={real}")
    act = main.load_active_map().get(key)
    if act != version:
        ok = False
        notes.append(f"active 表是 {act}，不是 {version}")
    else:
        notes.append(f"active={act}")
    return ok, "；".join(notes)


def mvn_test(key, versions):
    """在版本之间来回切，验每一轮都真的生效。"""
    print(f"\n=== [{key}] 多版本切换真机测试 ===")
    have = [v for v in versions if comp_of(key).install_dir(v).is_dir()]
    print(f"已装：{have}")
    if len(have) < 2:
        print(f"  [SKIP] 只装了 {len(have)} 个版本，不足以测切换")
        return 0
    seq = have + [have[0]]      # 来回切：单向只能证"切过去对"，回切才知有没有搞坏
    results = []
    for v in seq:
        ok, note = switch(key, v)
        results.append((v, ok))
        print(f"  切到 {v:12} {'PASS' if ok else 'FAIL'}  {note}")
    all_ok = all(r[1] for r in results)
    print(f"=== [{key}] {'全部通过' if all_ok else '有失败项'} ===")
    return 0 if all_ok else 1


def uninstall_all(key):
    comp = comp_of(key)
    removed = []
    for path in list(comp.installed_dirs()):
        shutil.rmtree(path, ignore_errors=True)
        removed.append(path.name)
    dl = main.CONFIG_DIR / key / "downloads"
    if dl.is_dir():
        shutil.rmtree(dl, ignore_errors=True)
    try:
        main.save_active_version(key, None)
    except Exception:
        pass
    return removed


def cmd_install(key, v1=None, v2=None):
    vs = versions_of(key)
    picks = [v1, v2] if (v1 and v2) else vs[:2]
    print(f"[{key}] 目标版本：{picks}")
    print(f"        全部候选：{vs}")
    ok = True
    for v in picks:
        ok = install(key, v) and ok
    if not ok:
        print(f"[{key}] 安装阶段有失败，跳过切换测试")
        return 1
    return mvn_test(key, picks)


def cmd_uninstall(key):
    removed = uninstall_all(key)
    print(f"[{key}] 已删除：{removed}")
    print(f"  剩余已装：{[p.name for p in comp_of(key).installed_dirs()]}")
    return 0


def cmd_check(key):
    comp = comp_of(key)
    print(f"[{key}] active={main.load_active_map().get(key)}")
    print(f"  已装目录：{[p.name for p in comp.installed_dirs()]}")
    if comp.env_var:
        print(f"  {comp.env_var} = {read_user_env(comp.env_var)}")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        raise SystemExit(1)
    act, key = a[0], a[1]
    if act == "install":
        raise SystemExit(cmd_install(key, *(a[2:4] if len(a) > 2 else ())))
    if act == "switch":
        ok, note = switch(key, a[2])
        print(f"{'PASS' if ok else 'FAIL'}  {note}")
        raise SystemExit(0 if ok else 1)
    if act == "uninstall":
        raise SystemExit(cmd_uninstall(key))
    if act == "check":
        raise SystemExit(cmd_check(key))
    if act == "mvn":
        raise SystemExit(mvn_test(key, a[2:]))
    print("未知动作")
    raise SystemExit(1)
