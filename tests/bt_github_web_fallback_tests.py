# -*- coding: utf-8 -*-
"""GitHub「不烧 API 额度」通道的规格测试（离线）。

背景：匿名 api.github.com 是 60 次/小时/IP，而工具一次启动要给 30 个 GitHub 托管
组件各抓一次。额度耗尽后原来的行为是整批降级成内置清单。2026-10-21 新增网页兜底：
releases.atom（tag）+ releases/expanded_assets（产物名/体积），都不占 API 额度。

本文件只用桩数据，不联网。
"""
import sys
import unittest

import _btprelude  # noqa: F401  必须早于 import main：打 WMI 桩 + offscreen + sys.path

REPO_ROOT = str(_btprelude.REPO_ROOT)

import main  # noqa: E402


class _Text:
    def __init__(self, text: str):
        self.text = text


ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Release notes from jq</title>
  <entry><title>jq 1.8.2</title>
    <link rel="alternate" type="text/html" href="https://github.com/jqlang/jq/releases/tag/jq-1.8.2"/>
  </entry>
  <entry><title>jq 1.8.2rc1</title>
    <link rel="alternate" type="text/html" href="https://github.com/jqlang/jq/releases/tag/jq-1.8.2rc1"/>
  </entry>
  <entry><title>jq 1.8.1</title>
    <link rel="alternate" type="text/html" href="https://github.com/jqlang/jq/releases/tag/jq-1.8.1"/>
  </entry>
  <entry><title>duplicate</title>
    <link rel="alternate" type="text/html" href="https://github.com/jqlang/jq/releases/tag/jq-1.8.2"/>
  </entry>
</feed>
"""

ASSETS = """<div>
  <a href="/jqlang/jq/releases/download/jq-1.8.2/jq-windows-amd64.exe" rel="nofollow">
    <span>jq-windows-amd64.exe</span></a>
  <span class="text-right">1.87 MB</span>
  <a href="/jqlang/jq/releases/download/jq-1.8.2/jq-linux-amd64" rel="nofollow">
    <span>jq-linux-amd64</span></a>
  <span class="text-right">2.07 MB</span>
