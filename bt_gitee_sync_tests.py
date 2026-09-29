"""同步Gitee产物.sh 的离线端到端测试（本地 mock Gitee，绝不碰真实 gitee.com）。

为什么要有这份测试：这个脚本已经坑过三次（v1.0.3/v1.0.4 静默少传、境外 runner 上传挂死），
而它跑在 CI 里、只有真发版时才被执行一次，靠肉眼读 shell 不靠谱。

做法：用 http.server 在 127.0.0.1 起一个假 Gitee，把场景名编进 GITEE_API_BASE 的路径前缀，
脚本用同一份代码走完整流程；断言看退出码 + stdout/stderr 文本。

场景（对应被测行为）：
  new              —— 无 Release：创建时正文必须带 4 条 GitHub 直链，默认一个产物都不传
  existing_no_links—— Release 已存在且正文没直链：必须硬失败并给出网页端/重建两条补救
  existing_links   —— 已存在且正文有直链、上传清单为空：通过
  upload_ok        —— UPLOAD_ARTIFACTS 指定产物：已存在的跳过、缺失的上传并校验通过
  upload_missing   —— 上传接口假装成功但附件清单没它：必须硬失败
  server500        —— 全程 500：按 MAX_ATTEMPTS 重试后失败，且每次都打了可见日志
  client400        —— 4xx：立即判死，不浪费重试
"""
import os
import re
import shutil
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO_ROOT = Path(r"E:\file\test\byte-tools")
SCRIPT = REPO_ROOT / "同步Gitee产物.sh"
TAG = "vTEST"
GH_BASE = f"https://github.com/owner/slug/releases/download/{TAG}"
ARTIFACTS = ["byte-tools.exe", "byte-tools-windows-x64.zip",
             "byte-tools-macos-arm64.zip", "byte-tools-linux-x64"]

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
            return self.send_json(200, '{"id": 777, "tag_name": "%s"}' % TAG)
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


def start_server():
    srv = HTTPServer(("127.0.0.1", 0), MockGitee)
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
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_script(self, scenario, extra_env=None, assets_dir=None, max_attempts=2):
        env = dict(os.environ)
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
        })
        for k, v in (extra_env or {}).items():
            env[k] = v
        proc = subprocess.run([BASH, "-l", str(SCRIPT)], capture_output=True, text=True,
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

    def test_404_on_tags_lookup_is_not_an_error(self):
        # 真实 Gitee 返回 200 + null（见 new 场景），仓库不存在才 404；两种都要能走到「创建」
        code, out = self.run_script("repo404")
        self.assertEqual(code, 0, out)
        self.assertIn("尚无 Release，创建中...", out)
        self.assertIn("创建成功，Release ID: 777", out)

    def test_existing_release_without_links_fails_loudly_with_remedies(self):
        STATE["body"] = "跨平台构建产物（旧默认说明，没有直链）"
        code, out = self.run_script("existing_no_links")
        self.assertEqual(code, 1, out)
        self.assertIn("没有 GitHub 直链", out)
        self.assertIn("A) 在 Gitee 网页端", out)
        self.assertIn("B) 删掉 Gitee 的这个 Release", out)

    def test_existing_release_with_links_passes(self):
        STATE["body"] = f"产物见 {GH_BASE}/byte-tools.exe"
        code, out = self.run_script("existing_links")
        self.assertEqual(code, 0, out)
        self.assertIn("Release 之前已存在，正文沿用现有内容", out)

    # ---------- 场景 2：显式要求上传（小包）时按清单走 ----------
    def test_upload_subset_skips_existing_and_uploads_missing(self):
        STATE["body"] = GH_BASE  # 让收尾校验通过
        STATE["assets"] = ["byte-tools.exe"]      # 这个已经在 Gitee 上
        code, out = self.run_script(
            "existing_links",
            {"UPLOAD_ARTIFACTS": "byte-tools.exe|byte-tools-linux-x64"})
        self.assertEqual(code, 0, out)
        self.assertIn("已存在，跳过: byte-tools.exe", out)
        self.assertIn("成功: https://x/", out)
        self.assertIn("同步完成：上传 1 个，跳过已存在 1 个，按策略不上传 2 个", out)

    def test_upload_claimed_ok_but_asset_missing_fails(self):
        STATE["body"] = GH_BASE
        code, out = self.run_script("upload_missing",
                                    {"UPLOAD_ARTIFACTS": "byte-tools-linux-x64"})
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
                                    extra_env={"UPLOAD_ARTIFACTS": "byte-tools.exe"})
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
        self.assertIn(f"{GH_BASE}/byte-tools.exe", STATE["body"])

    def test_missing_dir_reports_curl_hint(self):
        code, out = self.run_script("new",
                                    assets_dir=str(Path(self.tmp.name) / "nope"))
        self.assertEqual(code, 1, out)
        self.assertIn("产物目录不存在", out)
        self.assertIn("curl -L -o", out)
        self.assertEqual(STATE["reqs"], [])


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
