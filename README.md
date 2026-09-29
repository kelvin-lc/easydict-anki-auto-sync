# Easydict → Anki Auto Sync

Automatically turn English words looked up in [Easydict](https://github.com/tisfeng/Easydict) into cards in [Anki](https://apps.ankiweb.net/). Runs locally on macOS. New words are collected every five minutes; if Anki is closed, they wait in a local queue until Anki opens.

This is an independent bridge, not an official Easydict or Anki add-on. [AnkiConnect](https://ankiweb.net/shared/info/2055492159) is the Anki add-on used to create notes and store audio.

[中文说明](#中文说明) · [English](#english)

## 中文说明

### 效果

- 只收录 Easydict 历史中的英文单词，跳过短语、整句及无中文释义的记录；同一单词去重。
- 正面显示单词、英美音标和播放按钮；背面显示分词性释义、词形变化、最多两条双语例句及近义词。词典未返回的内容会留空。
- Mac 的系统语音为每个单词生成一次 MP3，保存为 Anki 媒体附件。桌面端打开正面自动播放一次，AnkiWeb 同步后可点击播放；浏览器可能限制自动播放。
- 详细词条读取 Easydict 使用的有道词典接口。词条请求失败时先保留简短释义，每小时重试。音频生成失败也每小时重试。
- 读取查词历史、保存队列、生成音频都在本机完成。请求详细词条时，该英文单词会发给有道。脚本不读取 AnkiWeb 账号或密码，也不直接连接 AnkiWeb；云端由 Anki 自身同步。

### 安装

需要 macOS、Easydict、桌面版 Anki、AnkiConnect 插件、Python 3.9+ 和 `ffmpeg`。`say` 随 macOS 提供。安装 AnkiConnect：Anki → 工具 → 插件 → 获取插件，输入 **2055492159**，然后重启 Anki。`ffmpeg` 可通过 `brew install ffmpeg` 安装。

```bash
git clone https://github.com/kelvin-lc/easydict-anki-auto-sync.git
cd easydict-anki-auto-sync
python3 install.py
```

安装时保持 Anki 打开，脚本会通过 AnkiConnect 读取当前配置档名称。如安装时不方便打开 Anki，可指定名称：

```bash
python3 install.py --profile "User 1"
```

可选参数：`--deck "Easydict 生词"`、`--interval 300`（秒，最少 60）、`--voice Samantha`。更新代码后在仓库目录再次执行 `python3 install.py`。安装程序备份旧脚本和启动配置，保留队列与已生成的音频。

安装后，macOS 登录时启动一个后台进程；每 5 分钟扫描一次，其余时间休眠。Anki 关闭时可继续收集查词记录，打开 Anki 后自动导入。首次导入通常在查词后的 **5～10 分钟**内；Anki 关闭期间的记录会在打开后下一轮补入。Easydict 自己清空或淘汰历史之前，脚本必须至少扫描过该记录。

### AnkiWeb 同步

在 Anki 桌面版点击“同步”，让卡片与 MP3 上传到 AnkiWeb。初次同步若出现“上传本机 / 下载云端”的冲突提示，请先确认哪一侧有需要保留的卡片；选择下载会替换本机未同步的修改。Anki 的[同步说明](https://docs.ankiweb.net/syncing.html)介绍了合并不同设备内容的方法。

### 暂停、卸载和排错

```bash
python3 uninstall.py
```

这会停止登录服务，保留 Anki 卡片、本地队列和 MP3 缓存。只有明确希望删除本地队列与缓存时才执行 `python3 uninstall.py --remove-local-data`；它也不会删除 Anki 中的卡片。

日志位于 `~/Library/Application Support/EasydictAnkiSync/sync.log`。如果卡片没有加入，请检查 Anki 是否打开、AnkiConnect 是否启用、Anki 配置档是否与安装时一致。目标牌组为独立牌组，不修改已有牌组的卡片。

## English

### Install

Requires macOS, Easydict, desktop Anki, [AnkiConnect](https://ankiweb.net/shared/info/2055492159) (add-on code `2055492159`), Python 3.9+, and `ffmpeg` (`brew install ffmpeg`). Keep Anki open during installation so the active profile can be detected.

```bash
git clone https://github.com/kelvin-lc/easydict-anki-auto-sync.git
cd easydict-anki-auto-sync
python3 install.py
```

Use `python3 install.py --profile "Your Anki profile"` if Anki is closed. Optional flags: `--deck`, `--interval` (seconds, default 300), and `--voice`. Run the installer again after updating the repository. Stop it with `python3 uninstall.py`.

The background process polls Easydict's saved query history, queues English words, creates Anki notes through AnkiConnect when Anki is available, and attaches a small MP3 generated once per word with macOS `say` and `ffmpeg`. Detailed definitions come from the same Youdao dictionary endpoint used by Easydict. Sync using Anki desktop to make the cards and MP3s available on AnkiWeb.

## License and attribution

GPL-3.0. The Youdao request and dictionary parsing are adapted from Easydict. See [THIRD_PARTY.md](THIRD_PARTY.md) and [LICENSE](LICENSE). Dictionary content belongs to its provider. This repository does not bundle dictionary entries or user data.
