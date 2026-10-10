# PaperRead

<p align="center">
  <img src="easyread/web/paperread-mark.png" width="72" alt="PaperRead">
</p>

<p align="center"><b>A local research workspace for discovering, reading, and organizing papers.</b><br>
PaperRead combines a comfortable PDF reading experience with research exploration, candidate management, reading progress, AI-assisted summaries, reading paths, and paper mind maps.</p>

> This is YuriyLin's PaperRead fork. It keeps the useful local reading and annotation model from EasyRead while adding a Traditional Chinese interface, a research workspace, and Windows/Linux desktop packages plus a Docker browser edition.

<p align="center"><a href="README.md">繁體中文</a> · <b>English</b></p>

<p align="center"><a href="https://github.com/YuriyLin/PaperRead">Homepage</a> · <a href="https://github.com/YuriyLin/PaperRead/releases/latest">Download</a> · <a href="https://github.com/YuriyLin/PaperRead/issues">Issues</a></p>

<p align="center">
  <a href="https://github.com/YuriyLin/PaperRead/releases/latest"><img src="https://img.shields.io/github/v/release/YuriyLin/PaperRead?label=release" alt="release"></a>
  <a href="https://github.com/YuriyLin/PaperRead/actions/workflows/test.yml"><img src="https://github.com/YuriyLin/PaperRead/actions/workflows/test.yml/badge.svg" alt="tests"></a>
  <img src="https://img.shields.io/badge/Windows%20x64%20%7C%20Linux%20x64-supported-2f6070" alt="Windows x64 and Linux x64 supported">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="MIT license">
</p>

PaperRead provides **Windows x64** and **Linux x64** desktop packages. The Windows installer and Linux AppImage bundle the Electron application, Python backend, and required dependencies; Python and Node.js are not required for normal use. macOS does not currently have a prebuilt desktop package, but it can use the Docker browser edition.

## What PaperRead adds to EasyRead

The reader remains the place for close reading: bilingual text, equations, page-aware PDF locating, highlights, notes, questions, and Ask AI. PaperRead adds a research workflow around that reader:

| Area | PaperRead behavior |
|---|---|
| **Research Explorer** | Search by topic, conference, journal, year, and venue. Multiple venues can be entered together, such as `ICCV ECCV CVPR`, or a single venue such as `MICCAI`. |
| **Reading Board** | Move papers by drag and drop between **To read**, **Reading**, **To organize**, and **Completed**. Reading progress and the interest star are independent and remain synchronized with the library and reader. |
| **Candidates** | Keep a separate list of papers worth reviewing. Adding a candidate does not silently replace the search results or force a download. |
| **Organized Summaries** | Generate and review a paper summary when you choose, render it as Markdown, and export it for later use. Summaries can be removed to the recycle bin. |
| **Reading Path** | Start from a topic or a selected paper and organize recommended papers by purpose, such as foundations, method understanding, representative work, extensions, and frontier research. |
| **Paper Mind Map** | Ask AI to turn the current paper into a Traditional Chinese Mermaid mind map covering the research question, method, findings, contribution, and limitations. |
| **Smart Annotations** | Generate reviewable AI highlight or underline suggestions for the full paper, a section, or a research purpose. Suggestions never overwrite manual annotations before you accept them. |

The interface is localized for Taiwan Traditional Chinese usage. English technical terms such as `OpenAlex`, `Ollama`, `Mermaid`, model names, and API names remain unchanged where that improves clarity. Translation language and interface language are separate settings.

## Typical workflow

1. Open **Research Explorer** and search a topic or one or more venues.
2. Add promising papers to **Candidates**. Results from different sources are merged and duplicate papers are removed.
3. Review the candidate list and choose which papers need a summary. Summary generation and export are explicit user actions.
4. Move papers on the **Reading Board** to set the reading order and progress.
5. Open a paper in the reader to highlight, annotate, ask questions, and verify the original PDF.
6. Generate a **Reading Path** or a **Paper Mind Map** when you need a broader view of the research area.

When adding a paper to the Reading Board, categories are shown as selectable cards rather than a keyboard-dependent multi-select list. You can assign multiple research directions at once, or add the paper without a category and organize it later.

## Reading and evidence

PaperRead keeps translated text, AI explanations, and personal notes as separate data. Figures and tables preserve their layout as placeholders in the reading view; open the original PDF to inspect the source image or table. This avoids presenting a cropped screenshot or an unverified translation as the original evidence.

The local library stores paper metadata, PDF files, page data, block identifiers, translations, highlights, notes, discussions, and chat history. Existing EasyRead data is kept compatible where possible, and PaperRead data is stored under the `PaperRead` user folder.

