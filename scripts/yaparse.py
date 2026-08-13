#!/usr/bin/env python3
"""yaparse.py — parse Yandex Search API v2 XML (FLAT or DEEP grouping) into compact output.

Reads the decoded XML payload on stdin. Companion of yandex-search.sh.

Modes (--out): text (default) — header + numbered "url | title" + passages;
               json — {"found": ..., "docs": [...]};
               urls — one URL per line (cheapest for token budgets).

Design notes (verified against live responses, see references/verified.md):
  - iterates .//doc, so FLAT and DEEP groupings both work;
  - mixed content with <hlword> is flattened via itertext();
  - url: doc/url → fallback doc/saved-copy-url → fallback doc@id;
  - found: element <found priority="all"> under <response>, else first <found>, else n/a;
  - <error code="15"> ("nothing found") is a NORMAL empty result → found=0, exit 0.

Exit codes: 0 ok (incl. empty result), 3 API error inside XML, 5 XML unparseable.
"""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET

WS = re.compile(r"\s+")


def text_of(el):
    """Flatten mixed content (e.g. <title>foo <hlword>bar</hlword></title>)."""
    if el is None:
        return ""
    return WS.sub(" ", "".join(el.itertext())).strip()


def truncate(s, n):
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", choices=["text", "json", "urls"], default="text")
    ap.add_argument("--passage-chars", type=int, default=220)
    ap.add_argument("--meta", default="", help="free-form string appended to the text header")
    args = ap.parse_args()

    data = sys.stdin.buffer.read()
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        sys.stderr.write(f"[error] XML parse failed: {e}\n--- first 500 chars ---\n")
        sys.stderr.write(data[:500].decode("utf-8", "replace") + "\n")
        sys.stderr.write("[hint] rerun with --raw to inspect the raw payload\n")
        sys.exit(5)

    err = root.find(".//error")
    if err is not None:
        code = err.get("code", "")
        if code == "15":  # "Искомая комбинация слов нигде не встречается" — normal empty result
            emit(args, "0", [])
            sys.exit(0)
        sys.stderr.write(f"[error] API error code={code or '?'}: {text_of(err)}\n")
        sys.exit(3)

    resp = root.find(".//response")
    found_els = (resp.findall("found") if resp is not None else []) or root.findall(".//found")
    found = None
    for f in found_els:
        if f.get("priority") == "all":
            found = f.text
            break
    if found is None and found_els:
        found = found_els[0].text
    found = (found or "n/a").strip()

    docs = []
    for doc in root.iter("doc"):
        url_el = doc.find("url")
        url = (url_el.text or "").strip() if url_el is not None and url_el.text else ""
        if not url:
            sc = doc.find("saved-copy-url")
            url = (sc.text or "").strip() if sc is not None and sc.text else ""
        if not url:
            url = doc.get("id", "")
        docs.append(
            {
                "url": url,
                "title": text_of(doc.find("title")),
                "domain": text_of(doc.find("domain")),
                "modtime": text_of(doc.find("modtime")),
                "headline": text_of(doc.find("headline")),
                "passages": [text_of(p) for p in doc.findall("./passages/passage")],
            }
        )

    emit(args, found, docs)


def emit(args, found, docs):
    if args.out == "urls":
        for d in docs:
            print(d["url"])
    elif args.out == "json":
        out = {"found": found, "docs": docs}
        if args.meta:
            out["meta"] = args.meta
        print(json.dumps(out, ensure_ascii=False))
    else:
        header = f"found={found} docs={len(docs)}"
        if args.meta:
            header += f" {args.meta}"
        print(header)
        for i, d in enumerate(docs, 1):
            title = d["title"] or "(no title)"
            print(f"{i:3d}. {d['url']} | {title}")
            texts = d["passages"] or ([d["headline"]] if d["headline"] else [])
            for p in texts:
                if p:
                    print(f"     {truncate(p, args.passage_chars)}")


if __name__ == "__main__":
    main()
