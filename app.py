#!/usr/bin/env python3
"""
Super-TXT
Single-command TUI: run `python app.py` and follow the prompts.

• Uses Crawl4AI's AsyncWebCrawler for HTML→Markdown
• Rich terminal UI (banner, forms, progress) with robots.txt respect
• BFS crawl scoped to domain and optional path prefix
• Fragment-aware export for URLs with anchors
• Generates per-page Markdown, llms.txt, llms_index.md, and a ZIP

Install (Windows-friendly)
  pip install -U crawl4ai rich httpx beautifulsoup4 pyfiglet markdownify typer
  crawl4ai-setup   # downloads browser binaries
  crawl4ai-doctor  # sanity check

Run
  python app.py

"""
from __future__ import annotations

import asyncio
import os
import re
import sys
import time
import zipfile
from dataclasses import dataclass
from typing import Optional, List, Set, Dict, Tuple
from urllib.parse import urlparse, urljoin, urldefrag

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich import box

try:
    import pyfiglet
except Exception:
    pyfiglet = None

# Crawl4AI v0.7.x API
C4A_AVAILABLE = False
try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
    C4A_AVAILABLE = True
except Exception:
    AsyncWebCrawler = None
    BrowserConfig = None
    CrawlerRunConfig = None
    CacheMode = None

# Optional Markdown fallback
try:
    from markdownify import markdownify as fallback_md
except Exception:
    fallback_md = None

console = Console()
USER_AGENT = "llms-scraper/1.2 (Crawl4AI Async)"

@dataclass
class JobConfig:
    seeds: List[str]
    same_domain: bool = True
    path_prefix: Optional[str] = None
    max_pages: int = 200
    output_dir: str = "./export"
    make_zip: bool = True
    obey_robots: bool = True
    include_fragments: bool = True

@dataclass
class PageRecord:
    url: str
    filepath: str
    title: str
    description: str

# ---------------- UI helpers ----------------

def banner(text: str) -> str:
    if pyfiglet:
        try:
            return pyfiglet.figlet_format(text, font="Slant")
        except Exception:
            pass
    return f"{text}" + ("=" * len(text))

_slug_re = re.compile(r"[^a-zA-Z0-9\-_.]+")

def slugify(text: str) -> str:
    text = text.strip().lower().replace(" ", "-")
    text = _slug_re.sub("-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-._") or "index"

# ---------------- robots.txt ----------------

