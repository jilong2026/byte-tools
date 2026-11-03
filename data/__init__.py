"""纯数据模型包（规则 R30）。目前收纳 ComponentVersion / DownloadArtifact。"""
from .components import ARTIFACT_LABELS, ComponentVersion, DownloadArtifact, configure

__all__ = ["ARTIFACT_LABELS", "ComponentVersion", "DownloadArtifact", "configure"]
