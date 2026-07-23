/* Markdown renderer for the Human Console — safe by construction.
 *
 * renderMarkdown(src) -> HTML string. The GitHub-Flavored-Markdown subset the
 * Console's prose actually uses (headers, bold/italic, inline + fenced code,
 * lists, tables, blockquotes, links, rules); everything else degrades to
 * escaped text.
 *
 * Security model (docs/console/design-principles.md #11): task text is
 * UNTRUSTED (GitHub issue bodies, human notes). This renderer NEVER passes
 * input-derived HTML through — it emits only its own fixed tag set, and every
 * piece of input text reaches the output through escapeHtml() at the leaves.
 * So there is no raw-HTML injection surface and no need for a sanitizer: a
 * `<script>` in the source becomes the literal text `<script>`. The one
 * remaining vector — dangerous URLs in links — is closed by safeHref(), which
 * allowlists http/https/mailto and drops anything else (e.g. javascript:).
 *
 * Self-contained: defines its own escapeHtml so it does not depend on app.js
 * or load order.
 */
"use strict";

(function (global) {
  function escapeHtml(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;",
               '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // Only these protocols may appear in a link href. Everything else — most
  // importantly javascript:/data:/vbscript: — drops the link to plain text.
  function safeHref(url) {
    const u = String(url || "").trim();
    if (/^(https?:|mailto:)/i.test(u)) return u;       // absolute, allowlisted
    if (/^[/#?]/.test(u)) return u;                    // relative / anchor / query
    if (/^[a-z][a-z0-9+.-]*:/i.test(u)) return null;   // some other scheme -> reject
    return u;                                          // bare relative (foo/bar)
  }

  /* ---------- inline ---------- */

  // Render one line/span of inline markdown. Order matters: pull out inline
  // code and links FIRST (their contents must not be re-formatted or escaped
  // twice), leaving placeholders, then apply emphasis to what remains, then
  // escape all surviving literal text. Placeholders use \x00..\x01 sentinels
  // that cannot occur in escaped output.
  function renderInline(src) {
    const slots = [];
    let text = String(src == null ? "" : src);

    // Inline code: `code` (contents escaped verbatim, never interpreted).
    text = text.replace(/`([^`]+)`/g, function (_, code) {
      slots.push("<code>" + escapeHtml(code) + "</code>");
      return "\x00" + (slots.length - 1) + "\x01";
    });

    // Links: [text](url). Link text may itself contain emphasis, so render it
    // recursively; the href is allowlisted and, if rejected, the whole link
    // degrades to its escaped label.
    text = text.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function (_, label, url) {
      const href = safeHref(url);
      const inner = renderInline(label);
      const html = href == null
        ? inner
        : '<a href="' + escapeHtml(href) +
          '" target="_blank" rel="noopener noreferrer">' + inner + "</a>";
      slots.push(html);
      return "\x00" + (slots.length - 1) + "\x01";
    });

    // Split on placeholders so emphasis/escaping only touches literal text.
    const parts = text.split(/(\x00\d+\x01)/);
    let out = "";
    for (const part of parts) {
      const m = /^\x00(\d+)\x01$/.exec(part);
      if (m) { out += slots[Number(m[1])]; continue; }
      out += emphasize(part);
    }
    return out;
  }

  // Bold then italic, over already-code/link-extracted text. Everything not
  // part of a marker is escaped. **strong**/__strong__, *em*/_em_.
  //
  // Underscores follow GFM's intraword rule: `_` is a delimiter ONLY at a word
  // boundary, so identifiers like message_queue_consumer and interaction_history
  // are left literal. Asterisks may be intraword (needed for **bold**).
  const isWord = (c) => c != null && /[A-Za-z0-9]/.test(c);
  function emphasize(s) {
    let out = "";
    let i = 0;
    while (i < s.length) {
      const two = s.slice(i, i + 2);
      if (two === "**" || two === "__") {
        const underscore = two === "__";
        if (!underscore || !isWord(s[i - 1])) {           // open flanking
          const close = s.indexOf(two, i + 2);
          if (close > i + 1 && (!underscore || !isWord(s[close + 2]))) {  // close flanking
            out += "<strong>" + emphasize(s.slice(i + 2, close)) + "</strong>";
            i = close + 2;
            continue;
          }
        }
      }
      const ch = s[i];
      if (ch === "*" || ch === "_") {
        const underscore = ch === "_";
        if (!underscore || !isWord(s[i - 1])) {           // open flanking
          const close = s.indexOf(ch, i + 1);
          if (close > i + 1 && (!underscore || !isWord(s[close + 1]))) {  // close flanking
            out += "<em>" + emphasize(s.slice(i + 1, close)) + "</em>";
            i = close + 1;
            continue;
          }
        }
      }
      out += escapeHtml(ch);
      i += 1;
    }
    return out;
  }

  /* ---------- block ---------- */

  const RE = {
    fence: /^(```+|~~~+)\s*(\S*)\s*$/,
    heading: /^(#{1,6})\s+(.*)$/,
    hr: /^ {0,3}([-*_])( *\1){2,} *$/,
    quote: /^ {0,3}> ?(.*)$/,
    ul: /^(\s*)[-*+]\s+(.*)$/,
    ol: /^(\s*)(\d+)[.)]\s+(.*)$/,
    tableSep: /^ *\|?[ :]*-+[ :|-]*\|?[ :-]*$/,
    tableRow: /\|/,
  };

  function splitRow(line) {
    let s = line.trim();
    if (s.startsWith("|")) s = s.slice(1);
    if (s.endsWith("|")) s = s.slice(0, -1);
    // split on unescaped pipes
    return s.split(/(?<!\\)\|/).map(function (c) { return c.replace(/\\\|/g, "|").trim(); });
  }

  function listMatch(line) {
    const ol = RE.ol.exec(line);
    if (ol) return { ordered: true, indent: ol[1].length, num: parseInt(ol[2], 10), text: ol[3] };
    const ul = RE.ul.exec(line);
    if (ul) return { ordered: false, indent: ul[1].length, num: 1, text: ul[2] };
    return null;
  }

  // Parse a list starting at lines[start]. Handles: loose lists (blank lines
  // between items — real GitHub issue bodies use them), the ordered start
  // number (a list beginning at "2." renders with start="2"), lazy
  // continuation lines, and nested sub-lists by indentation. Returns
  // { html, next }.
  function parseList(lines, start) {
    const first = listMatch(lines[start]);
    const ordered = first.ordered;
    const base = first.indent;
    const tag = ordered ? "ol" : "ul";
    const items = [];   // { parts: [text…], nested: html }
    let i = start;

    while (i < lines.length) {
      const line = lines[i];
      const m = listMatch(line);

      if (m && m.ordered === ordered && m.indent === base) {
        items.push({ parts: [m.text], nested: "" });
        i += 1;
        continue;
      }
      if (m && m.indent > base && items.length) {         // nested sub-list
        const sub = parseList(lines, i);
        items[items.length - 1].nested += sub.html;
        i = sub.next;
        continue;
      }
      if (/^\s*$/.test(line)) {                            // blank: loose-list?
        let j = i + 1;
        while (j < lines.length && /^\s*$/.test(lines[j])) j += 1;
        if (j < lines.length) {
          const n = listMatch(lines[j]);
          const indented = /^\s/.test(lines[j]) &&
            (lines[j].match(/^\s*/)[0].length > base);
          if ((n && n.ordered === ordered && n.indent === base) ||
              (n && n.indent > base) || indented) { i = j; continue; }
        }
        break;                                             // list ends
      }
      if (items.length && !m) {                            // lazy continuation
        items[items.length - 1].parts.push(line.trim());
        i += 1;
        continue;
      }
      break;
    }

    const startAttr = (ordered && first.num !== 1) ? ' start="' + first.num + '"' : "";
    let html = "<" + tag + startAttr + ">";
    for (const item of items)
      html += "<li>" + renderInline(item.parts.join(" ")) + item.nested + "</li>";
    html += "</" + tag + ">";
    return { html: html, next: i };
  }

  function renderMarkdown(src) {
    const lines = String(src == null ? "" : src).replace(/\r\n?/g, "\n").split("\n");
    let out = "";
    let i = 0;
    let para = [];

    function flushPara() {
      if (!para.length) return;
      out += "<p>" + para.map(renderInline).join("<br>") + "</p>";
      para = [];
    }

    while (i < lines.length) {
      const line = lines[i];

      // blank line -> paragraph break
      if (/^\s*$/.test(line)) { flushPara(); i += 1; continue; }

      // fenced code block
      const f = RE.fence.exec(line);
      if (f) {
        flushPara();
        const fence = f[1][0];
        const buf = [];
        i += 1;
        while (i < lines.length && !new RegExp("^(" + fence + "{" + f[1].length + ",})\\s*$").test(lines[i])) {
          buf.push(lines[i]); i += 1;
        }
        i += 1; // consume closing fence (or EOF)
        out += "<pre class=\"md-code\"><code>" + escapeHtml(buf.join("\n")) + "</code></pre>";
        continue;
      }

      // heading
      const h = RE.heading.exec(line);
      if (h) {
        flushPara();
        const level = h[1].length;
        out += "<h" + level + ">" + renderInline(h[2]) + "</h" + level + ">";
        i += 1; continue;
      }

      // thematic break
      if (RE.hr.test(line)) { flushPara(); out += "<hr>"; i += 1; continue; }

      // table: a row containing a pipe, followed by a separator row
      if (RE.tableRow.test(line) && i + 1 < lines.length && RE.tableSep.test(lines[i + 1])) {
        flushPara();
        const header = splitRow(line);
        i += 2;
        let t = "<table class=\"md-table\"><thead><tr>";
        for (const c of header) t += "<th>" + renderInline(c) + "</th>";
        t += "</tr></thead><tbody>";
        while (i < lines.length && RE.tableRow.test(lines[i]) && !/^\s*$/.test(lines[i])) {
          const cells = splitRow(lines[i]);
          t += "<tr>";
          for (let c = 0; c < header.length; c++)
            t += "<td>" + renderInline(cells[c] || "") + "</td>";
          t += "</tr>";
          i += 1;
        }
        t += "</tbody></table>";
        out += t; continue;
      }

      // blockquote (consecutive > lines, rendered recursively)
      if (RE.quote.test(line)) {
        flushPara();
        const buf = [];
        while (i < lines.length && RE.quote.test(lines[i])) {
          buf.push(RE.quote.exec(lines[i])[1]); i += 1;
        }
        out += "<blockquote>" + renderMarkdown(buf.join("\n")) + "</blockquote>";
        continue;
      }

      // lists (loose, nested, ordered-start-aware — see parseList)
      if (listMatch(line)) {
        flushPara();
        const r = parseList(lines, i);
        out += r.html; i = r.next; continue;
      }

      // paragraph text
      para.push(line);
      i += 1;
    }
    flushPara();
    return out;
  }

  global.renderMarkdown = renderMarkdown;
  // Inline-only: emphasis, code, and safe links, with NO block wrapping —
  // for short fields rendered inside a <span> (a <p> would break the span).
  global.renderMarkdownInline = renderInline;
  // Exposed for the browser test page.
  global.__md = { escapeHtml: escapeHtml, safeHref: safeHref, renderInline: renderInline };
})(typeof window !== "undefined" ? window : this);
