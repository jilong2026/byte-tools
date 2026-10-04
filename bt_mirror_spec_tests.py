"""全 24 组件镜像源配置的规格测试（离线断言，实测结论已写死在这里）。

实测时间：2026-09-28，方法见 bt_cand.py / bt_cand2.py / bt_matrix.out：
  GET + UA:byte-tools，读状态码、Content-Length 与首 4 字节魔数。
  注意：不带 UA 时清华/北外/中科大一律 403，中科大 apache/* 曾被误判成假源；
  带 UA 复测后 ustc 的 apache/* 与 jenkins、docker-ce 是真包，golang/* 只是 302 跳 dl.google.com。

本机 WMI 服务卡死会让 platform.system() 永久阻塞，因此这里先把它 stub 掉，
只影响测试进程，不改仓库代码。
"""
import os
import sys
import unittest

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


def default_cv(key):
    return COMPS[key].versions[0]


def cv_urls(cv, os_key):
    """某个版本在某个平台上的全部候选 URL（多源列表优先，否则单源）。"""
    lst = list((cv.url_list_map or {}).get(os_key) or [])
    if not lst:
        single = (cv.url_map or {}).get(os_key)
        if single:
            lst = [single]
    return lst


def urls(key, os_key):
    return cv_urls(default_cv(key), os_key)


def all_urls(key):
    """该组件所有版本、所有平台、所有模式的 URL 扁平表。"""
    out = []
    for cv in COMPS[key].versions:
        for bucket in ((cv.url_list_map or {}), (cv.url_map or {})):
            for value in bucket.values():
                if isinstance(value, list):
                    out.extend(value)
                elif value:
                    out.append(value)
    return out


# 实测「同步了当前版本」的大陆镜像域名（这些站对 apache/* 只保留最新版）
FULL_HISTORY_HOSTS = ("repo.huaweicloud.com",)          # 华为云 repo 保留全量历史
MAINLAND_MARKERS = ("huaweicloud", "aliyun", "tuna", "bfsu", "nju", "ustc",
                    "sjtu", "npmmirror", "cloud.tencent", "daocloud",
                    "ghproxy.net", "ghfast.top", "gh-proxy.com")


def is_mainland(u: str) -> bool:
    return any(m in u for m in MAINLAND_MARKERS)


class DeadSourceMustNotAppear(unittest.TestCase):
    """实测已死的源，一个都不许再出现在配置里。"""

    DEAD_SUBSTRINGS = [
        "ghproxy.com/",                  # 已停服（注意 ghproxy.net 是活的）
        "gh.idayer.com",                 # 已停服
        "mirrors.ustc.edu.cn/mongodb/",  # 404（不同步 fastdl 二进制树）
        "repo.huaweicloud.com/anaconda/",  # 任意不存在文件都回 200（假镜像）
        "mirrors.tuna.tsinghua.edu.cn/gradle/",   # 无 gradle 目录
        "mirrors.tuna.tsinghua.edu.cn/golang/",   # 无 golang 目录
        "mirrors.tuna.tsinghua.edu.cn/mongodb/",  # 只有 apt/yum
        "mirrors.tuna.tsinghua.edu.cn/postgresql/",  # 无 postgresql 目录
        "mirrors.tuna.tsinghua.edu.cn/elasticstack/",  # 只有 apt/yum
        "mirrors.tuna.tsinghua.edu.cn/elasticsearch/",
        "mirrors.aliyun.com/mongodb/", "mirrors.aliyun.com/elasticsearch/",
        "mirrors.aliyun.com/gradle/",    # 404
        "repo.huaweicloud.com/golang/", "mirrors.huaweicloud.com/golang/",  # 401
        "repo.huaweicloud.com/mongodb/",  # 只有 C++ 源码包
    ]

    def test_no_dead_source_anywhere(self):
        hits = []
        for key in COMPS:
            for u in all_urls(key):
                for dead in self.DEAD_SUBSTRINGS:
                    if dead in u:
                        hits.append(f"{key}: {u}")
        self.assertEqual(hits, [], "配置里仍有实测已死的源：\n" + "\n".join(hits))


