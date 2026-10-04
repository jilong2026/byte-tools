#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# 把 GitHub Release 的产物信息同步到 Gitee Release。
#
# 谁会跑它：发布维护者（以及 release.yml 的 sync-to-gitee 任务）。普通用户不需要
# 这个脚本，也不需要任何产物目录——他们从 Releases 页下载 byte-tools.exe，或双击
# 仓库根目录那两个一键脚本。本机暂存产物用的 release-assets/ 被 .gitignore 排除是
# 故意的：约 220 MB 二进制不该进版本库，同步完就可以删。
#
# 【2026-09-29 策略变更】Gitee 侧不再挂大二进制产物，只在 Release 正文里写清各平台
#   产物的 GitHub 直链。原因：GitHub 托管 runner 在境外，往 gitee.com 推 84MB 附件
#   会长时间挂死且服务端根本不落地（v1.0.3 实测：一次 POST 挂了 70 分钟，
#   Gitee 附件清单里一个产物都没有，而脚本因 -sS + curl 内部 --retry + --max-time 1800
#   ×4 轮重试，最坏能静默耗掉 6 小时不吐一行日志）。
#   确实需要 Gitee 站内直下时：把 UPLOAD_ARTIFACTS 设成要传的文件名（建议只挑小包），
#   或把 release.yml 里 sync-to-gitee 的 runs-on 换成能直连 gitee.com 的国内 self-hosted runner。
#
# 三个关键特性：
#   1. 快速失败 + 全程可见 —— 每次请求打印 HTTP 码、耗时、已传字节与均速；
#      网络类错误按 MAX_ATTEMPTS 指数退避重试，4xx 立即判死（重试没有意义）。
#      重试只在脚本这一层，curl 不再叠 --retry，避免「内外相乘」把预算吃光。
#   2. 幂等可重跑 —— Release 已存在就复用 ID；已上传的同名附件跳过。
#   3. 收尾强校验 —— 正文里的 GitHub 直链必须回读到位；UPLOAD_ARTIFACTS 指定的附件
#      必须全部出现。缺一项就报错退出，绝不静默「同步成功」。
#
# 依赖：curl、awk（human_size 用）；python3 可选（JSON 解析，缺失时回退 grep）
#
# Windows 上请优先用同目录的 同步Gitee产物.bat，不要用 Git Bash 跑本脚本：本机实测
# （2026-10-05）Git Bash 默认的 /mingw64/bin/curl 会把 -F 参数里的中文按 GBK 发出，
# Gitee 收到的正文就是乱码；C:\Windows\System32\curl.exe 则原样保留 UTF-8。两者的
# 行为差异只在 Windows 存在，Linux runner 上等价于 System32 那一档。
#
# 环境变量：
#   GITEE_TOKEN          (必需) Gitee 私人令牌。只作为表单字段传递，绝不拼进 URL，
#                        也绝不使用 curl -v（那会把请求内容打进日志）
#   GITEE_OWNER          (必需) Gitee 仓库 owner
#   GITEE_REPO           (必需) Gitee 仓库名
#   TAG_NAME             (必需) 要同步的 tag，如 v1.0.1
#   GITHUB_REPO_SLUG     (必需) GitHub 的 owner/repo，用于生成产物直链
#   ASSETS_DIR           产物目录，默认 ./assets
#   GH_ACCEL_PREFIX      自动下载产物时用的加速器前缀，默认 https://gh-proxy.com/；
#                        直连 github.com 排在它后面（规则 R1：镜像优先、官网末位）
#   AUTO_FETCH_ASSETS    缺产物时脚本自己去下载，默认 1；设 0 关掉（测试接缝，
#                        保证回归用例不碰网络）
#   TARGET_COMMITISH     tag 在 Gitee 不存在时的指向，默认 master
#   MAX_ATTEMPTS         单次请求最大尝试次数，默认 3（退避 5s / 10s）
#   API_MAX_TIME         JSON 接口单请求上限（秒），默认 60
#   UPLOAD_MAX_TIME      附件上传单请求上限（秒），默认 300
#   RELEASE_ARTIFACTS    产物清单（| 分隔），默认与 release.yml 的 matrix 一致；
#                        正文表格、上传资格、收尾校验都以它为准 —— 改产物名只改这一处
#   UPLOAD_ARTIFACTS     其中真正要上传到 Gitee 的子集（| 分隔），默认为空 = 一个都不传
#   RELEASE_BODY         覆盖正文（默认自动生成带 GitHub 直链的说明）
#   GITEE_API_BASE       测试接缝：覆盖 API 基址（离线 mock 服务器用），平时不要设
#
# 用法（位于项目根目录；文件名含中文，命令行建议用引号或 tab 补全）：
#   GITEE_TOKEN=xxx GITEE_OWNER=me GITEE_REPO=repo GITHUB_REPO_SLUG=me/repo \
#   TAG_NAME=v1.0.1 "./同步Gitee产物.sh"