def fetch_robots_disallows(base_url: str, timeout: int = 15) -> Optional[Set[str]]:
    try:
        parsed = urlparse(base_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
            r = client.get(robots_url)
            if r.status_code != 200:
                return None
            disallows: Set[str] = set()
            ua_star = False
            for line in r.text.splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if line.lower().startswith('user-agent:'):
                    ua_star = line.split(':', 1)[1].strip() == '*'
                elif ua_star and line.lower().startswith('disallow:'):
                    path = line.split(':', 1)[1].strip()
                    if path:
                        disallows.add(path)
            return disallows
    except Exception:
        return None

def allowed_by_robots(url: str, disallows: Optional[Set[str]]) -> bool:
    if not disallows:
        return True
    path = urlparse(url).path or '/'
    return not any(path.startswith(prefix) for prefix in disallows)

# ---------------- scope/links ----------------

def same_domain(a: str, b: str) -> bool:
    return urlparse(a).netloc.lower() == urlparse(b).netloc.lower()

def under_prefix(url: str, prefix: Optional[str]) -> bool:
    if not prefix:
        return True
    return (urlparse(url).path or '/').startswith(prefix)

def extract_links(base_url: str, html: str) -> List[str]:
    soup = BeautifulSoup(html, 'html.parser')
    out: List[str] = []
    for a in soup.find_all('a', href=True):
        href = a.get('href').strip()
        if href.startswith('javascript:') or href.startswith('mailto:'):
            continue
        out.append(urljoin(base_url, href))
    return out

# ---------------- content/filenames ----------------

def path_for_url(url: str, base_dir: str) -> Tuple[str, str]:
    url_no_frag, frag = urldefrag(url)
    parsed = urlparse(url_no_frag)
    segs = [s for s in (parsed.path or '/').split('/') if s]
    if not segs:
        segs = ['index']
    base = segs[-1] or 'index'
    stem = slugify(base)
    if frag:
        stem += f"__{slugify(frag)}"
    folders = segs[:-1] if len(segs) > 1 else ['root']
    out_dir = os.path.join(base_dir, *[slugify(s) for s in folders])
    os.makedirs(out_dir, exist_ok=True)
    return os.path.join(out_dir, f"{stem}.md"), stem

def title_and_desc_from_html(html: str) -> Tuple[str, str]:
    soup = BeautifulSoup(html, 'html.parser')
    title = soup.title.string.strip() if soup.title and soup.title.string else 'Untitled'
    p = soup.find('p')
    desc = ''
    if p:
        desc = ' '.join(p.get_text(' ', strip=True).split())[:280]
    return title, desc

def slice_fragment_section(html: str, fragment: str) -> Optional[str]:
    if not fragment:
        return None
    soup = BeautifulSoup(html, 'html.parser')
    node = soup.find(id=fragment) or soup.find(attrs={'name': fragment})
    if not node:
        return None
    heading_tags = [f"h{i}" for i in range(1, 7)]
    start = node
    while start and start.name not in heading_tags:
        start = start.parent
    if not start:
        start = node
    level = int(start.name[1]) if start.name and start.name.startswith('h') and start.name[1:].isdigit() else 6
    collected = [start]
    for sib in start.next_siblings:
        if isinstance(sib, Tag) and sib.name in heading_tags and int(sib.name[1]) <= level:
            break
        collected.append(sib)
    frag_soup = BeautifulSoup('', 'html.parser')
    container = frag_soup.new_tag('div')
    for c in collected:
        container.append(c if isinstance(c, Tag) else NavigableString(str(c)))
    return str(container)

# ---------------- markdown fallback ----------------

def md_fallback(html: str) -> str:
    if fallback_md:
        try:
            return fallback_md(html, heading_style='ATX', strip=['style', 'script'])
        except Exception:
            pass
    soup = BeautifulSoup(html, 'html.parser')
    return soup.get_text('', strip=True)

# ---------------- network helpers ----------------

def fetch_html(url: str, timeout: int = 25) -> Tuple[Optional[str], Optional[str]]:
    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            r = client.get(url)
            if r.status_code != 200:
                return None, None
            ct = (r.headers.get('content-type') or '').lower()
            if 'text/html' not in ct and 'application/xhtml+xml' not in ct:
                return None, None
            return r.text, str(r.url)
    except Exception:
        return None, None

# ---------------- export helpers ----------------

def save_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

def build_indexes(base_dir: str, records: List[PageRecord]) -> None:
    lines = ["# Exported docs index", ""]
    for r in records:
        rel = os.path.relpath(r.filepath, base_dir).replace(os.sep, '/')
        lines.append(f"- [{r.title}]({rel}) — {r.description}")
    save_text(os.path.join(base_dir, 'llms.txt'), "".join(lines) + "")

    tbl = ["# LLMS Export Index", "", "| Title | File | Source URL |", "|---|---|---|"]
    for r in records:
        rel = os.path.relpath(r.filepath, base_dir).replace(os.sep, '/')
        tbl.append(f"| {r.title} | {rel} | {r.url} |")
    save_text(os.path.join(base_dir, 'llms_index.md'), "".join(tbl) + "")

def zip_dir(base_dir: str) -> str:
    zip_path = os.path.abspath(base_dir) + ".zip"
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(base_dir):
            for fn in files:
                fp = os.path.join(root, fn)
                zf.write(fp, arcname=os.path.relpath(fp, base_dir))
    return zip_path

# ---------------- async crawl core ----------------

async def acrawl(cfg: JobConfig) -> List[PageRecord]:
    if not C4A_AVAILABLE:
        console.print(Panel("Crawl4AI is required. Install it with: [bold]pip install crawl4ai[/bold]", style="red"))
        raise SystemExit(1)

    # Robots cache
    robots_cache: Dict[str, Optional[Set[str]]] = {}
    def allowed(u: str) -> bool:
        if not cfg.obey_robots:
            return True
        host = urlparse(u).netloc
        if host not in robots_cache:
            robots_cache[host] = fetch_robots_disallows(u)
        return allowed_by_robots(u, robots_cache[host])

    # Prepare crawler
    bconf = BrowserConfig(headless=True)
    runconf = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

    records: List[PageRecord] = []
    from collections import deque
    q = deque(cfg.seeds)
    visited: Set[str] = set()

    async with AsyncWebCrawler(config=bconf) as crawler:
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn(), TextColumn("{task.completed}/{task.total}"), TimeElapsedColumn(), console=console) as progress:
            task = progress.add_task("Crawling", total=cfg.max_pages)
            processed = 0

            while q and processed < cfg.max_pages:
                raw = q.popleft().strip()
                if not raw:
                    continue
                url_no_frag, frag = urldefrag(raw)
                if url_no_frag in visited:
                    continue
                visited.add(url_no_frag)

                if cfg.same_domain and not any(same_domain(url_no_frag, s) for s in cfg.seeds):
                    continue
                if not under_prefix(url_no_frag, cfg.path_prefix):
                    continue
                if not allowed(url_no_frag):
                    continue

                html, final_url = fetch_html(url_no_frag)
                if not html:
                    continue

                # Crawl4AI generates Markdown from the full page
                try:
                    result = await crawler.arun(url=url_no_frag, config=runconf)
                except TypeError:
                    result = await crawler.arun(url_no_frag)  # older signature fallback

                # Pull markdown robustly across versions
                md_text = None
                if hasattr(result, 'markdown'):
                    mk = getattr(result, 'markdown')
                    if isinstance(mk, str):
                        md_text = mk
                    else:
                        # object with raw_markdown / fit_markdown
                        for attr in ('fit_markdown', 'raw_markdown', 'markdown'):
                            if hasattr(mk, attr) and getattr(mk, attr):
                                md_text = getattr(mk, attr)
                                break
                if not md_text:
                    md_text = md_fallback(html)

                # If the original seed had a fragment, try slicing the HTML and replace md
                if cfg.include_fragments and frag:
                    section_html = slice_fragment_section(html, frag)
                    if section_html:
                        md_text = md_fallback(section_html)

                title, desc = title_and_desc_from_html(html)
                out_path, _ = path_for_url(raw, cfg.output_dir)
                save_text(out_path, f"# {title}> Source: {raw}" + md_text)
                records.append(PageRecord(url=raw, filepath=out_path, title=title, description=desc))

                processed += 1
                progress.update(task, advance=1, description=f"Saved: {title}")

                # Discover links from full HTML
                for link in extract_links(final_url, html):
                    ln, _ = urldefrag(link)
                    if ln in visited:
                        continue
                    if cfg.same_domain and not any(same_domain(ln, s) for s in cfg.seeds):
                        continue
                    if not under_prefix(ln, cfg.path_prefix):
                        continue
                    q.append(ln)

    build_indexes(cfg.output_dir, records)
    if cfg.make_zip:
        zip_path = zip_dir(cfg.output_dir)
        console.print(Panel.fit(f"ZIP created: [bold]{zip_path}[/bold]", style="green"))
    return records

