#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 把 GitHub Release 的产物同步到 Gitee Release。
#
# 设计目标：推一个 tag，GitHub 与 Gitee 两边的产物都齐全。
# 三个关键特性：
#   1. 抗网络抖动 —— GitHub runner 在境外，连 gitee.com:443 会偶发
#      curl(35) SSL_ERROR_SYSCALL（TLS 握手被重置）。这里对每次请求做
#      指数退避重试，单次抖动不再判死整个 job。
#   2. 幂等可重跑 —— release 已存在就复用 ID，附件已存在就跳过上传。
#      因此 job 失败后直接 Re-run，不会产生重复 release 或重复附件。
#   3. 收尾强校验 —— 上传完回查一次附件清单，白名单产物缺一个就报错退出，
#      避免「少传了某个平台」被静默放过。
#
# 依赖：curl（必需）、python3（可选，用于 JSON 解析；缺失时回退到 grep）
#
# 环境变量：
#   GITEE_TOKEN        (必需) Gitee 私人令牌
#   GITEE_OWNER        (必需) Gitee 仓库 owner
#   GITEE_REPO         (必需) Gitee 仓库名
#   TAG_NAME           (必需) 要同步的 tag，如 v1.0.1
#   ASSETS_DIR         产物目录，默认 ./assets
#   TARGET_COMMITISH   tag 在 Gitee 不存在时的指向，默认 master
#   MAX_ATTEMPTS       单次请求最大尝试次数，默认 4
#   RELEASE_BODY       Release 说明，默认「跨平台构建产物（与 GitHub Release 同步生成）」
#   ALLOWED_FILES      产物白名单（| 分隔），默认与 release.yml 的 matrix 一致
#
# 用法：
#   GITEE_TOKEN=xxx GITEE_OWNER=me GITEE_REPO=repo TAG_NAME=v1.0.1 ./scripts/sync_gitee.sh

set -euo pipefail

GITEE_OWNER="${GITEE_OWNER:?缺少环境变量 GITEE_OWNER}"
GITEE_REPO="${GITEE_REPO:?缺少环境变量 GITEE_REPO}"
TAG_NAME="${TAG_NAME:?缺少环境变量 TAG_NAME}"
GITEE_TOKEN="${GITEE_TOKEN:?缺少环境变量 GITEE_TOKEN（Gitee 私人令牌）}"

ASSETS_DIR="${ASSETS_DIR:-./assets}"
TARGET_COMMITISH="${TARGET_COMMITISH:-master}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-4}"
RELEASE_BODY="${RELEASE_BODY:-跨平台构建产物（与 GitHub Release 同步生成）}"
ALLOWED_FILES="${ALLOWED_FILES:-byte-tools.exe|byte-tools-windows-x64.zip|byte-tools-macos-arm64.zip|byte-tools-linux-x64}"

API_BASE="https://gitee.com/api/v5/repos/${GITEE_OWNER}/${GITEE_REPO}"
RELEASE_PAGE="https://gitee.com/${GITEE_OWNER}/${GITEE_REPO}/releases/${TAG_NAME}"
# Gitee 附件单次上传上限 100MB
MAX_UPLOAD_BYTES=104857600

# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

# 优先用 python3 解析 JSON；没有 python3 时回退到 grep（够用即可）
PY_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PY_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PY_BIN="python"
fi

# 取 JSON 顶层字符串/数字字段：json_get <json> <key>
json_get() {
  if [ -n "${PY_BIN}" ]; then
    printf '%s' "$1" | "${PY_BIN}" -c '
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
v = d.get(sys.argv[1], "") if isinstance(d, dict) else ""
print(v if isinstance(v, (str, int, float)) else "")
' "$2" 2>/dev/null || true
  else
    printf '%s' "$1" | tr ',{}' '\n\n\n' | grep -m1 "\"$2\"" | sed 's/.*: *//; s/"//g' || true
  fi
}

