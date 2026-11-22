#!/usr/bin/env python3
"""Copy the City of Berkeley council agenda table into meetings.json.

Runs from a GitHub Action on a schedule. Standard library only.
Usage: python scripts/fetch_meetings.py [output_path] [--from-file page.html]
If the page can't be read or no meetings are found, the existing
meetings.json is left untouched and the script exits with an error.
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

SOURCE = "https://berkeleyca.gov/your-government/city-council/city-council-agendas"
MEETING_HREF = re.compile(r"/city-council-agendas/city-council-(\d{4}-\d{2}-\d{2})(?:-\d+)?/?$")
WHEN = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s*-\s*(\d{1,2}:\d{2}\s*[ap]m)", re.I)


class RowParser(HTMLParser):
    """Collects each table row's text and links."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.row, self.link = [], None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self.row = {"text": "", "links": []}
        elif tag == "a" and self.row is not None and a.get("href"):
            self.link = {"href": a["href"], "title": a.get("title") or "", "text": ""}

    def handle_endtag(self, tag):
        if tag == "a" and self.link is not None:
            self.link["text"] = self.link["text"].strip()
            self.row["links"].append(self.link)
            self.link = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.row is not None:
            self.row["text"] += " " + data
        if self.link is not None:
            self.link["text"] += data


def absolute(href):
    return href if href.startswith("http") else "https://berkeleyca.gov" + href


def parse(html):
    p = RowParser()
    p.feed(html)
    meetings = []
    for row in p.rows:
        page = next((l for l in row["links"] if MEETING_HREF.search(l["href"])), None)
        when = WHEN.search(" ".join(row["text"].split()))
        if not page or not when:
            continue
        mm, dd, yyyy, time = when.groups()
        kind = page["text"].split(" - ", 1)[1].strip() if " - " in page["text"] else "Meeting"
        m = {
            "date": f"{yyyy}-{mm}-{dd}",
            "time": " ".join(time.lower().split()),
            "type": kind,
            "page": absolute(page["href"]),
        }
        for l in row["links"]:
            href, title = absolute(l["href"]), l["title"].lower()
            if title.startswith("html agenda"):
                m["agenda"] = href
            elif title.startswith("video stream"):
                m["video"] = href
            elif href.lower().endswith(".pdf"):
                name = href.lower()
                if "annotated" in name:
                    m["annotated"] = href
                elif "packet" in name:
                    m["packet"] = href
                else:
                    m.setdefault("agendaPdf", href)
        meetings.append(m)
    # newest first, de-duplicated by meeting page
    seen, out = set(), []
    for m in sorted(meetings, key=lambda m: (m["date"], to24(m["time"])), reverse=True):
        if m["page"] not in seen:
            seen.add(m["page"])
            out.append(m)
    return out


def to24(t):
    return datetime.strptime(t.upper(), "%I:%M %p").strftime("%H:%M")


def main():
    args = sys.argv[1:]
    out_path = "meetings.json"
    html = None
    if "--from-file" in args:
        i = args.index("--from-file")
        html = open(args[i + 1], encoding="utf-8").read()
        del args[i:i + 2]
    if args:
        out_path = args[0]
    if html is None:
        req = urllib.request.Request(SOURCE, headers={
            "User-Agent": "District5-site-agenda-sync (+https://berkeleydistrictfive.com)"})
        with urllib.request.urlopen(req, timeout=60) as r:
            html = r.read().decode("utf-8", "replace")

    meetings = parse(html)
    if not meetings:
        sys.exit("No meetings found on the city page; meetings.json left unchanged.")

    data = {
        "source": SOURCE,
        "checked": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "meetings": meetings,
    }
    # Only rewrite the file when the meetings themselves changed, so the
    # Action doesn't make a commit every run just for a new timestamp.
    try:
        old = json.load(open(out_path, encoding="utf-8"))
        if old.get("meetings") == meetings:
            print(f"No change ({len(meetings)} meetings).")
            return
    except (OSError, ValueError):
        pass
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(f"Wrote {len(meetings)} meetings to {out_path}.")
    embed_snapshot(data)


def embed_snapshot(data, page="index.html"):
    """Keep the backup copy inside index.html in step with meetings.json."""
    try:
        html = open(page, encoding="utf-8").read()
    except OSError:
        return
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    new = re.sub(r'(<script type="application/json" id="snapshot">).*?(</script>)',
                 lambda m: m.group(1) + blob + m.group(2), html, count=1, flags=re.S)
    if new != html:
        open(page, "w", encoding="utf-8").write(new)


if __name__ == "__main__":
    main()
