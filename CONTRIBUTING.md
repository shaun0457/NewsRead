# 参与贡献

欢迎提 Issue 和 PR。下面是一些约定，照着来能更快合并。

## 本地跑起来

需要 Python 3.10+。

```bash
git clone https://github.com/Edwardxlai/easyread
cd easyread
python -m pip install -e .
easyread
```

浏览器会打开 `http://127.0.0.1:8765`。也可以直接用 `start.cmd`（Windows）或 `./start.sh`（macOS / Linux）。

改桌面版（Electron）还需要 Node.js 22+，见 README 的“桌面版”一节。

## 跑测试

```bash
python -m unittest discover tests -v
node --test tests/test_*.cjs
```

提 PR 后 GitHub Actions 会在 Windows、macOS、Linux 上自动跑一遍。第一次贡献的 PR 需要维护者点一下批准才会开始跑，稍等就好。

## 提 PR

- 一个 PR 只做一件事，方便审和回退。
- 标题和说明写清楚改了什么、为什么改；修 bug 的话写一下怎么复现。
- 改了界面的，附一张截图。
- 修了 bug 或加了功能，尽量在 `tests/` 里补一个测试。
- 不用改 `CHANGELOG.md` 和版本号，发版时维护者统一写。

## 报问题

直接开 Issue 就行，有模板提示要写哪些信息，填不全也没关系。