class WindowsDefaultMustHaveTwoMainlandSources(unittest.TestCase):
    """R1.1：默认版本的 Windows 源列表里，至少 2 个大陆源，官网在末位。"""

    # 实测「全网无大陆镜像」/「默认清单离线构造」的组件，按 R1.1 走登记例外
    #   kubectl：DaoCloud 反代是唯一大陆源
    #   mongodb / postgresql：fastdl / EDB 无人镜像，只有官方源
    #   jdk：默认清单不许联网，镜像要等「刷新版本」时列目录才能拿到确切文件名
    SINGLE_SOURCE_EXCEPTION = {"kubectl": 1, "mongodb": 0, "postgresql": 0, "jdk": 0}

    def test_counts(self):
        for key, comp in COMPS.items():
            lst = comp.versions[0].urls_for_current()
            if not lst:
                continue          # docker/rabbitmq 在 Windows 不发静态包，属正常
            cn = [u for u in lst if is_mainland(u)]
            if key in self.SINGLE_SOURCE_EXCEPTION:
                expected = self.SINGLE_SOURCE_EXCEPTION[key]
                self.assertEqual(len(cn), expected, f"{key} 例外源数量变了：{lst}")
            else:
                self.assertGreaterEqual(len(cn), 2,
                                        f"{key} Windows 只有 {len(cn)} 个大陆源：{lst}")
            last = lst[-1]
            self.assertFalse(is_mainland(last), f"{key} 末位不是官方源：{last}")


class OfficialIsLast(unittest.TestCase):
    OFFICIAL_HOST = {
        "maven": "archive.apache.org", "tomcat": "archive.apache.org",
        "kafka": "archive.apache.org", "rocketmq": "archive.apache.org",
        "pulsar": "archive.apache.org", "activemq": "archive.apache.org",
        "gradle": "services.gradle.org", "go": "go.dev",
        "jenkins": "get.jenkins.io", "python": "python.org",
        "node": "nodejs.org", "git": "github.com", "conda": "repo.anaconda.com",
        "mysql": "cdn.mysql.com", "jdk": "adoptium.net", "mongodb": "mongodb.org",
        "postgresql": "enterprisedb.com", "kubectl": "dl.k8s.io",
        "elasticsearch": "elastic.co", "nacos": "github.com", "rabbitmq": "github.com",
        "seata": "archive.apache.org",
        "bun": "github.com", "docker": "download.docker.com",
    }

    def test_official_last(self):
        for key, host in self.OFFICIAL_HOST.items():
            for cv in COMPS[key].versions:
                for os_key, lst in (cv.url_list_map or {}).items():
                    if not lst:
                        continue
                    self.assertIn(host, lst[-1],
                                  f"{key}/{cv.version}/{os_key} 末位应是 {host}，"
                                  f"实际 {lst[-1]}")


class UstcMustBeUsedWhereMeasured(unittest.TestCase):
    """2026-09-28 带 byte-tools UA 复测：ustc 的 apache/*（maven/tomcat/kafka/rocketmq/pulsar/
    activemq/incubator-seata）、jenkins、docker-ce 都是真包（GET 回gzip/zip 魔数），必须作为额外
    大陆源出现在这些组件的列表末位（镜像优先级最低，但仍在前于官网）。
    ustc 的 golang/* 只是 302 跳 dl.google.com（本机 TLS 握手失败），等于没有镜像，不得引入。"""

    HAS_USTC = ("maven", "tomcat", "rocketmq", "pulsar", "activemq", "seata", "kafka",
                "jenkins", "docker")
    NO_USTC = ("go", "gradle", "node", "mysql", "bun", "elasticsearch", "mongodb")

    def test_ustc_present_last_but_before_official(self):
        for key in self.HAS_USTC:
            lst = urls(key, "Windows") if key != "docker" else urls(key, "Linux")
            idx = [i for i, u in enumerate(lst) if "mirrors.ustc.edu.cn" in u]
            self.assertEqual(len(idx), 1, (key, lst))
            self.assertNotEqual(idx[0], len(lst) - 1,
                                f"{key} 的 ustc 不能是末位（末位必须是官网）：{lst[-1]}")

    def test_new_ustc_sources_are_last_mirror(self):
        # 新加的 ustc 排在所有大陆源之后、官网之前
        for key in ("maven", "tomcat", "rocketmq", "pulsar", "activemq", "seata",
                    "kafka", "jenkins"):
            lst = urls(key, "Windows")
            self.assertEqual(lst.index(next(u for u in lst if "ustc" in u)), len(lst) - 2, key)

    def test_ustc_absent_where_measured_dead(self):
        for key in self.NO_USTC:
            for u in all_urls(key):
                self.assertNotIn("mirrors.ustc.edu.cn", u, key)