# 列出 release 已有附件名，一行一个：asset_names <json>
asset_names() {
  if [ -n "${PY_BIN}" ]; then
    printf '%s' "$1" | "${PY_BIN}" -c '
import sys, json
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for a in (d.get("assets") or []) if isinstance(d, dict) else []:
    print(a.get("name", ""))
' 2>/dev/null || true
  else
    printf '%s' "$1" | grep -o '"name":"[^"]*"' | sed 's/"name":"//; s/"$//' || true
  fi
}

# 旧版 curl（<7.71）不支持 --retry-all-errors，按需追加，避免直接报未知参数
CURL_RETRY_OPTS="--retry 2 --retry-delay 5"
if curl --help all 2>/dev/null | grep -q "retry-all-errors"; then
  CURL_RETRY_OPTS="${CURL_RETRY_OPTS} --retry-all-errors --retry-connrefused"
fi

# 带指数退避的 Gitee 请求：gitee_request <curl 参数...>
# 成功时把响应体打到 stdout；重试耗尽返回非 0
gitee_request() {
  local attempt=1 delay=10 resp
  while [ "${attempt}" -le "${MAX_ATTEMPTS}" ]; do
    if resp=$(curl -sS ${CURL_RETRY_OPTS} --connect-timeout 20 --max-time 1800 "$@" 2>&1); then
      printf '%s' "${resp}"
      return 0
    fi
    echo "  !! 第 ${attempt}/${MAX_ATTEMPTS} 次请求 Gitee 失败（curl 退出码 $?），${delay}s 后重试" >&2
    echo "     错误信息: ${resp}" >&2
    attempt=$((attempt + 1))
    sleep "${delay}"
    delay=$((delay * 2))
  done
  echo "错误：连续 ${MAX_ATTEMPTS} 次请求 Gitee 均失败（多为境外 runner 到 gitee.com 的链路抖动）" >&2
  return 1
}

# ---------------------------------------------------------------------------
# 0. 预检
# ---------------------------------------------------------------------------
echo "==> 同步 ${TAG_NAME} 产物到 Gitee ${GITEE_OWNER}/${GITEE_REPO}"

if [ ! -d "${ASSETS_DIR}" ]; then
  echo "错误：产物目录不存在: ${ASSETS_DIR}"
  exit 1
fi

# ---------------------------------------------------------------------------
# 1. 获取或创建 Gitee Release（幂等：已有则复用 ID）
# ---------------------------------------------------------------------------
echo "==> [1/3] 获取或创建 Gitee Release"
RELEASE_RESP=$(gitee_request "${API_BASE}/releases/tags/${TAG_NAME}")
RELEASE_ID=$(json_get "${RELEASE_RESP}" "id")

if [ -z "${RELEASE_ID}" ]; then
  echo "   tag ${TAG_NAME} 尚无 Release，创建中..."
  CREATE_RESP=$(gitee_request -X POST "${API_BASE}/releases" \
    -F "access_token=${GITEE_TOKEN}" \
    -F "tag_name=${TAG_NAME}" \
    -F "name=${TAG_NAME}" \
    -F "body=${RELEASE_BODY}" \
    -F "target_commitish=${TARGET_COMMITISH}")
  RELEASE_ID=$(json_get "${CREATE_RESP}" "id")
  if [ -z "${RELEASE_ID}" ]; then
    echo "错误：创建 Gitee Release 失败，原始响应："
    echo "${CREATE_RESP}"
    exit 1
  fi
  echo "   创建成功，Release ID: ${RELEASE_ID}"
else
  echo "   Release 已存在，复用 ID: ${RELEASE_ID}（幂等，重跑不会重复创建）"
fi

# ---------------------------------------------------------------------------
# 2. 上传白名单产物（已存在的同名附件跳过）
# ---------------------------------------------------------------------------
echo "==> [2/3] 上传产物"
EXISTING=$(asset_names "$(gitee_request "${API_BASE}/releases/${RELEASE_ID}")")

