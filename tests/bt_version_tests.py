"""版本号语义的特征化测试（离线）。

跑法：`.venv/Scripts/python.exe -u bt_version_tests.py`

**这个文件在重构前就该是绿的。** 它的作用不是判对错，而是把
`main.py` 里三套并存的版本比较语义的**当前行为逐格锁死**，
包括那些"看起来像 bug、其实是承重设计"的地方。

三套实现与它们的分歧（2026-10-14 收敛前的实测表）：

| 输入            | `_version_parts` | `_semver_key` | `_version_key` |
|-----------------|-----------------|---------------|----------------|
| `21.0.4`        | (21, 0, 4)      | (21, 0, 4)    | (21, 0, 4)     |
| `21.0.4-beta`   | (21, 0, 4)      | **(0,)**      | **(0,)**       |
| `v1.10.2`       | (1, 10, 2)      | **(0,)**      | (0, 10, 2)     |
| `jdk-21.0.5`    | **None**        | (0,)          | (21, 0, 5)     |
| `3.12.1rc1`     | (3, 12, 1)      | **(0,)**      | (3, 12, 0)     |
| `1.0.0_1`       | (1, 0, 0)       | (1, 0, 1)     | (1, 0, 0)      |

`1.0.0_1` 那一格是纯 Python 巧合：`int("0_1") == 1`，所以严格档认它，
而"取开头连续数字"的宽松档只取到 `0`。

**为什么这些分歧必须保留，而不是"顺手统一"**：

- `_semver_key` 把任何带后缀的版本打成 `(0,)`，于是 beta / rc / 带 v 前缀的
  条目在**排序时一律沉底**。这正是"预发布版不该被当成更新"的实现方式。
  改成宽松档的话，`21.0.4-beta` 会按 21.0.4 参与排序、排在正式版旁边 ——
  用户就会看到"检测到新版本 21.0.4-beta"。（那个错位是承重的。）
- `_version_key` 服务的是**安装目录名**（`jdk-21.0.5`），前缀 `jdk-` 必须先剥掉；
  非数字段补 0 而不是判废，是为了 `3.12.1rc1` 这种目录仍能参与排序。
- `_version_parts` 服务的是**识别与更新比较**，遇到 `jdk-21.0.5` 必须返回 None，
  因为"这不是一个版本号"和"这是 21.0.5"是两回事。

所以 `Version` 值对象把这三种口径都建成**具名的方法**，而不是抹平成一种。
真要统一口径，那是行为变更，得先在别处解决（见文件末尾 `KnownDivergences`）。
"""
import os
import sys
import unittest

import _btprelude  # noqa: F401  必须早于 import main：打 WMI 桩 + offscreen + sys.path

REPO_ROOT = str(_btprelude.REPO_ROOT)

import main  # noqa: E402


# 与 main.py 里三套实现收敛前的实测结果逐格对应。
# 改这个表 = 改行为，必须是有意识的决定，不是重构的副作用。
CHARACTERIZATION = [
    # (输入,        _version_parts, _semver_key, _version_key)
    ("21",          (21,),         (21,),      (21,)),
    ("21.0.4",      (21, 0, 4),    (21, 0, 4), (21, 0, 4)),
    ("21.0.4-beta", (21, 0, 4),    (0,),       (0,)),
    ("v1.10.2",     (1, 10, 2),    (0,),       (0, 10, 2)),
    ("2.10.0",      (2, 10, 0),    (2, 10, 0), (2, 10, 0)),
    ("2.9.0",       (2, 9, 0),     (2, 9, 0),  (2, 9, 0)),
    ("1.2.3",       (1, 2, 3),     (1, 2, 3),  (1, 2, 3)),
    ("jdk-21.0.5",  None,          (0,),       (21, 0, 5)),
    ("jdk-17",      None,          (0,),       (17,)),
    ("3.12.1rc1",   (3, 12, 1),    (0,),       (3, 12, 0)),
    ("1.0.0_1",     (1, 0, 0),     (1, 0, 1),  (1, 0, 0)),
    ("8",           (8,),          (8,),       (8,)),
    ("LTS",         None,          (0,),       (0,)),
    ("",            None,          (0,),       (0,)),
]