## Smart annotations

The reader's Notes panel provides **Smart Annotations** for finding research-relevant passages. Before starting, choose:

- the **full paper** or a selected section;
- **automatic annotations**, reviewable **suggestions**, or annotations guided by a research purpose;
- an optional purpose such as `Find methods and limitations relevant to 3D segmentation`.

Each suggestion shows its page, location status, color, highlight or underline type, AI note, and reason. You can accept, edit, or reject suggestions one by one, or accept all suggestions that have been safely located. Unlocatable text remains pending for review instead of being applied to an uncertain position.

Colors have stable meanings: yellow for core concepts and claims, green for methods and implementation details, blue for experiments and quantitative evidence, and red for limitations, failure cases, assumptions, and open questions. Accepted suggestions use the existing annotation system and never overwrite manual annotations.

The analysis uses the stable English source together with the current Traditional Chinese translation, then places accepted annotations on the Chinese reading text when it can verify the location. After a retranslation, PaperRead rechecks the anchors; it asks for another analysis or manual editing when the new location cannot be confirmed.

When **Quote the original with each item** is enabled during Markdown export, the quote and the user's note are separated clearly: the translated passage is rendered as a Markdown blockquote, followed by **My note** or **My question**.

## Models and AI services

PaperRead can use configured cloud APIs, CLI-based model services, or local OpenAI-compatible endpoints. Common options include OpenAI/Codex, Anthropic, Gemini, DeepSeek, Zhipu GLM, SiliconFlow, Ollama, LM Studio, and custom endpoints. Local models can be selected from the model list when the service is running, for example an Ollama model at `http://127.0.0.1:11434`.

Model availability, rate limits, and response formats depend on the selected provider. Basic reading, the library, the candidate list, and the board remain usable when an AI provider is unavailable. AI-generated summaries, reading paths, and mind maps should be reviewed against the original paper before being used as research conclusions.

## Install on Windows

Download the latest `PaperRead-Setup-x.x.x.exe` from [Releases](https://github.com/YuriyLin/PaperRead/releases/latest). The installer supports per-user installation, lets you choose the install directory, and can create a desktop shortcut. The installer is currently not code-signed, so Windows SmartScreen may require **More info → Run anyway** after you verify that the file came from this repository.

For development, install Python 3.10+ and run `start.cmd` from the repository root. The local service listens on `127.0.0.1`; paper files and settings remain on the local machine unless a configured model service receives selected content for translation or AI analysis.

## Install on Linux

Download `PaperRead-x.x.x.AppImage` from [Releases](https://github.com/YuriyLin/PaperRead/releases/latest), then make it executable and launch it:

```bash
chmod +x PaperRead-*.AppImage
./PaperRead-*.AppImage
```

The AppImage is the supported Linux x64 desktop package. macOS does not currently have a prebuilt desktop package.

## Run with Docker

The Docker edition runs PaperRead as a local web service and works on Linux, macOS, and Windows with Docker Desktop. From a checkout of this repository:

```bash
docker compose up -d
```

Open <http://localhost:8765>. The Compose file stores the library and settings in the named `paperread-data` volume, so `docker compose down` does not remove your data. If Ollama runs on the host machine, use `http://host.docker.internal:11434/v1` as its OpenAI-compatible endpoint; the included Compose configuration provides the host mapping. Keep the service on a trusted local network and do not expose it directly to the public Internet without authentication and a firewall.

## Development

The web interface uses plain HTML, CSS, and JavaScript. The backend is Python and the desktop shell is Electron. Useful checks include:

```bash
python -m unittest discover tests
node tests/e2e.cjs library/<paper-id>
```

To create the Windows installer or Linux AppImage after testing locally:

```bash
npm run dist
```

## License

MIT. Math rendering uses [KaTeX](https://katex.org) (MIT).

## Contributors

- [@YuriyLin](https://github.com/YuriyLin) — PaperRead fork, Traditional Chinese interface, research workspace, reading workflow, Windows desktop packaging, and release maintenance
- [@Wang-auspicious](https://github.com/Wang-auspicious) — upstream Electron desktop packaging and release workflow
- [@bisuwuss-netizen](https://github.com/bisuwuss-netizen) — upstream PDF dependency, page locating, Markdown rendering, and streaming fixes
- [@MeshedPoto](https://github.com/MeshedPoto) — upstream PDF translation, highlighting, macOS reliability, and math rendering fixes
- [@Lzy22301093](https://github.com/Lzy22301093) — upstream table validation and rendering resilience
