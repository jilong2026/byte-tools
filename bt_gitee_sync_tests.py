"""同步Gitee产物.sh 的离线端到端测试（本地 mock Gitee，绝不碰真实 gitee.com）。

为什么要有这份测试：这个脚本已经坑过三次（v1.0.3/v1.0.4 静默少传、境外 runner 上传挂死），
而它跑在 CI 里、只有真发版时才被执行一次，靠肉眼读 shell 不靠谱。

做法：用 http.server 在 127.0.0.1 起一个假 Gitee，把场景名编进 GITEE_API_BASE 的路径前缀，
脚本用同一份代码走完整流程；断言看退出码 + stdout/stderr 文本。

场景（对应被测行为）：
  new              —— 无 Release：创建时正文必须带 4 条 GitHub 直链，默认一个产物都不传
  repo404          —— tags 查询返回 404 时也要当成「没有 Release」继续创建，而不是判死
  existing_no_links—— Release 已存在且正文没直链：脚本自己 PATCH 补写，补不动才硬失败
  existing_links   —— 已存在且正文已有直链：通过，且**不再重复写**正文
  patch400         —— 补写正文被 Gitee 拒绝（4xx）：硬失败并给出网页端/重建两条补救
  upload_ok        —— UPLOAD_ARTIFACTS 指定产物：已存在的跳过、缺失的上传并校验通过
  upload_missing   —— 上传接口假装成功但附件清单没它：必须硬失败
  server500        —— 全程 500：按 MAX_ATTEMPTS 重试后失败，且每次都打了可见日志
  client400        —— 4xx：立即判死，不浪费重试
另有两组与真实脚本无关但同样容易踩空的守卫：
  SyncScriptTest  —— 产物目录指错/为空时，必须在请求 Gitee 之前就拦住（断言 mock 收到 0 个请求）
  ArtifactNameConsistency —— 产物名写在 4 个地方（build matrix / release.yml / .sh / .bat），改一处必须全红
  BatEndToEnd     —— Windows 版 .bat 的完整流程（预检→复用→上传 4 个→附件校验），同样只打本地 mock
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SCRIPT = REPO_ROOT / "同步Gitee产物.sh"
TAG = "vTEST"
GH_BASE = f"https://github.com/owner/slug/releases/download/{TAG}"
ARTIFACTS = ["ByteTools.exe", "ByteTools-windows-x64.zip",
             "ByteTools-macos-arm64.zip", "ByteTools-linux-x64"]

# 用 Git Bash 跑脚本；必须走登录 shell（-l），否则 mingw64/bin 不在 PATH 里，脚本找不到 curl
_BASH_CANDIDATES = [
    r"C:\Users\E5430\.qoder\bin\git\bin\bash.exe",
    r"C:\Users\E5430\.qoder\bin\git\usr\bin\bash.exe",
    r"C:\Program Files\Git\bin\bash.exe",
]
BASH = next((p for p in _BASH_CANDIDATES if Path(p).exists()), None) or shutil.which("bash")

# 每个场景的服务端状态（附件名 + 正文），由 handler 读写
STATE = {}


class MockGitee(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # 静音访问日志
        pass

    def scenario(self):
        # 路径形如 /api/<scenario>/repos/owner/slug/...
        m = re.match(r"^/api/([^/]+)/", self.path)
        return m.group(1) if m else "?"

    def tail(self):
        return self.path.split(f"/api/{self.scenario()}", 1)[-1]

    def send_json(self, code, payload):
        body = payload.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_multipart(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        fields = {}
        for m in re.finditer(r'name="([^"]+)"\r\n\r\n(.*?)(?:\r\n--|$)', raw, re.S):
            fields[m.group(1)] = m.group(2)
        STATE["raw"] = raw
        return fields

    def do_GET(self):
        sc, tail = self.scenario(), self.tail()
        STATE["reqs"].append(("GET", tail))
        if "/releases/download/" in self.path:
            # GH_ACCEL 测试接缝指到这里：给一个 >1 MB 的"真产物"，
            # 让「清空 → 重新下载」这条路径能离线跑完（curl_fetch 只收 ≥1 MB 的文件）。
            body = b"R" * 1_100_000
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if sc == "server500":
            return self.send_json(500, '{"message":"boom"}')
        if sc == "client400":
            return self.send_json(400, '{"message":"bad request token"}')
        if "/releases/tags/" in tail:
            if sc == "new":
                # 2026-09-29 实测：Gitee 对「仓库存在但该 tag 没有 Release」返回 200 + null，
                # 不是 404；仓库本身不存在才 404。脚本要能吃下这两种。
                return self.send_json(200, 'null')
            if sc == "repo404":
                return self.send_json(404, '{"message":"Not Found Project"}')
            # 真实 Gitee 这个接口返回完整 release 对象（含 body）；脚本要靠它判断
            # "现有正文里有没有直链"，所以 mock 也必须带上 body。
            return self.send_json(200, '{"id": 777, "tag_name": "%s", "body": %s}' % (
                TAG, __import__("json").dumps(STATE.get("body", ""))))
        if "/releases/777" in tail or "/releases/888" in tail:
            assets = [{"name": n, "browser_download_url": "x"} for n in STATE.get("assets", [])]
            body = STATE.get("body", "")
            return self.send_json(200, '{"id": 777, "body": %s, "assets": %s}' % (
                __import__("json").dumps(body), __import__("json").dumps(assets)))
        return self.send_json(404, '{"message":"mock: unexpected GET"}')

    def do_POST(self):
        sc, tail = self.scenario(), self.tail()
        STATE["reqs"].append(("POST", tail))
        fields = self.read_multipart()
        if sc == "server500":
            return self.send_json(500, '{"message":"boom"}')
        if sc == "client400":
            return self.send_json(400, '{"message":"bad request token"}')
        if tail.rstrip("/").endswith("/releases"):
            STATE["body"] = fields.get("body", "")
            return self.send_json(200, '{"id": 777, "tag_name": "%s"}' % TAG)
        if "/attach_files" in tail:
            fn = re.search(r'name="file";[^\r\n]*filename="([^"]+)"', STATE.get("raw", ""))
            name = fn.group(1) if fn else "unknown"
            if sc == "upload_missing":   # 接口假装成功，但服务端不登记附件
                return self.send_json(200, '{"browser_download_url":"https://x/y"}')
            STATE["assets"].append(name)
            return self.send_json(200, '{"browser_download_url":"https://x/%s"}' % name)
        return self.send_json(404, '{"message":"mock: unexpected POST"}')


    def do_PATCH(self):
        sc, tail = self.scenario(), self.tail()
        STATE["reqs"].append(("PATCH", tail))
        fields = self.read_multipart()
        if sc == "patch400":
            return self.send_json(400, '{"message":"mock: patch refused"}')
        if "/releases/" in tail:
            # 真实 Gitee 的 PATCH 是「编辑 Release」语义，校验必填字段：
            # 只发 access_token + body 会被打回 400（2026-09-30 实测），
            # 所以 mock 也照实校验，免得脚本在 mock 下能过、到真实 Gitee 就 400。
            missing = [k for k in ("tag_name", "name") if not fields.get(k)]
            if missing:
                return self.send_json(
                    400, '{"messages":["%s is missing"]}' % ' is missing","'.join(missing))
            STATE["patch_fields"] = fields
            STATE["body"] = fields.get("body", "")
            return self.send_json(200, '{"id": 777, "tag_name": "%s"}' % TAG)
        return self.send_json(404, '{"message":"mock: unexpected PATCH"}')


def start_server():
    # 线程化：单个 keep-alive 连接不该把后面的请求堵死（否则偶发超时会让测试时好时坏）
    srv = ThreadingHTTPServer(("127.0.0.1", 0), MockGitee)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def write_assets(tmpdir):
    d = Path(tmpdir)
    d.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(ARTIFACTS, 1):
        (d / name).write_bytes(b"x" * (1024 * i))   # 1KB..4KB，够跑通不占时间
    (d / "alipay.png").write_bytes(b"junk")          # 非产物：绝不该进正文/上传
    return str(d)


class SyncScriptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = start_server()
        cls.port = cls.srv.server_address[1]

    def setUp(self):
        STATE.clear()
        STATE["assets"] = []
        STATE["body"] = ""
        STATE["reqs"] = []
        STATE["patch_fields"] = {}
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_script(self, scenario, extra_env=None, assets_dir=None, max_attempts=2):
        env = dict(os.environ)
        # 两处 PATH 调整，都是为了让子进程的行为等价于 CI 的 Linux runner：
        #  1) bash -l 里没有 python3/python，脚本会退到它自己标注「够用但脆弱」的
        #     grep 解析，mock 场景断言随之失真 —— 递进当前解释器所在目录。
        #  2) Git Bash 把 /mingw64/bin 排在 System32 前面，而本机实测 mingw64 的
        #     curl 会把 argv 里的中文按 GBK 发出（System32 的 curl 保持 UTF-8），
        #     正文回读断言因此永远对不上 —— 让 System32 的 curl 优先。
        env["PATH"] = os.pathsep.join(
            ["C:\\Windows\\System32", os.path.dirname(sys.executable),
             env.get("PATH", "")])
        env.update({
            "GITEE_TOKEN": "mock-token-never-asserted",
            "GITEE_OWNER": "owner",
            "GITEE_REPO": "slug",
            "GITHUB_REPO_SLUG": "owner/slug",
            "GITHUB_SERVER_URL": "https://github.com",
            "TAG_NAME": TAG,
            "ASSETS_DIR": assets_dir or write_assets(self.tmp.name),
            "MAX_ATTEMPTS": str(max_attempts),
            "API_MAX_TIME": "10",
            "UPLOAD_MAX_TIME": "10",
            "GITEE_API_BASE": f"http://127.0.0.1:{self.port}/api/{scenario}/repos/owner/slug",
            # 用例的产物是 KB 级假文件，脚本现在会自己去下载缺的那几个 —— 关掉，
            # 保证整棵树离线（下载路径本身由静态用例对账，不靠真网络）
            "AUTO_FETCH_ASSETS": "0",
        })
        for k, v in (extra_env or {}).items():
            env[k] = v
        # 不用 -l：login shell 会按 /etc/profile 重建 PATH，把 /mingw64/bin 抢回
        # 最前面，上面那个"System32 的 curl 优先"就白写了（实测 command -v curl
        # 又变回 /mingw64/bin/curl）。非登录 shell 保留我们递进去的顺序。
        proc = subprocess.run([BASH, str(SCRIPT)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              env=env, cwd=str(self.tmp.name), timeout=180)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")

    # ---------- 场景 1：无 Release，创建时写直链正文，默认不传二进制 ----------
    def test_new_release_writes_github_links_and_uploads_nothing(self):
        code, out = self.run_script("new")
        self.assertEqual(code, 0, out)
        self.assertIn("上传到 Gitee：（空）", out)
        # 4 行逐项「不上传」，外加收尾统计里那 1 次，所以按前缀数
        self.assertEqual(out.count("  -- 按策略不上传"), 4, out)
        self.assertIn("同步完成：上传 0 个", out)
        # 服务端收到的正文必须含 4 条直链，且不含被下载目录里的杂项图片
        body = STATE["body"]
        for name in ARTIFACTS:
            self.assertIn(f"{GH_BASE}/{name}", body)
        self.assertNotIn("alipay.png", body)
        # 正文是给终端用户看的：不能写「Gitee 侧不挂大二进制」这种工程内部话，
        # 因为本机 .bat 传过产物之后这句话就变成假的（2026-09-29 真实演练时发现）
        self.assertNotIn("不挂大二进制", body)
        self.assertIn("GitHub Release：", body)

    def test_404_on_tags_lookup_is_not_an_error(self):
        # 真实 Gitee 返回 200 + null（见 new 场景），仓库不存在才 404；两种都要能走到「创建」
        code, out = self.run_script("repo404")
        self.assertEqual(code, 0, out)
        self.assertIn("尚无 Release，创建中...", out)
        self.assertIn("创建成功，Release ID: 777", out)

    def test_existing_release_without_links_is_patched_then_passes(self):
        """已存在但正文没直链：必须自己补写（PATCH），不能把活儿丢给人。

        v1.0.5 真实翻车场景：Release 是旧版脚本建的、正文没直链，脚本只复用不写正文，
        于是收尾校验永远失败，重跑一百次也好不了。
        """
        STATE["body"] = "跨平台构建产物（旧默认说明，没有直链）"
        code, out = self.run_script("existing_no_links")
        self.assertEqual(code, 0, out)
        self.assertIn(("PATCH", "/repos/owner/slug/releases/777"), STATE["reqs"],
                      f"必须发一次 PATCH 补写正文，实际请求：{STATE['reqs']}")
        self.assertIn(GH_BASE, STATE["body"], "补写的正文里要有 GitHub 直链")
        self.assertIn("补写正文", out)
        # Gitee 的 PATCH 要求 tag_name + name 一起提交，缺一个就 400（见 mock do_PATCH）
        self.assertEqual(STATE["patch_fields"].get("tag_name"), TAG,
                         "PATCH 必须带 tag_name，否则真实 Gitee 会 400")
        self.assertEqual(STATE["patch_fields"].get("name"), TAG,
                         "PATCH 必须带 name，否则真实 Gitee 会 400")

    def test_existing_release_with_links_is_not_rewritten(self):
        STATE["body"] = f"产物见 {GH_BASE}/ByteTools.exe"
        code, out = self.run_script("existing_links")
        self.assertEqual(code, 0, out)
        self.assertNotIn(("PATCH", "/repos/owner/slug/releases/777"), STATE["reqs"],
                         "正文已经含直链就不该再写一次（每次发版多一次无谓的写）")
        self.assertIn("正文已含 GitHub 直链", out)

    def test_existing_release_patch_refused_fails_loudly_with_remedies(self):
        """PATCH 真被 Gitee 拒了才回到人工补救，不许静默放过。"""
        STATE["body"] = "没有直链的旧正文"
        code, out = self.run_script("patch400")
        self.assertEqual(code, 1, out)
        self.assertIn("补写正文失败", out)
        self.assertIn("A) 在 Gitee 网页端", out)
        self.assertIn("B) 删掉 Gitee 的这个 Release", out)

    # ---------- 场景 2：显式要求上传（小包）时按清单走 ----------
    def test_upload_subset_skips_existing_and_uploads_missing(self):
        STATE["body"] = GH_BASE  # 让收尾校验通过
        STATE["assets"] = ["ByteTools.exe"]      # 这个已经在 Gitee 上
        code, out = self.run_script(
            "existing_links",
            {"UPLOAD_ARTIFACTS": "ByteTools.exe|ByteTools-linux-x64"})
        self.assertEqual(code, 0, out)
        self.assertIn("已存在，跳过: ByteTools.exe", out)
        self.assertIn("成功: https://x/", out)
        self.assertIn("同步完成：上传 1 个，跳过已存在 1 个，按策略不上传 2 个", out)

    def test_upload_claimed_ok_but_asset_missing_fails(self):
        STATE["body"] = GH_BASE
        code, out = self.run_script("upload_missing",
                                    {"UPLOAD_ARTIFACTS": "ByteTools-linux-x64"})
        self.assertEqual(code, 1, out)
        self.assertIn("在上传清单里，但 Gitee 附件清单没有它", out)

    # ---------- 场景 3：网络失败必须快速、可见、不静默 ----------
    def test_server_errors_retry_bounded_and_are_visible(self):
        code, out = self.run_script("server500", max_attempts=3)
        self.assertEqual(code, 1, out)
        self.assertEqual(out.count("HTTP 500 服务端错误"), 3, out)
        self.assertIn("连续 3 次请求 Gitee 均失败", out)
        # 每次可见输出都带耗时/字节，方便判断「挂死」还是「在传」
        self.assertIn("用时", out)

    def test_client_error_does_not_waste_retries(self):
        code, out = self.run_script("client400", max_attempts=3)
        self.assertEqual(code, 1, out)
        self.assertEqual(out.count("客户端错误"), 1, out)   # 4xx 一次判死


    # ---------- 场景 4：目录指错时，必须在请求 Gitee 之前就拦住 ----------
    def test_wrong_dir_fails_before_touching_gitee(self):
        empty = str(Path(self.tmp.name) / "icons_only")
        Path(empty).mkdir(exist_ok=True)
        (Path(empty) / "byte-tools.png").write_bytes(b"icon")
        (Path(empty) / "alipay.png").write_bytes(b"icon")
        code, out = self.run_script("new", assets_dir=empty,
                                    extra_env={"UPLOAD_ARTIFACTS": "ByteTools.exe"})
        self.assertEqual(code, 1, out)
        self.assertIn("找不到任何产物文件", out)
        self.assertIn("图标目录", out)
        self.assertEqual(STATE["reqs"], [], "目录指错却已经打了 Gitee 接口")

    def test_empty_dir_still_writes_links_when_not_uploading(self):
        empty = str(Path(self.tmp.name) / "empty_assets")
        Path(empty).mkdir(exist_ok=True)
        code, out = self.run_script("new", assets_dir=empty)
        self.assertEqual(code, 0, out)
        self.assertIn("警告", out)
        self.assertIn("本地未取到", STATE["body"])
        self.assertIn(f"{GH_BASE}/ByteTools.exe", STATE["body"])

    def test_missing_dir_is_created_not_handed_back(self):
        """目录不存在就自己建，不许把 mkdir + 4 条 curl 甩给维护者（一键契约）。

        旧行为是报错退出并打印手工命令，等于"这步你自己做"。这里只断言契约改变
        的那部分：目录被建出来、那句提示没了、流程走进了 [1/3]。最终退出码不由本
        用例负责（另 4 个用例仍卡在 mock 桩的正文回读上，是既有问题）。
        """
        missing = Path(self.tmp.name) / "nope"
        code, out = self.run_script("new", assets_dir=str(missing))
        self.assertTrue(missing.is_dir(), "脚本没有把产物目录建出来")
        self.assertNotIn("产物目录不存在", out)
        self.assertIn("[1/3]", out, "还停在暂存阶段，没有真的继续")


class ArtifactNameConsistency(unittest.TestCase):
    """产物文件名在四个地方各写了一份，改一处忘改别处就是「静默少传」的老坑。

    build matrix 的 artifact 名是真源；其余三处必须与它逐字一致。
    """

    EXPECT = set(ARTIFACTS)

    def _yml(self):
        return (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    def test_build_matrix_names(self):
        yml = self._yml()
        names = set(re.findall(r"^\s{12}artifact_name:\s*(\S+)\s*$", yml, re.M))
        extras = {x for x in re.findall(r"^\s{12}artifact_extra:\s*(\S+)\s*$", yml, re.M)
                  if x not in ("''", '""')}
        # 被注释掉的停用条目（Intel 通用包）不该混进来
        self.assertEqual(names | extras, self.EXPECT,
                         f"matrix 产物名与预期不一致：{sorted(names | extras)}")

    def test_workflow_release_artifacts_env_matches_matrix(self):
        m = re.search(r"RELEASE_ARTIFACTS:\s*'([^']+)'", self._yml())
        self.assertIsNotNone(m, "release.yml 里没找到 RELEASE_ARTIFACTS")
        self.assertEqual(set(m.group(1).split("|")), self.EXPECT)

    def test_sh_default_matches_matrix(self):
        sh = (REPO_ROOT / "同步Gitee产物.sh").read_text(encoding="utf-8")
        m = re.search(r'DEFAULT_ARTIFACTS="([^"]+)"', sh)
        self.assertIsNotNone(m)
        self.assertEqual(set(m.group(1).split("|")), self.EXPECT)

    def test_bat_hardcoded_lists_match_matrix(self):
        bat = (REPO_ROOT / "同步Gitee产物.bat").read_text(encoding="utf-8")
        preflight = set(re.findall(r'if /i "!CHK!"=="([^"]+)"', bat))
        loop = set(re.findall(r'for %%W in \(([^)]+)\) do', bat)[0].split())
        want = set(re.findall(r"\$want = @\(([^)]+)\)", bat)[0].replace("'", "").split(","))
        self.assertEqual(preflight, self.EXPECT, "bat 预检清单不一致")
        self.assertEqual(loop, self.EXPECT, "bat 上传白名单不一致")
        self.assertEqual(want, self.EXPECT, "bat 收尾校验清单不一致")


class AutoFetchContract(unittest.TestCase):
    """一键契约：缺产物要脚本自己去下载，而不是打印几条 curl 让维护者手跑。

    起因（2026-10-05）：本机双击 同步Gitee产物.bat，看到 release-assets 不存在就
    报错退出并贴出 4 条 mkdir/curl；第二次跑还是同一处。"这步你自己做"本身就是
    缺陷，两个一键脚本当初也是这个毛病（见 DEVELOPMENT.md R4）。
    """

    MIN_BYTES = "1048576"

    def _bat(self):
        return (REPO_ROOT / "同步Gitee产物.bat").read_text(encoding="ascii")

    def _sh(self):
        return (REPO_ROOT / "同步Gitee产物.sh").read_text(encoding="utf-8")

    def test_bat_fetches_before_the_dir_check(self):
        bat = self._bat()
        self.assertIn("call :ensure_assets", bat)
        flat = bat.replace("\r\n", "\n")
        for label in (":ensure_assets", ":fetch_asset", ":curl_fetch"):
            self.assertIn("\n" + label + "\n", flat, f"缺子过程 {label}")
        self.assertLess(
            bat.index("call :ensure_assets"),
            bat.index('if not exist "%ASSETS_DIR%\\" goto :err_dir'),
            "必须先自动补齐产物，再判目录存在性")

    def test_both_scripts_try_accelerator_first_and_github_last(self):
        """规则 R1 同样适用于这条下载：镜像优先、官网末位。"""
        bat = self._bat()
        self.assertLess(bat.index('call :curl_fetch "%GH_ACCEL%%RAW%"'),
                        bat.index('call :curl_fetch "%RAW%"'),
                        "bat 把 github.com 直连排在了加速器前面")
        sh = self._sh()
        self.assertLess(sh.index('"${GH_ACCEL_PREFIX}${GH_DOWNLOAD_BASE}/${_name}"'),
                        sh.index('"${GH_DOWNLOAD_BASE}/${_name}"'),
                        "sh 把 github.com 直连排在了加速器前面")
        self.assertIn('GH_ACCEL_PREFIX="${GH_ACCEL_PREFIX:-https://gh-proxy.com/}"', sh)

    def test_downloaded_file_is_size_validated_in_both(self):
        """镜像会用 200 + 小 HTML 应付缺失文件，不校验体积就会把假产物传上 Gitee。"""
        self.assertIn(f"LSS {self.MIN_BYTES}", self._bat())
        self.assertIn(f"-ge {self.MIN_BYTES}", self._sh())

    def test_ci_mode_never_downloads(self):
        """CI 默认 UPLOAD_ARTIFACTS 为空（正文只写直链），那种模式下一个字节都不该下。"""
        cond = '[ "${#UPLOAD_LIST[@]}" -gt 0 ] && [ "${AUTO_FETCH_ASSETS:-1}" != "0" ]'
        self.assertIn(cond, self._sh(),
                      "自动下载没有绑在「真要往 Gitee 传二进制」这个条件上")

    def test_offline_seam_exists_in_both(self):
        """回归用例的产物是 KB 级假文件，必须能用同一个开关把下载关掉。"""
        self.assertIn('if /i "%AUTO_FETCH_ASSETS%"=="0" goto :eof', self._bat())
        self.assertIn('[ "${AUTO_FETCH_ASSETS:-1}" != "0" ]', self._sh())

    def test_bat_clears_stale_assets_before_fetching(self):
        """产物跨 tag **同名**（v1.1.2 起都叫 ByteTools.exe），所以"文件已存在"根本说明不了
        它属于哪个版本 —— 旧行为是把上个 tag 留下的包原样传到新 tag 的 Gitee Release 上，
        而 [3/3] 只核附件名，照样打印 OK（2026-10-10 用户就是这么撞上"传上去全是旧的"）。
        现在每次真要去下载之前，先把暂存目录整个清空。
        """
        bat = self._bat().replace("\r\n", "\n")
        self.assertIn("\n:clear_stale\n", bat, "缺清空子过程")
        clear_at = bat.index("call :clear_stale")
        self.assertLess(clear_at, bat.index("call :fetch_asset"),
                        "清空必须排在任何一次下载之前")
        self.assertLess(
            bat.index('if /i "%AUTO_FETCH_ASSETS%"=="0" goto :eof'), clear_at,
            "清空必须排在离线开关之后：AUTO_FETCH_ASSETS=0 时一个字节都不许删")

    def test_bat_refuses_to_clear_a_dir_not_named_release_assets(self):
        """ASSETS_DIR 是命令行第 3 个参数。手滑传成 `assets`（仓库里的图标目录）或仓库根目录时，
        无条件 rmdir 会直接删掉版本库文件 —— 所以清空只允许作用于末级名为 release-assets 的目录。
        """
        body = self._bat().split(":clear_stale", 1)[1]
        self.assertIn('"release-assets"', body, "clear_stale 里没有按目录末级名设闸")
        self.assertIn("notice:", body, "闸门拦下时要打印为什么没清，别静默跳过")
        self.assertIn("rmdir /s /q", body, "clear_stale 里没有真的清空动作")

    def test_bat_never_redirects_to_dev_null(self):
        """.bat 里出现 Unix 的 /dev/null 会让整条命令静默不执行，且 ERRORLEVEL 仍是 0。

        2026-10-10 实测三种写法的 rmdir：`>/dev/null 2>/dev/null` 与 `>/dev/null 2>nul`
        都是"文件还在、目录还在、errlevel=0"，只有不重定向或重定向到 `nul` 才真删。
        批处理里的空设备只有一个名字：nul。这条守卫防的是我下一次又顺手写 Unix 那套。
        """
        raw = (REPO_ROOT / "同步Gitee产物.bat").read_text(encoding="ascii")
        code = [ln for ln in raw.splitlines() if not ln.strip().upper().startswith("REM")]
        hits = [ln.strip()[:70] for ln in code if "/dev/null" in ln]
        self.assertEqual(hits, [],
                         ".bat 的执行行里出现 /dev/null：cmd 会去创建 \\dev\\null，"
                         f"失败后整条命令被丢弃且不报错 → {hits}")

    def test_bat_is_still_ascii_and_crlf(self):
        raw = (REPO_ROOT / "同步Gitee产物.bat").read_bytes()
        self.assertEqual(sorted({b for b in raw if b > 0x7F}), [],
                         "cmd 按字节偏移解析批处理，非 ASCII 会让语句错位被整段吞掉")
        self.assertEqual(raw.count(b"\n") - raw.count(b"\r\n"), 0,
                         "LF-only 批处理会导致标签查找失败")


class BatEndToEnd(unittest.TestCase):
    """Windows 版 .bat 的端到端流程：预检 → 复用 Release → 逐个上传 → 附件清单校验。

    只在 Windows 上跑（要 cmd.exe），API 指向同一个本地 mock，绝不碰真实 gitee.com；
    用几 KB 的假产物，免得把 220MB 灌进内存里的 mock。
    """

    @classmethod
    def setUpClass(cls):
        if not sys.platform.startswith("win"):
            raise unittest.SkipTest(".bat 只在 Windows 上验证")
        cls.srv = start_server()
        cls.port = cls.srv.server_address[1]

    def setUp(self):
        STATE.clear()
        STATE["assets"] = []
        STATE["body"] = ""
        STATE["reqs"] = []
        STATE["patch_fields"] = {}
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name in ARTIFACTS:
            (Path(self.tmp.name) / name).write_bytes(b"Z" * 2048)
        (Path(self.tmp.name) / "byte-tools.png").write_bytes(b"icon")

    def _run_bat(self, assets_dir, auto_fetch="0", extra_env=None):
        """跑真 .bat：API 指向本地 mock，AUTO_FETCH_ASSETS 默认关掉以保持离线。"""
        env = dict(os.environ)
        env["GITEE_API_BASE"] = f"http://127.0.0.1:{self.port}/api/existing_links/repos/owner/slug"
        env["NO_PAUSE"] = "1"
        env["AUTO_FETCH_ASSETS"] = auto_fetch   # 回归用例不许碰网络
        for k, v in (extra_env or {}).items():
            env[k] = v
        proc = subprocess.run(
            ["cmd.exe", "/c",
             f'{REPO_ROOT / "同步Gitee产物.bat"} {TAG} FAKE_TOKEN_NOT_REAL '
             f'{assets_dir} nopause'],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(REPO_ROOT), env=env, timeout=300)
        return proc, (proc.stdout or "") + (proc.stderr or "")

    def test_leftover_scratch_from_an_earlier_run_does_not_skip_uploads(self):
        """`%TEMP%\\bt_gitee_sync` 是固定路径，上一次真实发版留下的 assets.txt 会让本次
        把附件全判成"已存在，跳过"，然后在 [3/3] 报缺 —— 和暂存目录同一个病根：跨次残留。

        2026-10-10 实测现场：用户跑完 v1.2.0 的真同步之后，本文件的用例当场全红，
        那个文件里留着 `ByteTools-linux-x64 / ... / v1.2.0.zip / v1.2.0.tar.gz` 五行
        （Gitee 那次真实返回的附件名），于是 mock 说"什么都没有"脚本也说"都已经有了"。
        """
        scratch = Path(os.environ.get("TEMP") or "/tmp") / "bt_gitee_sync"
        scratch.mkdir(parents=True, exist_ok=True)
        (scratch / "assets.txt").write_text("\n".join(ARTIFACTS) + "\n", encoding="ascii")
        proc, out = self._run_bat(self.tmp.name)
        self.assertIn("done: uploaded 4, skipped 0, ignored 1", out,
                      f"残留的 assets.txt 让本次跳过了上传：{out}")
        self.assertEqual(proc.returncode, 0, out)

    def test_bat_uploads_all_four_and_verifies(self):
        proc, out = self._run_bat(self.tmp.name)
        self.assertEqual(proc.returncode, 0, out)
        self.assertIn("preflight ok: found 4 artifact file(s)", out)
        self.assertIn("release exists, reuse ID: 777", out)
        self.assertIn("skip non-artifact: byte-tools.png", out)
        self.assertIn("verified: all 4 artifacts present", out)
        self.assertIn("done: uploaded 4, skipped 0, ignored 1", out)
        self.assertEqual(sorted(STATE["assets"]), sorted(ARTIFACTS))
        # 上传必须带上可观测的 http/耗时/字节，别再回到「静默挂半小时」
        self.assertGreaterEqual(out.count("curl: http=200"), 4, out)
        self.assertNotIn("FAKE_TOKEN_NOT_REAL", out, "输出里回显了令牌")

    def test_offline_mode_does_not_wipe_the_staging_dir(self):
        """清空一步的闸门：下载开关关着（= 维护者手放的产物 / 回归用例）时一个字节都不许删。

        这里刻意把暂存目录的末级名取成 release-assets —— 也就是"名字符合清空条件"，
        唯一拦住它的必须只能是 AUTO_FETCH_ASSETS=0。
        """
        stage = Path(self.tmp.name) / "release-assets"
        stage.mkdir()
        for name in ARTIFACTS:
            (stage / name).write_bytes(b"Z" * 2048)
        marker = stage / "hand-placed.txt"
        marker.write_text("keep me")
        proc, out = self._run_bat(str(stage))
        self.assertEqual(proc.returncode, 0, out)
        self.assertTrue(marker.exists(),
                        "AUTO_FETCH_ASSETS=0 时脚本删掉了暂存目录里的文件")
        self.assertIn("preflight ok: found 4 artifact file(s)", out)
        self.assertEqual(sorted(STATE["assets"]), sorted(ARTIFACTS))

    def test_stale_artifact_is_cleared_and_refetched(self):
        """留一个上个版本的 ByteTools.exe，脚本必须删掉重下，而不是原样传上 Gitee。

        2026-10-10 用户实测撞到的：`:clear_stale` 写成 `rmdir ... >/dev/null 2>/dev/null`，
        cmd 把 `/dev/null` 当成"当前目录下的 \\dev\\null 文件"去创建，创建失败后**整条 rmdir
        被丢弃不执行**，而 ERRORLEVEL 仍是 0 —— 于是"清空 stale staging dir"照打、
        旧文件照传。当时这条只有文本契约（断言里有 rmdir 那三个字），所以全绿却全错；
        这条行为用例把 GH_ACCEL 指到本地 mock，才第一次真的把"清空 + 重下"跑了一遍。
        """
        stage = Path(self.tmp.name) / "release-assets"
        stage.mkdir()
        stale = stage / "ByteTools.exe"
        stale.write_bytes(b"OLD-VINTAGE" * 40)          # 440 B，远不到 1 MB 门槛
        proc, out = self._run_bat(
            str(stage), auto_fetch="1",
            extra_env={"GH_ACCEL": f"http://127.0.0.1:{self.port}/gh/"})
        self.assertIn("clearing stale staging dir", out)
        self.assertEqual(stale.stat().st_size, 1_100_000,
                         f"旧产物没被清掉重下 —— 传上 Gitee 的就是上个版本的包：{out}")
        self.assertEqual(sorted(STATE["assets"]), sorted(ARTIFACTS))
        self.assertEqual(proc.returncode, 0, out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