class GitUnixSourceTarballMustNotBeOffered(unittest.TestCase):
    """git 在 Linux/macOS 只能下到 git/git 的源码 tar.gz，解压后没有可执行文件（要自己编译）。

    2026-09-28 决定：不再把它当下载源列出来（用户会下一个用不了的东西），
    改为空列表 + unsupported_platform_hint 引导用发行版包管理器。
    """

    def test_git_offers_no_url_on_unix_platforms(self):
        for os_key in ("Darwin", "Linux"):
            for cv in COMPS["git"].versions:
                self.assertFalse(cv_urls(cv, os_key),
                                 f"git {cv.version}/{os_key} 仍在给源码包 URL")
                self.assertFalse(main._git_urls(cv.version).get(os_key),
                                 f"_git_urls({cv.version}) 仍返回 {os_key} 条目")

    def test_git_unix_hint_points_to_package_manager(self):
        hint = COMPS["git"].unsupported_platform_hint or ""
        self.assertTrue(hint, "git 缺 unsupported_platform_hint")
        self.assertTrue(any(k in hint for k in ("apt", "dnf", "yum", "brew")), hint)


class MeasuredAssetNames(unittest.TestCase):
    """今天实测纠正的文件名/路径。"""

    def test_activemq_uses_apache_prefix(self):
        # 6.x 也叫 apache-activemq-<v>-bin，不存在 activemq-apache-<v>-bin
        for u in all_urls("activemq"):
            self.assertNotIn("activemq-apache-", u)

    def test_activemq_default_version_is_live(self):
        self.assertEqual(default_cv("activemq").version, "6.3.2")

    def test_seata_uses_huawei_apache_dist_and_tar_gz(self):
        # GitHub release 从 v2.1.0 起资产数为 0，二进制只在 Apache dist
        for u in urls("seata", "Windows"):
            self.assertTrue("apache/incubator/seata" in u or "archive.apache.org" in u, u)
            self.assertTrue(u.endswith(".tar.gz"), u)

    def test_kafka_windows_is_tgz(self):
        # Kafka 只发 tgz，从不发 zip
        for u in all_urls("kafka"):
            self.assertTrue(u.endswith(".tgz"), f"kafka 不发 zip：{u}")
        self.assertEqual(default_cv("kafka").archive_map.get("Windows"), "tar.gz")

    def test_rabbitmq_uses_rabbitmq_server_dir(self):
        # 华为云真实目录是 /rabbitmq-server/v<ver>/，不是 /rabbitmq/
        for u in urls("rabbitmq", "Linux")[:2]:
            self.assertIn("/rabbitmq-server/v", u)

    def test_rabbitmq_default_version_exists_upstream(self):
        # 上游没有 4.0.0（4.0.x 从 v4.0.1 起）
        self.assertNotIn(default_cv("rabbitmq").version, ("4.0.0", "3.13.7"))
        self.assertEqual(default_cv("rabbitmq").version, "4.0.9")

    def test_rabbitmq_windows_is_documented_exception(self):
        # generic-unix 包依赖 Erlang，Windows 一律不自动下载，改走引导文案
        self.assertFalse(urls("rabbitmq", "Windows"))
        self.assertIn("Erlang", COMPS["rabbitmq"].unsupported_platform_hint or "")

    def test_elasticsearch_huawei_path_has_version_dir(self):
        # 华为云布局是 /elasticsearch/<version>/<file>；缺版本目录段就是原代码 404 的根因
        v = default_cv("elasticsearch").version
        for u in urls("elasticsearch", "Windows"):
            if "huaweicloud" in u:
                self.assertIn(f"/elasticsearch/{v}/", u)
            self.assertTrue(u.endswith(".zip"), u)

    def test_mongodb_linux_name_has_distro_segment(self):
        # fastdl 的 Linux 包名必须带发行版段，否则恒 403
        for u in urls("mongodb", "Linux"):
            if "fastdl" in u:
                self.assertRegex(u, r"linux-x86_64-[a-z0-9]+-\d.*\.tgz$")

    def test_mysql_default_windows_version_is_on_mirrors(self):
        # 阿里/华为只同步到 8.0.28/8.0.29
        self.assertEqual(default_cv("mysql").version, "8.0.28")

    def test_mysql_linux_uses_glibc212_on_mirrors(self):
        for u in urls("mysql", "Linux"):
            if not u.startswith("https://cdn.mysql.com"):
                self.assertIn("glibc2.12", u)

    def test_mysql_darwin_lists_mirror_names_before_cdn(self):
        # 官方 CDN 只挂最新版（8.0.28/8.0.29 的 macos14 实测恒 404），镜像站留着
        # 老版本当年命名的包（8.0.28→macos11、8.0.29→macos12），所以 Darwin 必须
        # 是"镜像在前的多源列表"，且带 macos11/macos12 候选名，官方 macos14 末位。
        for cv in COMPS["mysql"].versions:
            lst = cv_urls(cv, "Darwin")
            self.assertGreaterEqual(len(lst), 4, (cv.version, lst))
            self.assertTrue(
                any(("macos11" in u or "macos12" in u) and is_mainland(u) for u in lst),
                (cv.version, lst))
            self.assertTrue(lst[-1].startswith("https://cdn.mysql.com"), lst[-1])
            self.assertIn("macos14", lst[-1])
            # 不能把只有镜像才有的老命名放在官方 CDN 上（那边一定 404）
            self.assertTrue(all("macos14" in u for u in lst if u.startswith("https://cdn.mysql.com")), lst)

    def test_git_windows_has_real_mirror_not_only_accelerator(self):
        lst = urls("git", "Windows")
        self.assertIn("git-for-windows", lst[0])
        self.assertFalse(lst[0].startswith("https://gh"), lst[0])

    def test_jenkins_default_version_is_on_all_mirrors(self):
        # 镜像的 war-stable 只保留最近 4 条 LTS 线
        self.assertEqual(default_cv("jenkins").version, "2.568.3")

    def test_bun_default_version_has_windows_asset(self):
        # 1.0.20/1.0.29/1.0.30 的 release 里没有 Windows 包
        self.assertNotIn(default_cv("bun").version, ("1.0.30", "1.0.29", "1.0.20"))

    def test_python_default_versions_have_embed(self):
        # 3.10.14 / 3.9.19 是 security-only 发布，官方 ftp 里没有 embed 包
        vers = [cv.version for cv in COMPS["python"].versions]
        self.assertNotIn("3.10.14", vers)
        self.assertNotIn("3.9.19", vers)

    def test_kubectl_uses_daocloud_then_official(self):
        lst = urls("kubectl", "Windows")
        self.assertIn("files.m.daocloud.io", lst[0])
        self.assertIn("dl.k8s.io", lst[-1])

    def test_docker_keeps_ustc_and_has_five_mainland(self):
        # ustc 的 docker-ce 是真镜像（75MB gzip），与 apache/* 行为不同
        lst = urls("docker", "Linux")
        self.assertGreaterEqual(len([u for u in lst if is_mainland(u)]), 5)


class UrlsForCurrentStillWorks(unittest.TestCase):
    def test_every_component_returns_on_windows(self):
        for key, comp in COMPS.items():
            if key in ("docker", "rabbitmq"):
                continue      # Windows 无静态包 / 依赖 Erlang，属登记例外
            self.assertTrue(comp.versions[0].urls_for_current(),
                            f"{key} 在本机没有可用下载地址")


if __name__ == "__main__":
    unittest.main(verbosity=2)