</div>
"""


class HumanSizeTests(unittest.TestCase):
    def test_units_convert_to_bytes(self):
        self.assertEqual(main._gh_human_size("14 KB"), 14 * 1024)
        self.assertEqual(main._gh_human_size("1.87 MB"), int(1.87 * 1024 ** 2))
        self.assertEqual(main._gh_human_size("2 GB"), 2 * 1024 ** 3)
        self.assertEqual(main._gh_human_size("512 Bytes"), 512)

    def test_garbage_is_zero_not_an_exception(self):
        self.assertEqual(main._gh_human_size(""), 0)
        self.assertEqual(main._gh_human_size("n/a"), 0)


class AssetPageTests(unittest.TestCase):
    def test_names_and_sizes_stay_aligned(self):
        """按行切块：任何一个产物缺体积都不许让后面整体错位。"""
        assets = main._gh_parse_asset_page(ASSETS, "jqlang/jq", "jq-1.8.2")
        self.assertEqual([a["name"] for a in assets],
                         ["jq-windows-amd64.exe", "jq-linux-amd64"])
        self.assertEqual([a["size"] for a in assets],
                         [14 * 0 + main._gh_human_size("1.87 MB"),
                          main._gh_human_size("2.07 MB")])

    def test_download_url_is_rebuilt_from_the_tag(self):
        assets = main._gh_parse_asset_page(ASSETS, "jqlang/jq", "jq-1.8.2")
        self.assertEqual(assets[0]["browser_download_url"],
                         "https://github.com/jqlang/jq/releases/download/"
                         "jq-1.8.2/jq-windows-amd64.exe")

    def test_tag_with_slash_and_at_is_url_encoded(self):
        html = ('<a href="/biomejs/biome/releases/download/x/biome-win32-x64.exe">'
                '<span>b</span></a><span class="text-right">1 MB</span>')
        a = main._gh_parse_asset_page(html, "biomejs/biome", "@biomejs/biome@2.5.15")
        self.assertIn("/download/%40biomejs%2Fbiome%402.5.15/", a[0]["browser_download_url"])


class NoApiReleaseTests(unittest.TestCase):
    def _patch_get(self, calls: dict):
        def fake_get(url, timeout=None, **kw):
            calls.setdefault("urls", []).append(url)
            if url.endswith("releases.atom"):
                return _Text(ATOM)
            return _Text(ASSETS)
        orig = main._get
        main._get = fake_get
        self.addCleanup(setattr, main, "_get", orig)

    def test_atom_tags_are_used_and_prereleases_are_dropped(self):
        calls: dict = {}
        self._patch_get(calls)
        rels = main.github_releases_no_api("jqlang/jq", max_tags=5)
        tags = [r["tag_name"] for r in rels]
        self.assertEqual(tags, ["jq-1.8.2", "jq-1.8.1"],
                         "rc 版不许进列表；重复 tag 只留一份")
        self.assertTrue(all(r["prerelease"] is False for r in rels))
        self.assertTrue(any(u.endswith("releases.atom") for u in calls["urls"]))
        self.assertTrue(any("expanded_assets/jq-1.8.2" in u for u in calls["urls"]))

    def test_asset_page_failure_skips_that_tag_not_the_whole_list(self):
        def fake_get(url, timeout=None, **kw):
            if url.endswith("releases.atom"):
                return _Text(ATOM)
            if url.endswith("expanded_assets/jq-1.8.2"):
                raise RuntimeError("boom")
            return _Text(ASSETS)

        orig = main._get
        main._get = fake_get
        self.addCleanup(setattr, main, "_get", orig)
        rels = main.github_releases_no_api("jqlang/jq", max_tags=5)
        self.assertEqual([r["tag_name"] for r in rels], ["jq-1.8.1"])


class FetcherFallbackTests(unittest.TestCase):
    def test_api_failure_switches_to_web_and_still_returns_versions(self):
        fetcher = main.make_github_asset_fetcher(
            "jq", "jqlang/jq", (("exe", "jq-windows-amd64.exe"),),
            tag_re=r"jq-(\d+\.\d+\.\d+)$")

        def boom(*_a, **_k):
            raise RuntimeError("API rate limit exceeded")

        def fake_web(repo, max_tags=12):
            return [{"tag_name": "jq-1.8.2", "prerelease": False, "draft": False,
                     "assets": [{"name": "jq-windows-amd64.exe", "size": 123,
                                 "browser_download_url":
                                     "https://github.com/jqlang/jq/releases/download/"
                                     "jq-1.8.2/jq-windows-amd64.exe"}]}]

        orig_api, orig_web = main._github_api_json, main.github_releases_no_api
        main._github_api_json = boom
        main.github_releases_no_api = fake_web
        try:
            cvs = fetcher()
        finally:
            main._github_api_json, main.github_releases_no_api = orig_api, orig_web
        self.assertEqual([cv.version for cv in cvs], ["1.8.2"])
        self.assertEqual(cvs[0].artifacts[0].size, 123)

    def test_both_channels_failing_names_both_reasons(self):
        fetcher = main.make_github_asset_fetcher(
            "jq", "jqlang/jq", (("exe", "jq-windows-amd64.exe"),),
            tag_re=r"jq-(\d+\.\d+\.\d+)$")

        def boom(*_a, **_k):
            raise RuntimeError("api down")

        orig_api, orig_web = main._github_api_json, main.github_releases_no_api
        main._github_api_json = boom
        main.github_releases_no_api = boom
        try:
            with self.assertRaises(RuntimeError) as ctx:
                fetcher()
        finally:
            main._github_api_json, main.github_releases_no_api = orig_api, orig_web
        msg = str(ctx.exception)
        self.assertIn("api down", msg)
        self.assertIn("网页兜底", msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