class VersionSemantics(unittest.TestCase):
    """三套比较语义的当前行为，逐格锁死。"""

    def test_version_parts_table(self):
        for text, expected, _sk, _vk in CHARACTERIZATION:
            with self.subTest(输入=text):
                self.assertEqual(main._version_parts(text), expected)

    def test_semver_key_table(self):
        for text, _vp, expected, _vk in CHARACTERIZATION:
            with self.subTest(输入=text):
                self.assertEqual(main._semver_key(text), expected)

    def test_version_key_table(self):
        for text, _vp, _sk, expected in CHARACTERIZATION:
            with self.subTest(输入=text):
                self.assertEqual(main._version_key(text), expected)

    def test_none_input_does_not_crash(self):
        """None / 非字符串不许抛异常。

        版本号会从版本命令的 stdout、目录名、release tag 三处来，
        其中任意一处都可能给出 None —— 崩溃一次就等于界面打不开。
        """
        for text in (None, 21, object()):
            with self.subTest(输入=text):
                main._version_parts(text)
                main._version_key(text)

    # ------------------------------------------------------------------
    # 排序口径
    # ------------------------------------------------------------------
    def test_numeric_segment_order_beats_string_order(self):
        """`2.10.0 > 2.9.0` —— 字符串比会反过来。

        这是三套实现共同的硬约束（`_version_key` 的 docstring 专门记了这个坑：
        "按数值分段比而不是字符串比，字符串比会得出 1.9 > 1.10"）。
        """
        ordered = main._sort_semver_desc(["2.9.0", "2.10.0", "1.9", "1.10"])
        self.assertEqual(ordered[:2], ["2.10.0", "2.9.0"])
        self.assertLess(ordered.index("1.10"), ordered.index("1.9"))

    def test_prereleases_sink_to_the_bottom(self):
        """预发布版在排序里沉底 —— 靠 `_semver_key` 把它打成 (0,) 实现。

        这条单独钉出来，是因为它最容易被"顺手统一成宽松档"改掉，
        而改掉的后果是用户看到"检测到新版本 21.0.4-beta"。
        """
        vs = ["21.0.4", "21.0.4-beta", "2.10.0", "2.9.0"]
        filtered = [v for v in vs if main._version_parts(v) is not None]
        ordered = main._sort_semver_desc(filtered)
        self.assertEqual(ordered[-1], "21.0.4-beta",
                         "预发布版必须排在最后（它不是给用户装的版本）")
        self.assertEqual(ordered[0], "21.0.4")

    def test_install_dir_sorting_keeps_prefix_stripped(self):
        """安装目录名排序要剥掉 `jdk-` 前缀。"""
        dirs = ["jdk-2.9.0", "jdk-2.10.0", "jdk-17"]
        ordered = sorted(dirs, key=main._version_key, reverse=True)
        self.assertEqual(ordered[0], "jdk-17")
        self.assertEqual(ordered[1], "jdk-2.10.0")

    def test_sort_semver_desc_deduplicates(self):
        """降序排序同时去重 —— 同一版本号在清单里出现两次只算一次。"""
        self.assertEqual(main._sort_semver_desc(["1.0", "1.0", "2.0"]), ["2.0", "1.0"])

    # ------------------------------------------------------------------
    # 更新比较
    # ------------------------------------------------------------------
    def test_version_is_newer_uses_numeric_segments(self):
        self.assertTrue(main.version_is_newer("1.9", "1.10"))
        self.assertFalse(main.version_is_newer("2.0.0", "1.9.9"))
        self.assertFalse(main.version_is_newer("1.2.3", "1.2.3"), "相同版本不算更新")

    def test_version_is_newer_is_false_when_either_side_is_unparseable(self):
        """任一边读不出数字段，一律判"不是更新" —— 宁可不提示也不猜。"""
        for cur, lat in (("21.0.4", "LTS"), ("LTS", "21.0.4"), ("", "1.0"), ("1.0", "")):
            with self.subTest(current=cur, latest=lat):
                self.assertFalse(main.version_is_newer(cur, lat))

    def test_prerelease_is_not_newer_than_its_release(self):
        """`21.0.4-beta` 不该被判成比 `21.0.4` 新。"""
        self.assertFalse(main.version_is_newer("21.0.4", "21.0.4-beta"))

    def test_v_prefix_is_tolerated(self):
        """tag 带不带 v 前缀都要认（GitHub 的 tag 就是 `v1.2.3`）。"""
        self.assertEqual(main._version_parts("v1.2.3"), (1, 2, 3))
        self.assertTrue(main.version_is_newer("1.2.3", "v1.3.0"))
        self.assertTrue(main.version_is_newer("1.2.3", "V1.3.0"))

    # ------------------------------------------------------------------
    # 从命令输出里抽版本号（第三种职责：解析，不是比较）
    # ------------------------------------------------------------------
    def test_extract_version_text_pulls_a_version_out_of_command_output(self):
        cases = [
            ('openjdk version "21.0.2" 2024-01-16', "21.0.2"),
            ("Apache Maven 3.9.6 (bc0240f3c744dd6b6c8bdc4d8c2d4b5c)", "3.9.6"),
            ("v20.11.1", "20.11.1"),
            ("Go version go1.22.5 windows/amd64", "1.22.5"),
        ]
        for raw, want in cases:
            with self.subTest(raw=raw):
                self.assertEqual(main._extract_version_text(raw), want)

    def test_extract_version_text_falls_back_to_truncated_raw(self):
        """抽不出就返回原文截断 —— 比空串有用（用户还能看见厂商打印了什么）。"""
        self.assertEqual(main._extract_version_text(""), "")
        self.assertEqual(main._extract_version_text("some unversioned output"),
                         "some unversioned output"[:40])

    # ------------------------------------------------------------------
    # Version 值对象（本轮新增）
    # ------------------------------------------------------------------
    def test_version_value_object_exposes_the_three_named_policies(self):
        """三种口径是**具名方法**，不是抹平成一种。

        抹平的后果：预发布版不再沉底、安装目录前缀被当成版本号的一部分、
        `jdk-21.0.5` 不再返回 None —— 三处行为一起变，且都不报错。
        """
        v = main.Version.parse("21.0.4-beta")
        self.assertIsNotNone(v)
        self.assertEqual(v.text, "21.0.4-beta")
        self.assertEqual(v.parts, (21, 0, 4))       # 宽松：与 _version_parts 同
        self.assertEqual(v.strict_key, (0,))        # 严格：与 _semver_key 同
        self.assertTrue(v.prerelease)
        # 目录名口径：同样的串作为目录名读（先剥 `jdk-`，非数字段补 0）
        d = main.Version.from_install_dir("jdk-21.0.4-beta")
        self.assertEqual(d.dir_key, (21, 0, 0))     # 与 _version_key 同
        self.assertEqual(main._version_key("jdk-21.0.4-beta"), d.dir_key,
                         "薄壳与值对象口径不一致 —— 收敛没做到位")

    def test_version_three_functions_are_thin_wrappers_over_it(self):
        """三个老函数必须等价于 Version 的对应方法 —— 收敛的唯一保证。"""
        for text, vp, sk, vk in CHARACTERIZATION:
            v = main.Version.parse(text)
            with self.subTest(输入=text):
                self.assertEqual(main._version_parts(text),
                                 v.parts if v else None,
                                 "_version_parts 与 Version.parts 不一致")
            with self.subTest(输入=text, 口径="strict"):
                self.assertEqual(main._semver_key(text),
                                 main.Version.parse(text).strict_key
                                 if main.Version.parse(text) else (0,))
            with self.subTest(输入=text, 口径="dir"):
                self.assertEqual(main._version_key(text),
                                 main.Version.from_install_dir(text).dir_key)

    def test_version_is_hashable_and_comparable(self):
        """值对象：可哈希（能进 set/dict 键）、可比较。"""
        a = main.Version.parse("21.0.4")
        b = main.Version.parse("21.0.4")
        self.assertEqual(a, b)
        self.assertEqual(len({a, b}), 1, "相等的 Version 必须去重得掉")
        self.assertIsNotNone(hash(a))
        self.assertTrue(a.is_newer_than(main.Version.parse("17.0.12")))
        self.assertFalse(a.is_newer_than(b))

    def test_version_parse_rejects_garbage(self):
        for text in (None, "", "LTS", "jdk-21"):
            with self.subTest(输入=text):
                self.assertIsNone(main.Version.parse(text),
                                  f"{text!r} 不该被认成版本号")

    def test_version_parse_coerces_non_string_input(self):
        """数字会被 str() 强转后照常解析 —— 这是既有行为，不是新引入的。

        保持现状而不是改成只认 str：版本号会从 release API（JSON 里可能是
        数字）、命令 stdout、目录名三处来，强转比抛异常更贴近实际。
        钉住它是为了让「哪天有人加了类型校验」变成一次有意识的变更。
        """
        self.assertEqual(main.Version.parse(21).parts, (21,))
        self.assertEqual(main._version_parts(21), (21,))


class KnownDivergences(unittest.TestCase):
    """刻意保留的三处分歧 —— 它们是**行为现状**，不是待办。

    如果将来要统一它们，这三条会先红，提醒你"这是一次行为变更，
    得想清楚影响面"，而不是无声地改掉。
    """

    def test_strict_key_demotes_prerelease(self):
        self.assertEqual(main.Version.parse("21.0.4-beta").strict_key, (0,),
                         "预发布版沉底是承重设计，不要顺手统一成宽松档")

    def test_loose_parse_ignores_non_numeric_prefix(self):
        """`jdk-21.0.5` 读不出版本号，但作为目录名读得出。"""
        self.assertIsNone(main.Version.parse("jdk-21.0.5"))
        self.assertEqual(main.Version.from_install_dir("jdk-21.0.5").dir_key, (21, 0, 5))

    def test_underscore_chunk_differs_between_policies(self):
        """`1.0.0_1`：严格档认（int('0_1')==1），宽松档只取到 0。

        纯 Python 巧合，但既然已经这样了就先钉住 —— 统一口径时它会变。
        """
        self.assertEqual(main.Version.parse("1.0.0_1").parts, (1, 0, 0))
        self.assertEqual(main.Version.parse("1.0.0_1").strict_key, (1, 0, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