set -euo pipefail

GITEE_OWNER="${GITEE_OWNER:?缺少环境变量 GITEE_OWNER}"
GITEE_REPO="${GITEE_REPO:?缺少环境变量 GITEE_REPO}"
TAG_NAME="${TAG_NAME:?缺少环境变量 TAG_NAME}"
GITEE_TOKEN="${GITEE_TOKEN:?缺少环境变量 GITEE_TOKEN（Gitee 私人令牌）}"
GITHUB_REPO_SLUG="${GITHUB_REPO_SLUG:-${GITHUB_REPOSITORY:-}}"
if [ -z "${GITHUB_REPO_SLUG}" ]; then
  echo "错误：缺少 GITHUB_REPO_SLUG（形如 jilong2026/byte-tools），正文里的直链无法生成"
  exit 1
fi

ASSETS_DIR="${ASSETS_DIR:-./assets}"
TARGET_COMMITISH="${TARGET_COMMITISH:-master}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-3}"
API_MAX_TIME="${API_MAX_TIME:-60}"
UPLOAD_MAX_TIME="${UPLOAD_MAX_TIME:-300}"
DEFAULT_ARTIFACTS="byte-tools.exe|byte-tools-windows-x64.zip|byte-tools-macos-arm64.zip|byte-tools-linux-x64"
RELEASE_ARTIFACTS="${RELEASE_ARTIFACTS:-${DEFAULT_ARTIFACTS}}"
UPLOAD_ARTIFACTS="${UPLOAD_ARTIFACTS:-}"

API_BASE="${GITEE_API_BASE:-https://gitee.com/api/v5/repos/${GITEE_OWNER}/${GITEE_REPO}}"
RELEASE_PAGE="https://gitee.com/${GITEE_OWNER}/${GITEE_REPO}/releases/${TAG_NAME}"
GH_SERVER="${GITHUB_SERVER_URL:-https://github.com}"
GH_RELEASE_PAGE="${GH_SERVER}/${GITHUB_REPO_SLUG}/releases/tag/${TAG_NAME}"
GH_DOWNLOAD_BASE="${GH_SERVER}/${GITHUB_REPO_SLUG}/releases/download/${TAG_NAME}"
# 自动下载产物时先走加速器、最后才直连 github.com（规则 R1：镜像优先、官网末位）。
# 境外直连 github.com 从国内经常超时，本机 同步Gitee产物.bat 用的是同一个 gh-proxy.com。
GH_ACCEL_PREFIX="${GH_ACCEL_PREFIX:-https://gh-proxy.com/}"
# Gitee 附件单次上限：100MB（注意：这是沿用值，未重新实测；上传走这条路的别指望它兜底）
MAX_UPLOAD_BYTES=104857600

# 产物清单与「要上传的子集」解析成数组
IFS='|' read -r -a ARTIFACT_LIST <<< "${RELEASE_ARTIFACTS}"
UPLOAD_LIST=()
if [ -n "${UPLOAD_ARTIFACTS}" ]; then
  IFS='|' read -r -a UPLOAD_LIST <<< "${UPLOAD_ARTIFACTS}"
fi

is_upload_target() {
  local want="$1" item
  [ "${#UPLOAD_LIST[@]}" -gt 0 ] || return 1
  for item in "${UPLOAD_LIST[@]}"; do
    [ "${item}" = "${want}" ] && return 0
  done
  return 1
}

# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

# Windows 控制台默认跟着系统码页（简体中文 = cp936）。正文里只要有一个它编不出
# 来的字符（emoji、CJK 扩展汉字，或解码失败留下的 U+FFFD），json_get 里那句
# print 就抛 UnicodeEncodeError，而它是带 `2>/dev/null || true` 跑的 —— 错误被
# 咽掉、stdout 变空串，脚本于是得出「Gitee 正文里没有 GitHub 直链」这个假结论，
# 收尾校验永远过不去（本机 4 个回归用例就是这么红的）。Linux 上本来就是 UTF-8。
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