# ---------------- wizard + main ----------------

def draw_header() -> None:
    console.clear()
    console.print(Text(banner("Super-TXT"), style="bold cyan"))
    console.print(Panel("Crawl docs → clean Markdown via Crawl4AI (Async).", style="cyan", box=box.ROUNDED))


def wizard() -> JobConfig:
    seeds_default = "https://your-docs.com/api"
    path_default = "/api"

    seeds_in = Prompt.ask("Seed URLs (comma-separated)", default=seeds_default)
    same_domain = Confirm.ask("Restrict to same domain as seeds?", default=True)
    path_prefix = Prompt.ask("Path prefix filter (blank for none)", default=path_default)
    max_pages_str = Prompt.ask("Max pages to export", default="200")
    try:
        max_pages = max(1, int(max_pages_str))
    except Exception:
        max_pages = 200
    output_dir = Prompt.ask("Output directory", default="./export")
    make_zip = Confirm.ask("Create ZIP archive?", default=True)
    obey_robots = Confirm.ask("Obey robots.txt?", default=True)
    include_fragments = Confirm.ask("Export #fragment sections as separate files when present?", default=True)

    seeds = [s.strip() for s in seeds_in.split(',') if s.strip()]
    path_prefix = path_prefix or None

    cfg = JobConfig(
        seeds=seeds,
        same_domain=same_domain,
        path_prefix=path_prefix,
        max_pages=max_pages,
        output_dir=output_dir,
        make_zip=make_zip,
        obey_robots=obey_robots,
        include_fragments=include_fragments,
    )

    tbl = Table(title="Run Configuration", box=box.SIMPLE_HEAVY)
    tbl.add_column("Key", style="bold")
    tbl.add_column("Value")
    tbl.add_row("Seeds", "".join(seeds))
    tbl.add_row("Same domain", str(same_domain))
    tbl.add_row("Path prefix", path_prefix or "(none)")
    tbl.add_row("Max pages", str(max_pages))
    tbl.add_row("Output dir", output_dir)
    tbl.add_row("ZIP", str(make_zip))
    tbl.add_row("Obey robots.txt", str(obey_robots))
    tbl.add_row("Include fragments", str(include_fragments))
    console.print(tbl)

    if not Confirm.ask("Start crawl?", default=True):
        raise SystemExit("Cancelled by user")
    return cfg

if __name__ == "__main__":
    draw_header()
    if not C4A_AVAILABLE:
        console.print(Panel("Crawl4AI is installed but import failed. You're likely on v0.7.x which exposes [bold]AsyncWebCrawler[/bold]. If problems persist, run: crawl4ai-setup and crawl4ai-doctor.", style="red"))
        sys.exit(1)
    cfg = wizard()
    t0 = time.time()
    recs = asyncio.run(acrawl(cfg))
    dt = time.time() - t0
    summary = Table(title="Export Summary", box=box.MINIMAL_HEAVY_HEAD)
    summary.add_column("Files", justify="right")
    summary.add_column("Output")
    summary.add_column("Time (s)", justify="right")
    summary.add_row(str(len(recs)), cfg.output_dir, f"{dt:.1f}")
    console.print(summary)