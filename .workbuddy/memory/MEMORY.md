# 项目长期约定（byte-tools）

## 发布与 CI

- 发布方式：推 tag（`git tag vX.Y.Z && git push origin vX.Y.Z`）触发 `.github/workflows/release.yml`，三平台（windows-latest / macos-15 / ubuntu-latest）PyInstaller 打包，草稿暂存后自动取消草稿发布 GitHub Release，再同步 Gitee。
- Gitee 同步统一走项目根目录的 `同步Gitee产物.sh`（重试 + 幂等 + 附件校验），不要在 workflow 里裸写 curl。该脚本也可在本机手动执行做补救。
- 用户偏好：脚本放项目根目录，不要放进 scripts/ 之类的子文件夹；Windows 场景要有可双击运行的 `.bat`（与 `.sh` 功能等价）。
- 同步脚本有两份且必须同步维护：根目录 `同步Gitee产物.sh`（CI / Linux / macOS）与 `同步Gitee产物.bat`（Windows 手动补同步）。改白名单或流程时两个都要改。
- `.bat` 内容必须纯 ASCII（cmd 按 GBK 解析 UTF-8 会破坏语法），文件名可中文。
- 历史 tag 漏同步时，用 GitHub Actions 的 `workflow_dispatch`（输入 tag_name）补跑同步，不重新构建；它读的是默认分支上的 workflow，所以改动 push 到 master 后即可对任意历史 tag 生效。
- 仓库 owner：GitHub = `jilong2026`，Gitee = `jack_liujilong`，两边不同名。
- 已知两个历史坑：① `macos-13`(Intel) runner 已下线，加了会导致 job 永久 queued（已停用该 matrix 项）；② GitHub 境外 runner 连 gitee.com 会偶发 curl(35) SSL_ERROR_SYSCALL，靠脚本重试兜底，必要时把 sync-to-gitee 的 runs-on 改成国内 self-hosted runner。
- 产物白名单（改 matrix 时必须同步维护）：byte-tools.exe / byte-tools-windows-x64.zip / byte-tools-macos-arm64.zip / byte-tools-linux-x64。