# 选一个「真能解析 JSON」的解释器：Windows 上 python3 常是 Microsoft Store 的占位别名，
# 命令存在但一跑就退出码 49 且不输出，会让 json_get 静默返回空 —— 于是「已存在的 Release」
# 被当成不存在，本机手动补同步时直接踩这个坑。所以逐个做握手测试，全不行就回退 grep。
PY_BIN=""
for _cand in python3 python; do
  if command -v "${_cand}" >/dev/null 2>&1 \
     && printf '{}' | "${_cand}" -c 'import sys, json; json.load(sys.stdin)' >/dev/null 2>&1; then
    PY_BIN="${_cand}"
    break
  fi
done
if [ -z "${PY_BIN}" ]; then
  echo "   提示：没找到可用的 python3/python，JSON 解析回退到 grep（够用但脆弱）" >&2
fi

# 取 JSON 顶层字段：json_get <json> <key>
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

# 字节数转可读：human_size <bytes>
human_size() {
  awk -v b="${1:-0}" 'BEGIN{
    split("B KB MB GB", u, " "); i=1
    while (b>=1024 && i<4) { b/=1024; i++ }
    printf "%.1f %s", b, u[i]
  }'
}

RESP_FILE="$(mktemp)"
ERR_FILE="$(mktemp)"
cleanup() { rm -f "${RESP_FILE}" "${ERR_FILE}"; }
trap cleanup EXIT

# 带指数退避与可见输出的 Gitee 请求：gitee_request <单请求上限秒> [--allow-404] <curl 参数...>
# 成功时把响应体打到 stdout；失败返回非 0（调用方用 $? 判定）
# --allow-404：把 404 也当正常答复交回调用方判断。注意 2026-09-29 实测：Gitee v5 对
#   「仓库存在但该 tag 没有 Release」返回 **200 + null**（不是 404），仓库整体不存在才 404。
#   所以正常路径靠的是 null 里没有 id 字段；这个标志是防 Gitee 改行为时把创建流程打死。
# 刻意不用 curl -v：令牌走表单字段，-v 会把它打进日志。
gitee_request() {
  local max_time="$1"
  shift
  local allow_404=0
  if [ "${1:-}" = "--allow-404" ]; then
    allow_404=1
    shift
  fi
  local attempt=1 delay=5 rc=0 summary="" http="" secs uploaded speed
  while [ "${attempt}" -le "${MAX_ATTEMPTS}" ]; do
    rc=0
    summary=$(curl -sS --connect-timeout 20 --max-time "${max_time}" \
                  -o "${RESP_FILE}" -w '%{http_code} %{time_total} %{size_upload} %{speed_upload}' \
                  "$@" 2>"${ERR_FILE}") || rc=$?
    # -w 的四段：状态码 / 耗时秒 / 已上传字节 / 均速字节每秒
    http=$(printf '%s' "${summary}" | awk '{print $1}')
    secs=$(printf '%s' "${summary}" | awk '{print $2}')
    uploaded=$(printf '%s' "${summary}" | awk '{print $3}')
    speed=$(printf '%s' "${summary}" | awk '{print $4}')

    if [ "${rc}" -ne 0 ]; then
      # 带上耗时：一眼区分「瞬间失败」和「守满超时」——后者就是之前挂死 6 小时的那种
      # 所有状态行一律走 stderr：stdout 必须只有响应体，调用方要拿它当 JSON 解析
      echo "  !! 第 ${attempt}/${MAX_ATTEMPTS} 次请求失败：curl 退出码 ${rc}，用时 ${secs}s，$(head -c 200 "${ERR_FILE}" | tr '\n' ' ')" >&2
    elif [ "${http}" = "404" ] && [ "${allow_404}" -eq 1 ]; then
      echo "     HTTP 404（按「不存在」处理）用时 ${secs}s" >&2
      cat "${RESP_FILE}"
      return 0
    elif [ "${http}" -ge 400 ] 2>/dev/null && [ "${http}" -lt 500 ] && [ "${http}" != "429" ]; then
      echo "  !! HTTP ${http} 客户端错误（重试无意义，用时 ${secs}s），Gitee 返回：$(head -c 300 "${RESP_FILE}" | tr '\n' ' ')" >&2
      return 1
    elif [ "${http}" -ge 500 ] 2>/dev/null || [ "${http}" = "000" ]; then
      echo "  !! 第 ${attempt}/${MAX_ATTEMPTS} 次 HTTP ${http} 服务端错误，用时 ${secs}s，$(head -c 200 "${RESP_FILE}" | tr '\n' ' ')" >&2
    else
      echo "     HTTP ${http} 用时 ${secs}s 已传 ${uploaded} 字节 均速 ${speed} B/s" >&2
      cat "${RESP_FILE}"
      return 0
    fi
    attempt=$((attempt + 1))
    if [ "${attempt}" -le "${MAX_ATTEMPTS}" ]; then
      echo "     ${delay}s 后重试…" >&2
      sleep "${delay}"
      delay=$((delay * 2))
    fi
  done
  echo "错误：连续 ${MAX_ATTEMPTS} 次请求 Gitee 均失败（多为境外 runner 到 gitee.com 的链路问题）" >&2
  return 1
}

