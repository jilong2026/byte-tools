"""版本号值对象与三种比较口径（从 main.py 抽出，行为逐字不变）。

为什么三套口径并存：它们服务于不同场景，抹平会改变用户可见行为。
- parse / legacy_parts：宽松抽取（`21.0.4-beta` → (21, 0, 4)），用于展示与判断"是不是版本号"
- strict_key：纯 int 严格档，预发布版整档退化为 (0,)，让它们在排序里沉底
- dir_key：安装目录名口径，先剥 `<key>-` 前缀、非数字段补 0

main.py 中的 `_version_parts` / `_semver_key` / `_version_key` 保留为薄壳，
调用点无需改动；测试仍可通过 main 访问同一批对象。
"""
from typing import List, Optional, Tuple


class Version:
    """版本号值对象：把"一段版本文字怎么变成可比较的数字"收在一处。

    可哈希（实现了 __hash__/__eq__），能进 set 与 dict 键。
    """

    __slots__ = ("text", "parts", "prerelease", "_strict", "_dir")

    def __init__(self, text: str, parts: Tuple[int, ...], prerelease: bool) -> None:
        self.text = text
        self.parts = parts
        self.prerelease = prerelease
        self._strict: Optional[Tuple[int, ...]] = None
        self._dir: Optional[Tuple[int, ...]] = None

    # -- 构造 --------------------------------------------------------
    @classmethod
    def parse(cls, text: object) -> Optional["Version"]:
        """宽松抽取 + 严格识别：剥 v 前缀、逐段取开头数字，任一段无数字则 None。"""
        s = str(text or "").strip().lstrip("vV")
        if not s:
            return None
        parts: List[int] = []
        prerelease = False
        for chunk in s.split("."):
            digits = ""
            rest = ""
            for i, ch in enumerate(chunk):
                if ch.isdigit():
                    digits += ch
                else:
                    rest = chunk[i:]
                    break
            if not digits:
                return None
            parts.append(int(digits))
            if rest:
                prerelease = True
        return cls(str(text or ""), tuple(parts), prerelease)

    @classmethod
    def from_install_dir(cls, dir_name: object) -> "Version":
        """按安装目录名解析（`jdk-21.0.5` → 21.0.5），非数字段补 0。"""
        s = str(dir_name or "")
        tail = s.split("-", 1)[1] if "-" in s else s
        out: List[int] = []
        for chunk in tail.split("."):
            out.append(int(chunk) if chunk.isdigit() else 0)
        return cls(s, tuple(out), False)

    # -- 三种口径 ----------------------------------------------------
    @property
    def strict_key(self) -> Tuple[int, ...]:
        """严格档：逐段 int()，任一段不纯就整档作废 → (0,)。

        **别当成 bug 改掉**：它让预发布版在降序排序里沉底，
        "预发布版不该被当成更新"就靠它实现。
        """
        if self._strict is None:
            try:
                self._strict = tuple(int(x) for x in self.text.split("."))
            except (ValueError, AttributeError, TypeError):
                self._strict = (0,)
        return self._strict

    @property
    def dir_key(self) -> Tuple[int, ...]:
        """目录名档：`from_install_dir` 算出的数字段（非数字补 0）。"""
        if self._dir is None:
            self._dir = tuple(int(c) if c.isdigit() else 0
                              for c in self._text_tail().split("."))
        return self._dir

    def _text_tail(self) -> str:
        s = self.text
        return s.split("-", 1)[1] if "-" in s else s

    # -- 比较 --------------------------------------------------------
    def is_newer_than(self, other: object) -> bool:
        """self 是否比 other 新；任一边读不出数字段一律 False。"""
        b = Version.parse(other.text if isinstance(other, Version) else other)
        a = Version.parse(self.text)
        if a is None or b is None:
            return False
        return _pad_compare(a.parts, b.parts) > 0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self.parts == other.parts and self.text == other.text

    def __hash__(self) -> int:
        return hash((self.text, self.parts))

    def __repr__(self) -> str:
        return f"Version({self.text!r}, parts={self.parts}, pre={self.prerelease})"

    # -- 老函数的薄壳 ------------------------------------------------
    @staticmethod
    def legacy_parts(text: object) -> Optional[Tuple[int, ...]]:
        v = Version.parse(text)
        return v.parts if v is not None else None

    @staticmethod
    def legacy_semver_key(text: object) -> Tuple[int, ...]:
        v = Version.parse(text)
        return v.strict_key if v is not None else (0,)

    @staticmethod
    def legacy_version_key(dir_name: object) -> Tuple[int, ...]:
        return Version.from_install_dir(dir_name).dir_key


def _pad_compare(a: Tuple[int, ...], b: Tuple[int, ...]) -> int:
    """按数值分段比较，短的一边补 0（与历史实现一致）。"""
    n = max(len(a), len(b))
    pa = a + (0,) * (n - len(a))
    pb = b + (0,) * (n - len(b))
    return (pa > pb) - (pa < pb)


def version_is_newer(current: str, latest: str) -> bool:
    """latest 是否比 current 新；任一边解析失败返回 False（不打扰用户）。"""
    a = Version.legacy_parts(current)
    b = Version.legacy_parts(latest)
    if a is None or b is None:
        return False
    return _pad_compare(b, a) > 0
