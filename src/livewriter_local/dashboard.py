"""Server-rendered publishing dashboard."""

from datetime import datetime
import html


def _date_label(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%b %d, %Y")
    except (TypeError, ValueError):
        return value


def render_dashboard(config, posts: list[dict], media_count: int) -> str:
    published = sum(post["post_status"] == "published" for post in posts)
    drafts = sum(post["post_status"] == "draft" for post in posts)
    rows = "".join(
        f'''<a class="post-row" href="/posts/{html.escape(post["postid"])}"
              data-status="{html.escape(post["post_status"])}"
              data-search="{html.escape((post["title"] + " " + post["description"]).lower(), quote=True)}">
            <span class="post-mark" aria-hidden="true">{index:02d}</span>
            <span class="post-copy"><strong>{html.escape(post["title"] or "Untitled entry")}</strong>
              <small>{html.escape(_date_label(post["updated_at"]))}</small></span>
            <span class="status status--{html.escape(post["post_status"])}"><i></i>{html.escape(post["post_status"].title())}</span>
            <span class="row-arrow" aria-hidden="true">↗</span>
          </a>'''
        for index, post in enumerate(posts, start=1)
    )
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#f4f5ef">
  <link rel="EditURI" type="application/rsd+xml" href="{html.escape(config.rsd_path)}">
  <link rel="stylesheet" href="/static/dashboard.css">
  <title>{html.escape(config.blog_name)} | Local Library</title>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <a class="brand" href="/" aria-label="LiveWriter Local home">
        <span class="brand-seal" aria-hidden="true"><span></span><span></span><span></span></span>
        <span class="brand-name">LiveWriter <b>Local</b></span>
      </a>
      <nav class="topnav" aria-label="Main navigation">
        <a class="nav-link is-current" href="/">Library</a>
        <a class="nav-link" href="/media-library">Media</a>
        <a class="nav-link" href="/diagnostics">Diagnostics</a>
      </nav>
      <div class="server-state"><span class="live-dot"></span><span>Running locally</span></div>
    </header>

    <main>
      <section class="masthead" aria-labelledby="page-title">
        <div class="masthead-copy">
          <p class="eyebrow"><span>YOUR PRIVATE PUBLISHING DESK</span><span class="eyebrow-rule"></span></p>
          <h1 id="page-title">A home for<br><em>your words.</em></h1>
          <p class="intro">A quiet, local library for everything you create in Windows Live Writer.</p>
        </div>
        <div class="masthead-art" aria-hidden="true">
          <span class="sun-disc"></span><span class="orbit orbit--one"></span><span class="orbit orbit--two"></span>
          <span class="art-stem"></span><span class="art-leaf art-leaf--one"></span><span class="art-leaf art-leaf--two"></span>
          <span class="art-caption">KEEP<br>IN GOOD<br>COMPANY</span>
          <span class="art-index">LW—001</span>
        </div>
      </section>

      <section class="overview" aria-label="Library overview">
        <div class="overview-heading"><span>AT A GLANCE</span><span class="overview-line"></span></div>
        <div class="stat-grid">
          <div class="stat"><span class="stat-label">Total entries</span><strong>{len(posts):02d}</strong><span class="stat-note">in your library</span></div>
          <div class="stat"><span class="stat-label">Published</span><strong>{published:02d}</strong><span class="stat-note">ready to read</span></div>
          <div class="stat"><span class="stat-label">Drafts</span><strong>{drafts:02d}</strong><span class="stat-note">still taking shape</span></div>
          <div class="stat"><span class="stat-label">Media files</span><strong>{media_count:02d}</strong><span class="stat-note">kept close by</span></div>
        </div>
      </section>

      <div class="library-layout">
        <section class="post-library" aria-labelledby="library-title">
          <div class="section-heading">
            <div><p class="eyebrow eyebrow--dark">THE COLLECTION</p><h2 id="library-title">Recent entries<span class="title-count">{len(posts):02d}</span></h2></div>
            <label class="search-box"><span class="search-symbol" aria-hidden="true">⌕</span><input id="post-search" type="search" placeholder="Find an entry" aria-label="Find an entry"></label>
          </div>
          <div class="filters" role="group" aria-label="Filter entries">
            <button class="filter is-selected" type="button" data-filter="all" aria-pressed="true">All entries</button>
            <button class="filter" type="button" data-filter="published" aria-pressed="false">Published</button>
            <button class="filter" type="button" data-filter="draft" aria-pressed="false">Drafts</button>
          </div>
          <div class="post-list" id="post-list">{rows or '<div class="empty-state"><span class="empty-star">✳</span><h3>Your first entry starts here.</h3><p>Publish or save a draft from Windows Live Writer and it will appear in this library.</p></div>'}</div>
          <p class="no-results" id="no-results" hidden>No entries match that search.</p>
        </section>

        <aside class="desk-notes" aria-label="Connection details">
          <div class="note-top"><span class="note-kicker">THE LOCAL DESK</span><span class="note-number">01 / 03</span></div>
          <h2>Connected,<br><em>by design.</em></h2>
          <p>Your publishing service stays on this computer. Posts, images, and metadata are stored in your local data folder.</p>
          <div class="endpoint-block"><span>XML-RPC ADDRESS</span><code>{html.escape(config.blog_url.rstrip('/') + config.xmlrpc_path)}</code><button type="button" id="copy-endpoint" aria-label="Copy XML-RPC address" title="Copy address">Copy</button></div>
          <div class="note-footer"><span class="live-dot"></span><span>Private loopback connection</span></div>
        </aside>
      </div>
    </main>

    <footer class="site-footer"><span>{html.escape(config.blog_name)}</span><span>YOUR WORDS. YOUR MACHINE.</span><a href="{html.escape(config.rsd_path)}">RSD discovery ↗</a></footer>
  </div>
  <script src="/static/dashboard.js" defer></script>
</body>
</html>'''