# ---------------------------------------------------------------------------
# 0. 预检
# ---------------------------------------------------------------------------
echo "==> 同步 ${TAG_NAME} 到 Gitee ${GITEE_OWNER}/${GITEE_REPO}"
echo "    产物清单(${#ARTIFACT_LIST[@]} 项)：${RELEASE_ARTIFACTS}"
if [ "${#UPLOAD_LIST[@]}" -gt 0 ]; then
  echo "    上传到 Gitee：${UPLOAD_ARTIFACTS}"
else
  echo "    上传到 Gitee：（空）→ 只写正文直链，Gitee 侧不挂二进制产物"
fi

if [ ! -d "${ASSETS_DIR}" ]; then
  mkdir -p "${ASSETS_DIR}" 2>/dev/null || {
    echo "错误：无法创建产物目录: ${ASSETS_DIR}"
    echo "      本脚本要把 GitHub 产物下载到这里再传到 Gitee，所以它必须可写。"
    echo "      查一下磁盘剩余空间和目录权限，或者换个位置："
    echo "        ASSETS_DIR=/tmp/bt-assets ./\"$0\""
    echo "      谁会跑它：发布维护者。普通用户不需要这个目录——他们从 Releases 页"
    echo "      下载 byte-tools.exe，或双击仓库根目录那两个一键脚本。"
    exit 1
  }
fi

# 缺产物就自己去下载，而不是打几条 curl 让维护者手跑——两个一键脚本已经按这个
# 标准改过，这里是同一条契约。只在真要往 Gitee 传二进制时才下载：CI 默认
# UPLOAD_LIST 为空（正文只写 GitHub 直链），为那种模式拉 220MB 毫无意义。
# AUTO_FETCH_ASSETS=0 是测试接缝，让回归用例保持离线。
if [ "${#UPLOAD_LIST[@]}" -gt 0 ] && [ "${AUTO_FETCH_ASSETS:-1}" != "0" ]; then
  for _name in "${UPLOAD_LIST[@]}"; do
    [ -s "${ASSETS_DIR}/${_name}" ] && continue
    echo "   下载 ${_name} → ${ASSETS_DIR}/"
    _got=0
    for _url in "${GH_ACCEL_PREFIX}${GH_DOWNLOAD_BASE}/${_name}" "${GH_DOWNLOAD_BASE}/${_name}"; do
      if curl -fsSL --connect-timeout 20 --max-time 1800 -o "${ASSETS_DIR}/${_name}.part" "${_url}" \
         && [ "$(wc -c < "${ASSETS_DIR}/${_name}.part" 2>/dev/null || echo 0)" -ge 1048576 ]; then
        mv -f "${ASSETS_DIR}/${_name}.part" "${ASSETS_DIR}/${_name}"
        _got=1
        break
      fi
      rm -f "${ASSETS_DIR}/${_name}.part"
      echo "      这个源没拿到有效文件，换下一个"
    done
    [ "${_got}" -eq 1 ] || echo "   警告：加速器与 github.com 都没能取到 ${_name}" >&2
  done
fi

# 预检：目录里到底有没有产物。之前没有这一关，把仓库自带的图标目录 assets/ 当产物目录
# 传进来时，脚本会先跑完 Gitee 请求才发现「一个产物都没有」，白跑一趟还容易被误读成网络故障
FOUND_ART=0
for _name in "${ARTIFACT_LIST[@]}"; do
  [ -f "${ASSETS_DIR}/${_name}" ] && FOUND_ART=$((FOUND_ART + 1))
