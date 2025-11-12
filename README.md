# super-txt

Convert documentation websites into clean, section-aware Markdown files suitable for LLM ingestion, with a single-command terminal UI. Powered by [Crawl4AI](https://pypi.org/project/crawl4ai/). Outputs per-page Markdown, multiple human-friendly indexes, and a ZIP archive you can rename from the UI.

---

## Features

* **One-command run**: `python app.py` launches a guided, professional TUI.
* **Crawl4AI extraction**: uses `AsyncWebCrawler` for robust HTML → Markdown.
* **Scoped crawling**: same-domain and optional path-prefix filters.
* **Robots-aware**: respects `robots.txt` by default.
* **Fragment-aware export**: URLs with anchors (e.g. `#operation-…`) become focused files when possible.
* **Clean filenames**: URL-mirroring structure with sanitized names (`__fragment` suffix for anchors).
* **Indexes**:

  * `llms.txt` — minimal, LLM-friendly list.
  * `llms_index.md` — standard table of pages.
  * `llms_index_extended.md` — words, read-time, first H2, detected HTTP endpoints.
  * `sitemap.md` — simple directory hierarchy.
  * `llms_ai_index.md` — AI-enriched index placeholder (no external calls yet).
* **Zip packaging**: creates an archive and lets you name it from the UI.

---

## Why super-txt

LLM “feeds” benefit from curated, concise Markdown that mirrors the source site’s structure. super-txt crawls docs, slices sections, normalizes output, then builds indexes that are easy for both humans and tools to navigate.

---

## Requirements

* Python 3.10+
* Windows, macOS, or Linux
* Playwright browser dependencies (handled by `crawl4ai-setup`)

### Python dependencies
- setup the virtual environment `python -m venv venv`
- activate the virtual environment `source venv/bin/activate` (or `venv\Scripts\activate` on Windows)
- install dependencies, Use the provided `requirements.txt`:

Install:

```bash
pip install -r requirements.txt
```

> If you prefer manual install:
>
> ```bash
> pip install -U crawl4ai rich httpx beautifulsoup4 pyfiglet markdownify
> ```

---

## Installation & Setup (Crawl4AI 2023+ flow)

1. **Browser setup**

   ```bash
   crawl4ai-setup
   ```

2. **Diagnostics (optional but recommended)**

   ```bash
   crawl4ai-doctor
   ```

   This checks Python compatibility, Playwright install, and common environment issues. Follow any suggestions it prints, then re-run `crawl4ai-setup` if needed.

> Windows PowerShell note: if `crawl4ai-setup` complains about Playwright, run `playwright install` then re-run `crawl4ai-setup`.

---

## Quickstart

1. Put `app.py` at your project root.
2. Create and activate a virtual environment (recommended).
3. Install requirements and run the setup commands above.
4. Launch:

   ```bash
   python app.py
   ```

You’ll get a guided wizard that asks for:

* **Seed URLs** (comma-separated)
* **Restrict to same domain** (yes/no)
* **Path prefix filter** (e.g., `/api`)
* **Max pages**
* **Output directory**
* **Create ZIP + optional ZIP filename**
* **Obey robots.txt**
* **Export #fragment sections**
* **Index mode**: `standard`, `extended`, or `both`

### Example: Mistral API docs

At the **Seed URLs** prompt, paste:

```
https://docs.mistral.ai/api, https://docs.mistral.ai/api/endpoint/chat#operation-chat_completion_v1_chat_completions_post,
```

Use path prefix: `/api`.  or leave empty for agent to get the urls from root "/"

---

## Output

A typical export directory:

```
export/
├─ root/
│  └─ api.md
├─ api/
│  └─ endpoint/
│     ├─ chat.md
│     ├─ fim.md
│     ├─ agents.md
│     ├─ embeddings.md
│     └─ ...
├─ llms.txt
├─ llms_index.md
├─ llms_index_extended.md
├─ sitemap.md
└─ llms_ai_index.md
```

Each page file starts with:

```markdown
# Page Title

> Source: https://example.com/docs/page
```

### Indexes

* **llms.txt**: minimal, bullet-style index for LLM tools
* **llms_index.md**: table with title, file, source URL
* **llms_index_extended.md**: adds word count, estimated read minutes (~200 wpm), first H2, and detected HTTP endpoints (e.g., `POST /v1/chat/completions`)
* **sitemap.md**: hierarchical overview by folders

---

## How it works

* **Crawl**: A BFS queue walks same-domain links filtered by an optional prefix.
* **Fetch**: Raw HTML fetched via `httpx` (robots.txt checked beforehand unless disabled).
* **Extract**: Crawl4AI’s `AsyncWebCrawler` renders and extracts Markdown. If a page fails extraction, a `markdownify` fallback preserves content in plain Markdown.
* **Fragment slicing**: If a seed includes an anchor, super-txt attempts to isolate that section in the HTML and exports it as a focused Markdown file.
* **Normalize**: Paths map to directories; filenames are sanitized and include `__fragment` when applicable.
* **Index**: Multiple indexes are generated for human and programmatic consumption.
* **Package**: All files optionally zipped; filename can be set from the wizard.

---

## Professional usage guidelines

* **Respect site policies**: Keep robots.txt enabled unless you control the site.
* **Scope carefully**: Use path prefix filters to avoid crawling the whole domain.
* **Budget context**: Use `llms_index_extended.md` to identify large pages and decide what to feed an LLM.
* **Fragment seeds**: Use anchors on endpoint pages to create compact, page-per-operation files.

---

## Advanced tips

* **Faster iteration**: Start with a low `Max pages` and a narrow `Path prefix`. Increase gradually.
* **Stable seeds**: Prefer stable, versioned docs URLs to reduce churn.
* **Post-processing**: You can post-process Markdown with your linting or formatting tools; filenames are deterministic.

---

## Roadmap

* **AI-enriched index**: optional offline/hosted LLM pass to produce task-focused summaries, tags, and cross-links without changing your crawl settings.
* **Deeper section splitting**: per-heading file emission for long pages.
* **Deduplication**: heuristic merging for repeated content across versions.

The current build writes a placeholder file `llms_ai_index.md` and makes no external AI calls.

---

## Troubleshooting

* **“Crawl4AI is required / cannot import”**
  Ensure versions match:

  ```bash
  pip show crawl4ai
  crawl4ai-setup
  crawl4ai-doctor
  ```

  If needed:

  ```bash
  playwright install
  ```

* **Blank or partial pages**
  Some docs require client-side rendering; Crawl4AI handles this. If still blank, the fallback will emit plain text Markdown. Re-run later or lower `Max pages` to isolate issues.

* **Robots or rate limits**
  Keep robots on. If you control the site, consider allowing your user agent or reducing crawl scope.

* **Windows path issues**
  Use ASCII-only output paths if your shell or repository tools mis-handle Unicode. The exporter already sanitizes names.

---

## Configuration reference (wizard prompts)

* **Seed URLs**: comma-separated URLs to start from.
* **Restrict to same domain**: avoids cross-domain crawl.
* **Path prefix filter**: only crawl paths starting with this prefix (e.g., `/api`, `/docs/v1`).
* **Max pages**: upper bound on exports (BFS order).
* **Output directory**: where to write Markdown and indexes.
* **Create ZIP**: archive the export directory after completion.
* **ZIP filename**: custom name; will be sanitized.
* **Obey robots.txt**: recommended to keep on.
* **Export #fragment sections**: when a seed has `#anchor`, extract that section as a focused file.
* **Index mode**: `standard`, `extended`, or `both`.

---

## Development

* **Code style**: pragmatic, single-file CLI. Rich TUI + Crawl4AI async.
* **Testing targets**: public docs with known anchors and section hierarchy.
* **Contributing**: open issues/PRs with a clear before/after and sample URLs.

---

## License

MIT. See `LICENSE` if included; otherwise, feel free to add one as needed.

---

## Acknowledgments

* [Crawl4AI](https://pypi.org/project/crawl4ai/) for async crawling and Markdown extraction.
* [Rich](https://pypi.org/project/rich/) for terminal UI components.
* [BeautifulSoup](https://pypi.org/project/beautifulsoup4/) and [markdownify](https://pypi.org/project/markdownify/) for parsing and fallback conversion.

---

## Example session

```
$ python app.py

Seed URLs (comma-separated)  [https://docs.mistral.ai/api]:
Restrict to same domain as seeds? [Y/n]: y
Path prefix filter (blank for none)  [/api]:
Max pages to export  [200]:
Output directory  [./export]:
Create ZIP archive? [Y/n]: y
ZIP filename (blank = auto) []: mistral-api-llms
Obey robots.txt? [Y/n]: y
Export #fragment sections as separate files when present? [Y/n]: y
Index mode [standard|extended|both]  [both]:
```

After completion, look for:

* `export/llms.txt`
* `export/llms_index.md`
* `export/llms_index_extended.md`
* `export/sitemap.md`
* `mistral-api-llms.zip` (or auto-named)