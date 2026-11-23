# ComicNest

**把 NAS 上的漫画直接读出来的 TOS 7 应用。**

![版本](https://img.shields.io/badge/version-1.0.006-2f6f4e)
![TOS](https://img.shields.io/badge/TOS-7.0%2B-2f6f4e)
![架构](https://img.shields.io/badge/arch-x86__64%20%7C%20aarch64-2f6f4e)

ComicNest 不需要导入或转换：压缩包、PDF 和图片文件夹都原地读取，文件始终留在 NAS 上，远程图源按需缓存。书架自动扫描图源、识别系列与章节，阅读进度、翻页方向、动画等习惯会记在每本漫画上。

## 功能

**书架**

- 自动扫描本机共享文件夹、WebDAV 与 SMB 图源，识别系列、章节与封面。
- 「继续阅读」置顶最近在看的漫画，卡片上给出章节与进度。
- 按标题或作者搜索，按图源筛选；空书架会明确提示联系管理员添加图源。

**阅读器**

- 页面布局：单页、双页、拆分双页（跨页图自动铺满）。
- 阅读方向：从右至左、从左至右、从上至下。
- 翻页动画：平移、卷轴、仿真，可单独搭配方向使用。
- 亮度与缩放（放大后可拖动画面），进度滑杆与页码定位。
- 记住每本漫画的进度、布局、方向、动画与亮度；到达卷末可直接进入下一话。

**格式与图源**

- 压缩包：cbz、cbr、cb7、zip、rar、7z、tar；文档：pdf；以及散图文件夹。
- 本机文件夹、WebDAV、SMB；远程文件按需缓存，默认上限 8 GB，超过自动回收。
- 图源对 NAS 上的所有用户共享，只有管理员可以增删改。

**界面与权限**

- 深色/浅色主题；界面语言默认跟随 TOS 显示语言，也可手动固定（zh-CN、zh-TW、en、ja、ko、de、fr、es、ru）。
- 复用 TOS 登录会话与用户身份，管理员组（administrators / admin / wheel）进入「管理」维护图源。
- 适配 TOS 窗口标题栏与拖拽区，滚动内容不会画到标题栏下面。

## 安装

1. 取得对应架构的安装包：`comicnest_x86_64.deb` 或 `comicnest_aarch64.deb`。
2. 上传到 NAS 后安装：

   ```bash
   sudo dpkg -i comicnest_x86_64.deb
   ```

3. 打开 TOS 桌面上的 ComicNest。首次使用由管理员在「管理 → 图源」里添加文件夹或远程图源，默认共享目录是 `/Volume1/comicnest`。

## 构建

只需要 Python 3，无需 Node 或前端构建链：

```bash
python tools/build.py --platform x86_64    # 或 aarch64
```

产物位于 `dist/comicnest_<arch>.deb`。

本地调试（免鉴权、内置演示库）：

```bash
python tools/serve_dev_tcp.py --port 8787
```

## 结构

```
DEBIAN/                     打包脚本（preinst/postinst/prerm/postrm）
usr/local/comicnest/        Python 服务、扫描器、阅读器后端与 systemd 单元
webui/                      原生 ES modules + CSS，无编译步骤
tools/                      构建、校验与本地开发服务器
```

- 服务通过 Unix socket `/var/api/comicnest.sock` 提供 API，TOS 侧经 `/v2/proxy/comicnest/` 访问。
- 鉴权复用 TOS 会话 Cookie 与 CSRF 头；远程图源密码存放在应用私有的 secret store，不写入数据库。