done
if [ "${FOUND_ART}" -eq 0 ]; then
  if [ "${#UPLOAD_LIST[@]}" -gt 0 ]; then
    echo "错误：${ASSETS_DIR} 里找不到任何产物文件，但上传清单是非空的："
    echo "      期望的文件名：${RELEASE_ARTIFACTS}"
    echo "      实际看到：$(ls -1 "${ASSETS_DIR}" 2>/dev/null | tr '\n' ' ')"
    echo "      注意仓库根目录的 assets/ 是图标目录，不是产物目录（本机暂存请用 release-assets/）"
    echo "      再提醒一次：这是发布维护者用的脚本，普通用户不需要任何产物目录"
    exit 1
  fi
  echo "   警告：${ASSETS_DIR} 里没有产物文件；本次不上传任何东西，"
  echo "         正文里各文件的大小会显示为「本地未取到」，但 GitHub 直链仍然有效"
fi

# ---------------------------------------------------------------------------
# 1. 生成正文（含各平台产物的 GitHub 直链）
# ---------------------------------------------------------------------------
build_body() {
  {
    printf '跨平台构建产物由 GitHub Actions 在三平台矩阵上构建，下表给出各产物的 GitHub 直链。\n\n'
    printf '| 文件 | 大小 | GitHub 直链 |\n| --- | --- | --- |\n'
    local name size
    for name in "${ARTIFACT_LIST[@]}"; do
      if [ -f "${ASSETS_DIR}/${name}" ]; then
        size=$(human_size "$(wc -c < "${ASSETS_DIR}/${name}" | tr -d ' ')")
      else
        size='本地未取到'
      fi
      printf '| `%s` | %s | %s/%s |\n' "${name}" "${size}" "${GH_DOWNLOAD_BASE}" "${name}"
    done
    printf '\nGitHub Release：%s\n' "${GH_RELEASE_PAGE}"
    printf '\n说明：若本站附件与上表同名，则是同一批构建产物；国内直连本站下载偏慢时，可直接用表中的 GitHub 链接。\n'
  }
}
RELEASE_BODY="${RELEASE_BODY:-$(build_body)}"

# 补不上正文时给人工补救用（PATCH 被拒 / 收尾校验没过都会打这段）
print_remedies() {
  echo "已存在的 Release 只能二选一处理："
  echo "  A) 在 Gitee 网页端把下面这段正文粘进 ${RELEASE_PAGE} 的编辑框；"
  echo "  B) 删掉 Gitee 的这个 Release（含同名 tag），重跑本任务让脚本带直链重建。"
  echo "----- 建议正文 -----"
  printf '%s\n' "${RELEASE_BODY}"
}

# ---------------------------------------------------------------------------
# 2. 获取或创建 Gitee Release（幂等：已有则复用 ID）
# ---------------------------------------------------------------------------
echo "==> [1/3] 获取或创建 Gitee Release"
RELEASE_RESP=$(gitee_request "${API_MAX_TIME}" --allow-404 "${API_BASE}/releases/tags/${TAG_NAME}")
RELEASE_ID=$(json_get "${RELEASE_RESP}" "id")

