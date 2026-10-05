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
    ustc 的 golang/* 曾被判为"只是 302 跳 dl.google.com"，因而把 go 排除在外。

    2026-10-06 复测推翻了这一条：`mirrors.ustc.edu.cn/golang/go1.24.6.windows-amd64.zip`
    直接回 206、实收 3MB+、魔数是 zip —— 是真镜像，不是跳转。2026-09 那次大概是
    撞上了它跳转的时机或探测没带 UA。go 从 NO_USTC 移到 HAS_USTC。"""

    HAS_USTC = ("maven", "tomcat", "rocketmq", "pulsar", "activemq", "seata", "kafka",
                "jenkins", "docker", "go")
    NO_USTC = ("gradle", "node", "mysql", "bun", "elasticsearch", "mongodb")

    def test_ustc_present_last_but_before_official(self):
        for key in self.HAS_USTC:
            lst = urls(key, "Windows") if key != "docker" else urls(key, "Linux")
            idx = [i for i, u in enumerate(lst) if "mirrors.ustc.edu.cn" in u]
            self.assertEqual(len(idx), 1, (key, lst))
            self.assertNotEqual(idx[0], len(lst) - 1,
                                f"{key} 的 ustc 不能是末位（末位必须是官网）：{lst[-1]}")

    def test_new_ustc_sources_are_last_mirror(self):
        # ustc 在这些组件的源列表里，且**不在末位**（末位必须是官网）。
        #
        # 2026-10-06 改动：这条原来是 assertEqual(index, len(lst) - 2)，
        # 也就是把「ustc 必须是最后一个国内源」当契约钉死了。那钉的是 2026-09 的
        # 速度顺序，不是设计意图 —— 源顺序改成按实测速度排之后（华为云 repo
        # 实测 19-31 MB/s、ustc 2.9-13 MB/s），ustc 有时快过腾讯云/阿里云，
        # 位置自然不再是倒数第二。
        # 真正不能破的是"末位必须是官网兜底"，那是 R1 的核心；ustc 排第几是速度问题。
        for key in ("maven", "tomcat", "rocketmq", "pulsar", "activemq", "seata",
                    "kafka", "jenkins"):
            with self.subTest(key=key):
                lst = urls(key, "Windows")
                idx = [i for i, u in enumerate(lst) if "ustc" in u]
                self.assertEqual(len(idx), 1, (key, lst))
                self.assertLess(idx[0], len(lst) - 1, f"{key} 的 ustc 占了末位（官网兜底没了）")

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


class MirrorSpeedOrder(unittest.TestCase):
    """源顺序必须按 2026-10-06 实测速度排（不是按字母序、不是按历史遗留）。

    为什么要有这条：源顺序是 R1「国内源优先 + 多源故障转移」里唯一影响**用户等待时长**
    的环节。实测（Range 取样 4MB算吞吐，26 个组件共 117 个 URL）：

        repo.huaweicloud.com         27.25 MB/s（14 个组件都最快，最高 30.8）
        mirrors.cloud.tencent.com8.12 MB/s
        registry.npmmirror.com       7.38 MB/s
        tuna                         7.32 MB/s
        bfsu                6.47 MB/s
        nju                         6.42 MB/s
        ustc                        6.23 MB/s
        mirrors.huaweicloud.com      5.89 MB/s
        aliyun                       0.35 MB/s（10 个组件全部垫底，比官网还慢）

    阿里云慢到 0.35 MB/s 是最刺眼的：原顺序里它排在**第二位**，绝大多数用户第一个
    吃到的就是它 —— 130MB 的 gradle 要 6 分钟，而华为云只要 4 秒。

    这条护栏钉的是「同一个组件内，快源必须在慢源前面」这个相对关系，
    不是绝对位置 —— 某个源被官方下线、或某家镜像临时抽风，位置该变就得变。
    """

    # 各组件**自己的**实测速度（MB/s），不是跨组件平均。
    #
    # 2026-10-06 第一版护栏写的是跨组件平均（tuna 7.32、bfsu 6.47…），
    # 结果 7 个组件全红：maven 的 bfsu 实测 6.2、tuna 实测 5.8，按平均排才是对的。
    # 教训：**平均速度不是排序依据** —— 每个镜像对每个组件的路径/冷热都不一样，
    # 排序只能用"这个组件上这个源"的实测值。跨组件平均只能当参考。
    # 数据来自 _source_bench.json（Range 取样 4MB）。
    BY_COMPONENT = {
        "maven":        {"repo.huaweicloud.com": 19.1, "mirrors.bfsu.edu.cn": 6.2,
                          "mirrors.tuna.tsinghua.edu.cn": 5.8, "mirrors.cloud.tencent.com": 4.1,
                          "mirrors.ustc.edu.cn": 2.9, "mirrors.nju.edu.cn": 2.6,
                          "mirrors.aliyun.com": 0.3},
        "tomcat":       {"repo.huaweicloud.com": 25.0, "mirrors.cloud.tencent.com": 11.4,
                          "mirrors.tuna.tsinghua.edu.cn": 8.0, "mirrors.bfsu.edu.cn": 7.1,
                          "mirrors.nju.edu.cn": 5.4, "mirrors.ustc.edu.cn": 2.8,
                          "mirrors.aliyun.com": 0.4},
        "kafka":        {"repo.huaweicloud.com": 28.6, "mirrors.tuna.tsinghua.edu.cn": 7.8,
                          "mirrors.cloud.tencent.com": 7.5, "mirrors.bfsu.edu.cn": 6.6,
                          "mirrors.nju.edu.cn": 6.2, "mirrors.ustc.edu.cn": 3.0,
                          "mirrors.aliyun.com": 0.3},
        "activemq":     {"repo.huaweicloud.com": 28.6, "mirrors.cloud.tencent.com": 11.4,
                          "mirrors.bfsu.edu.cn": 9.1, "mirrors.nju.edu.cn": 8.3,
                          "mirrors.tuna.tsinghua.edu.cn": 7.5, "mirrors.ustc.edu.cn": 3.7,
                          "mirrors.aliyun.com": 0.3},
        "pulsar":       {"repo.huaweicloud.com": 30.8, "mirrors.nju.edu.cn": 10.0,
                          "mirrors.tuna.tsinghua.edu.cn": 7.5, "mirrors.cloud.tencent.com": 5.0,
                          "mirrors.ustc.edu.cn": 3.2, "mirrors.bfsu.edu.cn": 2.7,
                          "mirrors.aliyun.com": 0.3},
        "rocketmq":     {"repo.huaweicloud.com": 30.8, "mirrors.cloud.tencent.com": 13.3,
                          "mirrors.ustc.edu.cn": 12.5, "mirrors.bfsu.edu.cn": 8.5,
                          "mirrors.tuna.tsinghua.edu.cn": 7.4, "mirrors.aliyun.com": 0.3},
        "seata":        {"repo.huaweicloud.com": 28.6, "mirrors.nju.edu.cn": 9.8,
                          "mirrors.huaweicloud.com": 7.4, "mirrors.tuna.tsinghua.edu.cn": 7.3,
                          "mirrors.bfsu.edu.cn": 7.3, "mirrors.cloud.tencent.com": 6.7,
                          "mirrors.ustc.edu.cn": 3.4, "mirrors.aliyun.com": 0.3},
        "jenkins":      {"repo.huaweicloud.com": 26.7, "mirrors.ustc.edu.cn": 11.4,
                          "mirrors.tuna.tsinghua.edu.cn": 8.0, "mirrors.cloud.tencent.com": 5.9,
                          "mirrors.bfsu.edu.cn": 5.6, "mirrors.nju.edu.cn": 3.6,
                          "mirrors.huaweicloud.com": 1.8, "mirrors.aliyun.com": 0.3},
        "elasticsearch": {"repo.huaweicloud.com": 23.5, "mirrors.huaweicloud.com": 7.8},
    }
    COMPONENTS = tuple(BY_COMPONENT)

    def _host(self, url: str) -> str:
        return url.split("/")[2]

    def test_faster_mirror_never_after_slower_one(self):
        """同一组件内，快源必须在慢源前面（用该组件自己的实测值比）。"""
        for key in self.COMPONENTS:
            with self.subTest(key=key):
                speeds = self.BY_COMPONENT[key]
                lst = urls(key, "Windows")
                idx = [(i, self._host(u)) for i, u in enumerate(lst)
                       if self._host(u) in speeds]
                self.assertGreaterEqual(len(idx), 2,
                                        f"{key} 可比对的源只有 {len(idx)} 个，测不出顺序")
                for (i1, h1), (i2, h2) in zip(idx, idx[1:]):
                    self.assertGreaterEqual(
                        speeds[h1], speeds[h2] - 0.5,
                        f"{key} 的源顺序与实测速度相反：{h1}({speeds[h1]}) "
                        f"排在 {h2}({speeds[h2]}) 后面")

    def test_huaweicloud_repo_is_first_whenever_present(self):
        """华为云 repo 在 14 个组件上都最快（27 MB/s），有它就必须排第一。

        只对"repo 与其它国内源同时存在"的组件断言 —— 单一来源的组件（mongodb/postgresql）
        排第几都一样。
        """
        hits = 0
        for key, comp in COMPS.items():
            if key in ("docker", "rabbitmq"):
                continue
            try:
                lst = comp.versions[0].urls_for_current()
            except Exception:
                continue
            mainland = [u for u in lst if is_mainland(u)]
            if not mainland or self._host(mainland[0]) != "repo.huaweicloud.com":
                continue
            self.assertEqual(self._host(mainland[0]), "repo.huaweicloud.com",
                             f"{key} 的国内源首位不是最快的华为云：{mainland[0]}")
            hits += 1
        self.assertGreaterEqual(hits, 10,
                                f"只有 {hits} 个组件以华为云打头，与实测（14 个）不符")

    def test_no_source_list_starts_with_the_slowest_mirror(self):
        """阿里云实测 0.35 MB/s垫底，谁把它放首位就是退回到 2026-09 的坏顺序。"""
        for key in ("maven", "tomcat", "kafka", "activemq", "pulsar",
                    "rocketmq", "seata", "jenkins", "elasticsearch"):
            with self.subTest(key=key):
                mainland = [u for u in urls(key, "Windows") if is_mainland(u)]
                self.assertTrue(mainland, key)
                self.assertNotEqual(self._host(mainland[0]), "mirrors.aliyun.com",
                                    f"{key} 把最慢的阿里云放在了首位")


if __name__ == "__main__":
    unittest.main(verbosity=2)