UPLOADED=0
SKIPPED=0
IGNORED=0

for FILE in "${ASSETS_DIR}"/*; do
  [ -e "${FILE}" ] || continue
  BASE_NAME=$(basename "${FILE}")

  case "${BASE_NAME}" in
    byte-tools.exe|byte-tools-windows-x64.zip|byte-tools-macos-arm64.zip|byte-tools-linux-x64) ;;
    *)
      echo "  -- 跳过非产物文件: ${BASE_NAME}"
      IGNORED=$((IGNORED + 1))
      continue
      ;;
  esac

  # 白名单 ALLOWED_FILES 被自定义时以此为准
  if [ "${ALLOWED_FILES}" != "byte-tools.exe|byte-tools-windows-x64.zip|byte-tools-macos-arm64.zip|byte-tools-linux-x64" ]; then
    if ! echo "${BASE_NAME}" | grep -qE "^(${ALLOWED_FILES})$"; then
      echo "  -- 跳过非产物文件: ${BASE_NAME}"
      IGNORED=$((IGNORED + 1))
      continue
    fi
  fi

  if echo "${EXISTING}" | grep -qx "${BASE_NAME}"; then
    echo "  == 已存在，跳过: ${BASE_NAME}"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  SIZE=$(wc -c < "${FILE}" | tr -d ' ')
  if [ "${SIZE}" -gt "${MAX_UPLOAD_BYTES}" ]; then
    echo "错误：${BASE_NAME} 大小 ${SIZE} 字节，超过 Gitee 附件 100MB 上限"
    exit 1
  fi

  echo "  -> 上传 ${BASE_NAME}（${SIZE} 字节）"
  UPLOAD_RESP=$(gitee_request -X POST "${API_BASE}/releases/${RELEASE_ID}/attach_files" \
    -F "access_token=${GITEE_TOKEN}" \
    -F "file=@${FILE}")

  ATTACH_URL=$(json_get "${UPLOAD_RESP}" "browser_download_url")
  [ -n "${ATTACH_URL}" ] || ATTACH_URL=$(json_get "${UPLOAD_RESP}" "attach_file_url")
  if [ -z "${ATTACH_URL}" ]; then
    echo "错误：${BASE_NAME} 上传失败，原始响应："
    echo "${UPLOAD_RESP}"
    exit 1
  fi
  echo "     成功: ${ATTACH_URL}"
  UPLOADED=$((UPLOADED + 1))
done

# ---------------------------------------------------------------------------
# 3. 收尾校验：白名单产物必须全部出现在 Gitee Release 附件里
# ---------------------------------------------------------------------------
echo "==> [3/3] 校验 Gitee Release 附件"
FINAL_RESP=$(gitee_request "${API_BASE}/releases/${RELEASE_ID}")
FINAL_ASSETS=$(asset_names "${FINAL_RESP}")

MISSING=""
for WANT in byte-tools.exe byte-tools-windows-x64.zip byte-tools-macos-arm64.zip byte-tools-linux-x64; do
  if ! echo "${FINAL_ASSETS}" | grep -qx "${WANT}"; then
    MISSING="${MISSING} ${WANT}"
  fi
done

if [ -n "${FINAL_ASSETS}" ] && [ -n "${MISSING}" ]; then
  echo "错误：以下产物在 Gitee Release 上缺失:${MISSING}"
  echo "当前附件清单："
  echo "${FINAL_ASSETS}"
  exit 1
fi

if [ -z "${FINAL_ASSETS}" ]; then
  echo "警告：Gitee 未返回附件清单，跳过缺失校验（请手动打开 ${RELEASE_PAGE} 确认）"
fi

echo "同步完成：上传 ${UPLOADED} 个，跳过已存在 ${SKIPPED} 个，忽略非产物 ${IGNORED} 个"
echo "Gitee Release: ${RELEASE_PAGE}"