if [ -z "${RELEASE_ID}" ]; then
  echo "   tag ${TAG_NAME} 尚无 Release，创建中..."
  CREATE_RESP=$(gitee_request "${API_MAX_TIME}" -X POST "${API_BASE}/releases" \
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
  CREATED_NEW=1
else
  echo "   Release 已存在，复用 ID: ${RELEASE_ID}（幂等，重跑不会重复创建）"
  CREATED_NEW=0
  # 正文必须在这里自己补齐。v1.0.5 真实翻车：Release 是旧版脚本建的、正文没有 GitHub 直链，
  # 而这条分支只复用 ID 不写正文，于是收尾校验永远失败——重跑一百次也好不了。
  # 接口是实测出来的（2026-09-30）：PATCH /repos/{owner}/{repo}/releases/{id} 这个路由存在
  # （不带 token 返回 401「登录失效」，而 /releases/{id}/update 那种不存在的路径返回 404）。
  EXIST_BODY=$(json_get "${RELEASE_RESP}" "body")
  if printf '%s' "${EXIST_BODY}" | grep -qF "${GH_DOWNLOAD_BASE}"; then
    echo "   正文已含 GitHub 直链，无需改写"
  else
    echo "   正文里没有 GitHub 直链，补写正文（PATCH /releases/${RELEASE_ID}）..."
    # Gitee 的 PATCH 是「编辑 Release」语义，会校验必填字段：只发 access_token + body
    # 会被打回 400「tag_name is missing / name is missing」（2026-09-30 实测）。
    # 所以这里必须把 tag_name 与 name 一起带上，否则收尾校验永远过不去。
    if gitee_request "${API_MAX_TIME}" -X PATCH "${API_BASE}/releases/${RELEASE_ID}" \
        -F "access_token=${GITEE_TOKEN}" \
        -F "tag_name=${TAG_NAME}" \
        -F "name=${TAG_NAME}" \
        -F "body=${RELEASE_BODY}" >/dev/null; then
      echo "   补写正文完成"
    else
      echo "错误：补写正文失败（Gitee 拒绝了 PATCH /releases/${RELEASE_ID}）"
      print_remedies
      exit 1
    fi
  fi
fi

# ---------------------------------------------------------------------------
# 3. 上传 UPLOAD_ARTIFACTS 指定的产物（默认空集 = 全部跳过）
# ---------------------------------------------------------------------------
echo "==> [2/3] 上传产物"
UPLOADED=0
SKIPPED=0
NOT_UPLOADED=0
EXISTING=""
if [ "${#UPLOAD_LIST[@]}" -gt 0 ]; then
  EXISTING=$(asset_names "$(gitee_request "${API_MAX_TIME}" "${API_BASE}/releases/${RELEASE_ID}")")
fi

for BASE_NAME in "${ARTIFACT_LIST[@]}"; do
  FILE="${ASSETS_DIR}/${BASE_NAME}"

  if ! is_upload_target "${BASE_NAME}"; then
    echo "  -- 按策略不上传（正文已给直链）: ${BASE_NAME}"
    NOT_UPLOADED=$((NOT_UPLOADED + 1))
    continue
  fi

  if [ ! -f "${FILE}" ]; then
    echo "错误：${BASE_NAME} 在上传清单里，但产物目录中找不到：${FILE}"
    exit 1
  fi

  SIZE=$(wc -c < "${FILE}" | tr -d ' ')
  if [ "${SIZE}" -gt "${MAX_UPLOAD_BYTES}" ]; then
    echo "错误：${BASE_NAME} 大小 ${SIZE} 字节，超过单次上传上限 ${MAX_UPLOAD_BYTES}"
    exit 1
  fi

  if echo "${EXISTING}" | grep -qx "${BASE_NAME}"; then
    echo "  == 已存在，跳过: ${BASE_NAME}"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  echo "  -> 上传 ${BASE_NAME}（${SIZE} 字节，单请求上限 ${UPLOAD_MAX_TIME}s）"
  UPLOAD_RESP=$(gitee_request "${UPLOAD_MAX_TIME}" -X POST \
    "${API_BASE}/releases/${RELEASE_ID}/attach_files" \
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
# 4. 收尾校验：正文直链必须到位；上传清单里的附件必须全部存在
# ---------------------------------------------------------------------------
echo "==> [3/3] 校验 Gitee Release"
FINAL_RESP=$(gitee_request "${API_MAX_TIME}" "${API_BASE}/releases/${RELEASE_ID}")
FINAL_ASSETS=$(asset_names "${FINAL_RESP}")
FINAL_BODY=$(json_get "${FINAL_RESP}" "body")

if ! printf '%s' "${FINAL_BODY}" | grep -qF "${GH_DOWNLOAD_BASE}"; then
  echo "错误：Gitee 上这个 Release 的正文里没有 GitHub 直链（${GH_DOWNLOAD_BASE}）"
  echo "脚本已经试过自己补写（见上面 [1/3] 的输出），仍然没到位，所以："
  print_remedies
  exit 1
fi

if [ "${#UPLOAD_LIST[@]}" -gt 0 ]; then
  for BASE_NAME in "${UPLOAD_LIST[@]}"; do
    if ! echo "${FINAL_ASSETS}" | grep -qx "${BASE_NAME}"; then
      echo "错误：${BASE_NAME} 在上传清单里，但 Gitee 附件清单没有它"
      echo "当前附件清单：${FINAL_ASSETS}"
      exit 1
    fi
  done
fi

echo "同步完成：上传 ${UPLOADED} 个，跳过已存在 ${SKIPPED} 个，按策略不上传 ${NOT_UPLOADED} 个"
if [ "${#UPLOAD_LIST[@]}" -eq 0 ]; then
  echo "提示：本次只写入直链正文，Gitee 站内不提供二进制下载（这是 2026-09-29 起的默认策略）"
fi
echo "Gitee Release: ${RELEASE_PAGE}"
