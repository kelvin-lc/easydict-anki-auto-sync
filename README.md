# Easydict → Anki Auto Sync

Automatically turn English words looked up in [Easydict](https://github.com/tisfeng/Easydict) into cards in [Anki](https://apps.ankiweb.net/). Runs locally on macOS. New words are collected every five minutes; if Anki is closed, they wait in a local queue until Anki opens.

This is an independent bridge, not an official Easydict or Anki add-on. [AnkiConnect](https://ankiweb.net/shared/info/2055492159) is the Anki add-on used to create notes and store audio.

[中文说明](#中文说明) · [English](#english)

## 中文说明

### 效果

- 只收录 Easydict 历史中的英文单词，跳过短语、整句及无中文释义的记录；同一单词去重。
- 正面显示单词、英美音标和播放按钮；背面显示分词性释义、词形变化、最多两条双语例句及近义词。词典未返回的内容会留空。
- Mac 的系统语音为每个单词生成一次 MP3，保存为 Anki 媒体附件。桌面端打开正面自动播放一次，AnkiWeb 同步后可点击播放；浏览器可能限制自动播放。
- 详细词条读取 Easydict 使用的有道词典接口。词条请求失败时先保留简短释义，每小时重试。音频生成失败也每小时重试。Anki 关闭或重启导致的连接中断会在下一轮扫描重试，不会额外等待一小时。
- 读取查词历史、保存队列、生成音频都在本机完成。请求详细词条时，该英文单词会发给有道。脚本不读取 AnkiWeb 账号或密码，也不直接连接 AnkiWeb；云端由 Anki 自身同步。

### 从零安装（macOS）

本项目需要 Mac 上的 Easydict 和桌面版 Anki；只有 AnkiWeb 网页版不能运行自动导入。无需 GitHub 账号，无需购买 API，也无需手动创建牌组、笔记类型或卡片模板。脚本仅使用 Python 标准库，不需要 `pip install`。

#### 1. 安装并打开两个应用

- 从 [Easydict 官方发布页](https://github.com/tisfeng/Easydict/releases)下载适合自己 Mac 的版本，把 **Easydict.app 放进 `/Applications`（应用程序）**，打开并完成首次设置。安装器会检查这个路径。
- 从 [Anki 官网](https://apps.ankiweb.net/)安装 Mac 桌面版，打开并进入你准备背单词的配置档。首次使用可以保留默认配置档。
- 在 Easydict 中查询一个英文单词（例如 `residual`），确认有中文翻译，且出现在查询历史中。脚本依赖保存的历史；短语、整句，以及没有中文释义的记录不会导入。

#### 2. 安装 AnkiConnect

在桌面 Anki 中选择 **工具 → 插件 → 获取插件**，输入 **2055492159**，安装后退出并重新打开 Anki，保持它打开。菜单名称可能随界面语言略有不同；参见 [Anki 插件安装说明](https://docs.ankiweb.net/addons.html)。

AnkiConnect 是装在 **Anki** 里的插件，不是 Easydict 插件。默认连接地址为本机 `127.0.0.1:8765`。本脚本按默认的无 API 密钥配置连接；若你自行修改了端口或开启 API 密钥，当前脚本需要相应适配。

#### 3. 准备终端和依赖

按 `⌘ + 空格`，搜索并打开“终端”（Terminal）。后续代码块逐个复制到终端，按回车执行；如有错误，先处理当前步骤，再继续。

如果尚未安装 Homebrew，按 [Homebrew 官网](https://brew.sh/)的说明安装，并执行安装结束时显示的 **Next steps**，使 `brew` 命令可用。然后安装依赖：

```bash
brew install python git ffmpeg
python3 --version
git --version
ffmpeg -version
```

Python 需要 3.9 或更高版本。以上三个版本命令都应正常输出。再确认系统英语语音可用（这条命令会发声）：

```bash
say -v Samantha "hello"
```

若提示找不到 Samantha，可在 macOS 的语音设置中下载该英语声音，或用 `say -v '?'` 查看可用声音，安装时通过 `--voice "声音名称"` 指定。

#### 4. 下载并安装本项目

以下命令把源码放在你自己的 `~/other_code` 下。已有此仓库时请按后面的“更新”步骤操作。

```bash
mkdir -p ~/other_code
cd ~/other_code
git clone https://github.com/kelvin-lc/easydict-anki-auto-sync.git
cd easydict-anki-auto-sync
python3 install.py
```

安装时保持 Anki 打开，安装器会读取当前配置档名称。出现 `Installed for Anki profile ...; scans every 300s.` 表示后台服务已加载，**不代表第一张卡片已完成导入**。

安装完成后可关闭终端。后台服务在登录 Mac 时自动启动，退出后由系统重新拉起。它不是由 Anki 启动的：Anki 关闭时仍收集历史，打开 Anki 后下一轮才写入卡片。Mac 休眠或未登录时不会定时运行。

#### 5. 确认安装成功

保持 Anki 打开，在 Easydict 查询一个还没导入过的英文单词，确认有中文释义。保持 Mac 唤醒，等待 **5～10 分钟**：

1. Anki 里应自动出现 **Easydict 生词** 牌组（首次成功导入时创建）。
2. 在 Anki“浏览”窗口搜索 `deck:"Easydict 生词"`，确认测试单词存在。
3. 预览卡片：正面有单词及音频播放按钮，背面有释义。详细词典内容需网络可用；词典未提供的音标、例句等字段可能留空。
4. 点击播放按钮确认有声音。若点击可播放但不会自动播放，请检查该牌组的音频选项是否禁用了自动播放。

每 5 分钟扫描一次，其余时间休眠。积压按每批 3 个连续补全音频和详细释义，批次间休息 0.3 秒，不会每批再等待 5 分钟。首次运行也会处理 Easydict 当前历史中符合条件的旧词。历史若在脚本读取之前就被清空或淘汰，脚本无法补回。

### 文件位置与更新

`~` 表示你自己的用户主目录，不需要替换成作者的用户名。

| 内容 | 默认路径 |
| --- | --- |
| 下载的源码仓库 | `~/other_code/easydict-anki-auto-sync/` |
| 后台实际运行的脚本 | `~/Library/Application Support/EasydictAnkiSync/sync.py` |
| 登录启动配置 | `~/Library/LaunchAgents/local.easydict.anki-sync.plist` |
| 单词队列及补全状态 | `~/Library/Application Support/EasydictAnkiSync/queue.sqlite3` |
| MP3 缓存 | `~/Library/Application Support/EasydictAnkiSync/audio/` |
| 运行日志 | `~/Library/Application Support/EasydictAnkiSync/sync.log` |

源码与运行副本是分开的。更新时，保持 Anki 打开并进入原来的配置档，执行：

```bash
cd ~/other_code/easydict-anki-auto-sync
git pull --ff-only
python3 install.py
```

**仅 `git pull` 不会更新后台运行副本。** 安装器会备份旧脚本和启动配置，保留队列及音频，并重新启动服务。安装器记录了 Python 和 ffmpeg 的实际路径；如果升级或移除依赖后后台无法启动，也请重新执行安装命令。

可选参数：`--profile "你的 Anki 配置档名"`、`--deck "Easydict 生词"`、`--interval 300`（秒，最少 60）、`--voice Samantha`。指定配置档时名称必须与 Anki 完全一致。**更新时重新提供你使用过的自定义参数**，安装器不会自动沿用旧参数。此队列用于一个配置档；不要把更换配置档当成迁移卡片的方法。

### AnkiWeb 同步

在 Anki 桌面版点击“同步”，让卡片与 MP3 上传到 AnkiWeb。初次同步若出现“上传本机 / 下载云端”的冲突提示，请先确认哪一侧有需要保留的卡片；选择下载会替换本机未同步的修改。Anki 的[同步说明](https://docs.ankiweb.net/syncing.html)介绍了合并不同设备内容的方法。

### 暂停、卸载和排错

```bash
cd ~/other_code/easydict-anki-auto-sync
python3 uninstall.py
```

这会停止登录服务，保留 Anki 卡片、本地队列和 MP3 缓存。只有明确希望删除本地队列与缓存时才执行 `python3 uninstall.py --remove-local-data`；它也不会删除 Anki 中的卡片。

日志位于 `~/Library/Application Support/EasydictAnkiSync/sync.log`。如果卡片没有加入，请检查 Anki 是否打开、AnkiConnect 是否启用、Anki 配置档是否与安装时一致。默认目标牌组为 `Easydict 生词`。恢复后台服务时，在仓库中重新执行 `python3 install.py`（有自定义参数时一并提供）。

查看后台状态及最近日志：

```bash
launchctl print "gui/$(id -u)/local.easydict.anki-sync"
tail -n 50 "$HOME/Library/Application Support/EasydictAnkiSync/sync.log"
tail -n 50 "$HOME/Library/Application Support/EasydictAnkiSync/service-error.log"
```

状态中 `state = running` 表示进程正在运行。日志文件尚未创建时，`tail` 会提示不存在；结合安装输出和服务错误日志判断。

| 现象 | 检查或处理 |
| --- | --- |
| `brew: command not found` | 完成 Homebrew 安装，并执行其 Next steps，然后重新打开终端。 |
| `Easydict.app was not found` | 将应用移到 `/Applications/Easydict.app`。 |
| `open Anki with AnkiConnect enabled` | 打开 Anki，确认插件已安装启用，安装插件后重启 Anki。 |
| `Waiting for Anki profile ...` | 切换到安装时指定的 Anki 配置档。 |
| `Connection refused` | Anki 关闭时正常；保持 Anki 和 AnkiConnect 运行，等待下一轮。 |
| 一直没有卡片 | 检查 Easydict 历史里是否有英文单词及中文翻译；确认 Mac 醒着、服务运行、Anki 配置档正确。 |
| 有简短释义但没有详细内容 | 查看日志中词典请求的错误；网络恢复后失败项目每小时重试。 |
| 没有音频按钮 | 检查日志中的音频生成错误，以及 `say` 和 `ffmpeg` 是否正常。 |
| 更新后后台反复退出 | 查看 `service-error.log`；确认依赖路径仍存在，重新运行安装器。 |

## English

### Install

For the full step-by-step walkthrough, verification, file locations, and troubleshooting, see the [Chinese guide](#中文说明) above.

Requires macOS, Easydict, desktop Anki, [AnkiConnect](https://ankiweb.net/shared/info/2055492159) (add-on code `2055492159`), Python 3.9+, and `ffmpeg` (`brew install ffmpeg`). Place Easydict.app in `/Applications`, look up an English word with a Chinese translation, and confirm it is saved in history. Install AnkiConnect in Anki via Tools → Add-ons → Get Add-ons, then restart Anki. Keep Anki open during installation so the active profile can be detected. No GitHub account, manual deck/template setup, or pip packages are required.

If dependencies are missing, install [Homebrew](https://brew.sh/), follow its Next steps, and run `brew install python git ffmpeg`. Check speech with `say -v Samantha "hello"`.

```bash
git clone https://github.com/kelvin-lc/easydict-anki-auto-sync.git
cd easydict-anki-auto-sync
python3 install.py
```

Use `python3 install.py --profile "Your Anki profile"` if Anki is closed. Optional flags: `--deck`, `--interval` (seconds, default 300), and `--voice`. Run the installer again after updating the repository. Re-supply any custom options on every reinstall; old options are not automatically retained. Pulling the repository alone does not update the installed copy. Stop it with `python3 uninstall.py`; cards and local data are preserved by default.

After installation, close Terminal if desired. The service starts at macOS login and keeps running independently of Anki. With Anki open and the Mac awake, look up a new English word with a Chinese translation, wait 5–10 minutes, and check the automatically created `Easydict 生词` deck. Preview the card and click its audio button. Desktop-only use does not require an AnkiWeb account.

The background process polls Easydict's saved query history, queues English words, creates Anki notes through AnkiConnect when Anki is available, and attaches a small MP3 generated once per word with macOS `say` and `ffmpeg`. Detailed definitions come from the same Youdao dictionary endpoint used by Easydict. Ready work is drained sequentially in batches of three, with a 0.3-second pause between batches, without waiting another polling interval. Anki connection interruptions leave tasks eligible for the next scan; dictionary and audio-generation failures retry after an hour. Sync using Anki desktop to make the cards and MP3s available on AnkiWeb.

## License and attribution

GPL-3.0. The Youdao request and dictionary parsing are adapted from Easydict. See [THIRD_PARTY.md](THIRD_PARTY.md) and [LICENSE](LICENSE). Dictionary content belongs to its provider. This repository does not bundle dictionary entries or user data.
