# Easydict · Again / Good（可选）

这个小型插件只对 `Easydict English-Chinese` 笔记类型生效，在 Anki 桌面版的复习界面保留 Again / Good，使用 Anki 原生的评分值 1 / 3。Hard / Easy 的键盘评分也会被阻止；其他笔记类型不受影响。默认快捷键仍为 `1` 和 `3`，空格仍按 Anki 的设置显示答案或评为 Good。

它不更改 FSRS 算法、不修改已有复习记录，也不强制设置每日新词数量。已在 macOS Anki 26.9.3 上验证。AnkiWeb 不运行桌面插件，因此网页评分按钮仍由 AnkiWeb 控制。

## 安装

退出 Anki，在仓库目录执行：

```bash
mkdir -p "$HOME/Library/Application Support/Anki2/addons21"
cp -R anki_addon/easydict_two_buttons "$HOME/Library/Application Support/Anki2/addons21/"
```

重新打开 Anki。在“工具 → 插件”中可以看到 `Easydict · Again / Good`。停用或删除这个插件并重启 Anki，即可恢复四按钮。主项目的 `install.py` 和 `uninstall.py` 不负责安装或卸载此可选插件。

## 推荐的起步设置

在生词牌组的“选项”中克隆专用预设：每日新卡 5 张、复习上限 9999、新卡在复习之后、学习和重新学习步骤均为 `10m`。开启 FSRS，期望保留率用 90%，首次开启时保持“更改时重新安排卡片”关闭。“自动推进”的答案动作建议设为 Answer Again 而非 Bury Card，以免未评分的卡片被埋起。FSRS 开关作用于整个集合，其他参数按牌组预设生效。

## 更新卡片样式

新安装的笔记类型会自动使用仓库内的样式。已有笔记类型缺少新版字段（如 `Roots`、`Mnemonic`、`Family`）时，后台会在下一轮扫描中自动补字段并更新一次模板；字段齐全后不会在普通轮询时覆盖。若希望主动换成仓库最新版模板，保持 Anki 打开，在仓库目录执行：

```bash
python3 -c 'import sync; sync.setup_model()'
```

这会替换 `Easydict English-Chinese` 的样式及正反面模板，保留字段内容和复习进度；有个人模板改动时请先在 Anki 中备份。新版在背面优先展示精简释义、词根与助记和例句，将词形、同根词、近义词放在可展开区域，并提供浅色、深色和窄屏样式。
