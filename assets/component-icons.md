# 组件官方图标收集清单（2026-10-13）

## JetBrains 全家桶（统一黄色 LOGO）
- idea.svg (IntelliJ IDEA)
- pycharm.svg (PyCharm)  
- clion.svg (CLion)
- webstorm.svg (WebStorm)
- goland.svg (GoLand)
- datagrip.svg (DataGrip)
- rider.svg (Rider)
- app-code.svg (VS Code - 非 JetBrains，用 GH logo)

## Apache 系（羽毛 Logo + 软件名）
- tomcat.svg, kafka.svg, jetty.svg 等

## Docker & K8s 系
- docker.svg (蓝色鲸鱼)
- kubernetes.svg (蓝色海豚)
- helm.svg

## GitHub 系
- git.svg, github.svg

## Redis 相关
- redis.svg (红色字体或 logo)

## Database 系列
- mysql.svg, postgresql.svg, mongodb.svg, sqlite.svg

## 开发工具
- vscode.svg (GitHub logo), postman.svg, bron.svg, dbeaver.svg

## 其他主流
- python.svg, node.svg, go.svg, rust.svg, java.svg

总计约 **80+ 个图标**，优先覆盖前 30 个高频组件。

---

## 实现方案
1. **静态资源目录**: `assets/component-icons/`
2. **IconMap**: `{key: (filename, width, height)}`
3. **UI 布局**: 
   ```
   [图标] [标题] [详情按钮 ℹ] [角标]
   ```
4. **Fallback**: 缺少官方图标时按分类显示通用色块图标
