# -*- coding: utf-8 -*-
"""
心理学 論文執筆アプリ（全体版 / ローカル・追加インストール不要）

対象セクション：表題・要約・問題と目的①〜⑥・方法①〜⑥・結果①〜③・考察①〜⑤・引用文献(自動)
- 各セクションに「書くこと」＋クリックで挿入できる言い回しチップ＋記入欄
- 文献検索：CiNii Research（和文）/ CrossRef（欧文）から取り込み、APA式(心理学)で自動整形
- 「本文に挿入」で（著者, 年）を該当欄へ差し込み
- 入力はブラウザに自動保存（localStorage）／ 本文＋文献をコピー・Markdown/テキストで保存

使い方:  ターミナルで  python3 app.py   を実行（または「起動.command」をダブルクリック）。
"""
import base64
import csv
import html
import io
import json
import re
import sys
import threading
import webbrowser
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CONTACT_EMAIL = "example@example.com"  # CrossRefへの礼儀としての連絡先（任意）

APP_VERSION = "1.0.0"
# 自動更新チェック用URL（任意）。先生がJSONを置いたURLを入れると、
# 起動時に新版の有無を知らせます（コードは自動では置き換えません＝安全）。
# 例: "https://raw.githubusercontent.com/<ユーザー>/<リポジトリ>/main/latest.json"
# JSONの形式: {"version":"1.1.0","note":"説明","download":"https://…/app.py の入手先"}
UPDATE_URL = ""


# ----------------------------------------------------------------------
#  CiNii Research OpenSearch 取り込み
# ----------------------------------------------------------------------
def fetch_cinii(q, count):
    url = ("https://cir.nii.ac.jp/opensearch/all?"
           + urllib.parse.urlencode({"q": q, "count": count, "format": "json"}))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 PsychPaperApp"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    out = []
    for it in data.get("items", []):
        creators = it.get("dc:creator", [])
        if isinstance(creators, str):
            creators = [creators]
        authors = [parse_jp_author(c) for c in creators]
        year = extract_year(it.get("prism:publicationDate") or it.get("dc:date") or "")
        doi = ""
        for ident in as_list(it.get("dc:identifier")):
            if isinstance(ident, dict) and ident.get("@type") == "cir:DOI":
                doi = ident.get("@value", "")
        link = it.get("link", {})
        url_item = link.get("@id", "") if isinstance(link, dict) else ""
        out.append({
            "source": "CiNii",
            "authors": authors,
            "title": clean(it.get("title", "")),
            "journal": clean(it.get("prism:publicationName", "")),
            "publisher": clean(it.get("dc:publisher", "")),
            "year": year,
            "volume": num(it.get("prism:volume")),
            "number": num(it.get("prism:number")),
            "spage": num(it.get("prism:startingPage")),
            "epage": num(it.get("prism:endingPage")),
            "doi": doi,
            "type": it.get("dc:type", ""),
            "url": url_item,
        })
    return out


def is_ja(s):
    return bool(re.search(r"[぀-ヿ㐀-鿿一-龥]", s or ""))


def parse_jp_author(s):
    s = (s or "").strip()
    if "," in s:  # "諸井, 克英"  /  "Perlman, D."
        fam, _, giv = s.partition(",")
        return {"family": fam.strip(), "given": giv.strip(), "raw": s}
    if is_ja(s) and (" " in s or "　" in s):  # "村上 浩生" → 姓/名 に分割
        parts = s.split()
        return {"family": parts[0], "given": "".join(parts[1:]), "raw": s}
    return {"family": s, "given": "", "raw": s}


# ----------------------------------------------------------------------
#  CrossRef 取り込み（欧文・国際）
# ----------------------------------------------------------------------
def fetch_crossref(q, count):
    url = ("https://api.crossref.org/works?"
           + urllib.parse.urlencode({
               "query": q, "rows": count,
               "select": "title,author,container-title,issued,volume,issue,page,DOI,type,publisher",
           }))
    req = urllib.request.Request(
        url, headers={"User-Agent": "PsychPaperApp/1.0 (mailto:%s)" % CONTACT_EMAIL})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    out = []
    for it in data.get("message", {}).get("items", []):
        authors = []
        for a in it.get("author", []):
            fam = a.get("family", "") or ""
            giv = a.get("given", "") or ""
            authors.append({"family": fam, "given": giv,
                            "raw": (fam + " " + giv).strip()})
        year = ""
        parts = (it.get("issued", {}) or {}).get("date-parts", [[None]])
        if parts and parts[0] and parts[0][0]:
            year = str(parts[0][0])
        page = num(it.get("page"))
        spage, epage = "", ""
        if "-" in page:
            spage, _, epage = page.partition("-")
        else:
            spage = page
        out.append({
            "source": "CrossRef",
            "authors": authors,
            "title": clean(first(it.get("title", []))),
            "journal": clean(first(it.get("container-title", []))),
            "publisher": clean(it.get("publisher", "")),
            "year": year,
            "volume": num(it.get("volume")),
            "number": num(it.get("issue")),
            "spage": spage.strip(),
            "epage": epage.strip(),
            "doi": it.get("DOI", "") or "",
            "type": it.get("type", ""),
            "url": ("https://doi.org/" + it["DOI"]) if it.get("DOI") else "",
        })
    return out


# ----------------------------------------------------------------------
#  helpers
# ----------------------------------------------------------------------
def as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def first(x):
    x = as_list(x)
    return x[0] if x else ""


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(s or "").strip())


def num(v):
    v = str(v or "").strip()
    if v.lower() in ("n/a", "n.a.", "na", "-", "null", "none", ""):
        return ""
    return v


def extract_year(s):
    m = re.search(r"(\d{4})", s or "")
    return m.group(1) if m else ""


# ----------------------------------------------------------------------
#  図表（Excel / CSV）の読み込み — Python標準機能のみ
# ----------------------------------------------------------------------
def col_index(ref):
    m = re.match(r"([A-Za-z]+)", ref or "")
    if not m:
        return None
    idx = 0
    for ch in m.group(1).upper():
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def parse_ref(a1):
    m = re.match(r"([A-Za-z]+)(\d+)", a1 or "")
    if not m:
        return None
    return int(m.group(2)) - 1, col_index(m.group(1))  # (row, col) 0-indexed


def parse_csv(data, delim=","):
    text = data.decode("utf-8-sig", errors="replace")
    return [row for row in csv.reader(io.StringIO(text), delimiter=delim)]


def parse_xlsx(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    names = z.namelist()
    shared = []
    if "xl/sharedStrings.xml" in names:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall(NS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(NS + "t")))
    sheet = "xl/worksheets/sheet1.xml"
    if sheet not in names:
        ws = sorted(n for n in names
                    if n.startswith("xl/worksheets/") and n.endswith(".xml"))
        if not ws:
            return []
        sheet = ws[0]
    root = ET.fromstring(z.read(sheet))
    rows = []
    for row in root.iter(NS + "row"):
        cells = {}
        auto = 0
        for c in row.findall(NS + "c"):
            ci = col_index(c.get("r"))
            if ci is None:
                ci = auto
            auto = ci + 1
            t = c.get("t")
            v = c.find(NS + "v")
            val = ""
            if t == "s" and v is not None:
                try:
                    val = shared[int(v.text)]
                except (ValueError, IndexError):
                    val = ""
            elif t == "inlineStr":
                is_ = c.find(NS + "is")
                if is_ is not None:
                    val = "".join(x.text or "" for x in is_.iter(NS + "t"))
            elif v is not None:
                val = v.text or ""
            cells[ci] = val
        rows.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
    maxw = max((len(r) for r in rows), default=0)
    rows = [r + [""] * (maxw - len(r)) for r in rows]
    while rows and all(x == "" for x in rows[-1]):
        rows.pop()
    merges = []
    mc = root.find(NS + "mergeCells")
    if mc is not None:
        for m in mc.findall(NS + "mergeCell"):
            ref = m.get("ref", "")
            if ":" in ref:
                a, b = ref.split(":", 1)
                pa, pb = parse_ref(a), parse_ref(b)
                if pa and pb:
                    merges.append({"r1": pa[0], "c1": pa[1], "r2": pb[0], "c2": pb[1]})
    return rows, merges


# ----------------------------------------------------------------------
#  .docx 生成 — Python標準機能のみ（画像・表・セル結合対応）
# ----------------------------------------------------------------------
def img_size(data, mime):
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        if data[:2] == b"\xff\xd8":  # JPEG
            i = 2
            n = len(data)
            while i < n - 9:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3):
                    h = int.from_bytes(data[i + 5:i + 7], "big")
                    w = int.from_bytes(data[i + 7:i + 9], "big")
                    return w, h
                seg = int.from_bytes(data[i + 2:i + 4], "big")
                i += 2 + seg
    except Exception:  # noqa
        pass
    return 800, 600


def _xesc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


FONT_RPR = ('<w:rFonts w:ascii="Yu Gothic" w:eastAsia="Yu Gothic" '
            'w:hAnsi="Yu Gothic" w:cs="Yu Gothic"/>')


def build_docx(model):
    blocks = model.get("blocks", [])
    media = []   # (filename, bytes)
    rels = []    # (rid, target)
    counter = [0]
    body = []

    def run(text, bold=False, sz=21):
        rpr = FONT_RPR + ("<w:b/>" if bold else "")
        rpr += '<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (sz, sz)
        return ('<w:r><w:rPr>%s</w:rPr><w:t xml:space="preserve">%s</w:t></w:r>'
                % (rpr, _xesc(text)))

    def para(text, bold=False, sz=21, align=None, before=0, after=60):
        ppr = '<w:spacing w:before="%d" w:after="%d"/>' % (before, after)
        if align:
            ppr += '<w:jc w:val="%s"/>' % align
        return '<w:p><w:pPr>%s</w:pPr>%s</w:p>' % (ppr, run(text, bold, sz))

    def para_multi(text, sz=21):
        parts = (text or "").split("\n")
        return "".join(para(p, sz=sz) for p in parts)

    def add_image(dataurl):
        if not dataurl or "base64," not in dataurl:
            return para("（画像を読み込めませんでした）")
        head, b64 = dataurl.split("base64,", 1)
        try:
            raw = base64.b64decode(b64)
        except Exception:  # noqa
            return para("（画像を読み込めませんでした）")
        ext = "png" if "image/png" in head else "jpg"
        mime = "png" if ext == "png" else "jpeg"
        w, h = img_size(raw, mime)
        counter[0] += 1
        n = counter[0]
        rid = "rIdImg%d" % n
        fname = "image%d.%s" % (n, ext)
        media.append((fname, raw))
        rels.append((rid, "media/" + fname))
        cx = min(5400000, int(w * 9525))
        cy = int(cx * h / w) if w else int(h * 9525)
        return (
            '<w:p><w:pPr><w:spacing w:before="80" w:after="40"/><w:jc w:val="center"/></w:pPr>'
            '<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
            '<wp:extent cx="%d" cy="%d"/><wp:effectExtent l="0" t="0" r="0" b="0"/>'
            '<wp:docPr id="%d" name="image%d"/>'
            '<wp:cNvGraphicFramePr><a:graphicFrameLocks '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/>'
            '</wp:cNvGraphicFramePr>'
            '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:nvPicPr><pic:cNvPr id="%d" name="image%d"/><pic:cNvPicPr/></pic:nvPicPr>'
            '<pic:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
        ) % (cx, cy, n, n, n, n, rid, cx, cy)

    def add_table(blk):
        rows = blk.get("rows", [])
        merges = blk.get("merges", []) or []
        try:
            header_rows = int(blk.get("headerRows", 1) or 0)
        except (ValueError, TypeError):
            header_rows = 1
        ncols = max((len(r) for r in rows), default=0)
        if ncols == 0:
            return ""
        total = 9026
        colw = max(1, int(total / ncols))
        grid = "".join('<w:gridCol w:w="%d"/>' % colw for _ in range(ncols))
        omit, info = set(), {}
        for m in merges:
            r1, c1 = m["r1"], m["c1"]
            if c1 >= ncols or r1 >= len(rows):
                continue
            c2 = min(m["c2"], ncols - 1)
            r2 = min(m["r2"], len(rows) - 1)
            span = c2 - c1 + 1
            info[(r1, c1)] = {"span": span, "v": ("restart" if r2 > r1 else None)}
            for c in range(c1 + 1, c2 + 1):
                omit.add((r1, c))
            for r in range(r1 + 1, r2 + 1):
                info[(r, c1)] = {"span": span, "v": "continue"}
                for c in range(c1 + 1, c2 + 1):
                    omit.add((r, c))
        trs = []
        for ri, row in enumerate(rows):
            tcs = []
            for ci in range(ncols):
                if (ri, ci) in omit:
                    continue
                meta = info.get((ri, ci))
                span = meta["span"] if meta else 1
                tcpr = '<w:tcW w:w="%d" w:type="dxa"/>' % (colw * span)
                if span > 1:
                    tcpr += '<w:gridSpan w:val="%d"/>' % span
                if meta and meta["v"] == "restart":
                    tcpr += '<w:vMerge w:val="restart"/>'
                if meta and meta["v"] == "continue":
                    tcpr += '<w:vMerge/>'
                is_header = ri < header_rows
                if is_header:
                    tcpr += '<w:shd w:val="clear" w:color="auto" w:fill="DCE9F7"/>'
                val = "" if (meta and meta["v"] == "continue") else (row[ci] if ci < len(row) else "")
                cell = ('<w:p><w:pPr><w:spacing w:after="0"/></w:pPr>%s</w:p>'
                        % run(val, bold=is_header, sz=20))
                tcs.append('<w:tc><w:tcPr>%s</w:tcPr>%s</w:tc>' % (tcpr, cell))
            trs.append("<w:tr>%s</w:tr>" % "".join(tcs))
        borders = ("<w:tblBorders>" + "".join(
            '<w:%s w:val="single" w:sz="4" w:space="0" w:color="999999"/>' % s
            for s in ["top", "left", "bottom", "right", "insideH", "insideV"]) + "</w:tblBorders>")
        return ('<w:tbl><w:tblPr><w:tblW w:w="%d" w:type="dxa"/>%s</w:tblPr>'
                '<w:tblGrid>%s</w:tblGrid>%s</w:tbl>' % (total, borders, grid, "".join(trs)))

    for blk in blocks:
        t = blk.get("type")
        if t == "title":
            body.append(para(blk.get("text") or "（無題）", bold=True, sz=32, align="center", after=200))
        elif t == "heading":
            lvl = blk.get("level", 1)
            body.append(para(blk.get("text", ""), bold=True, sz=(28 if lvl == 1 else 24),
                             before=240, after=80))
        elif t == "para":
            body.append(para_multi(blk.get("text", "")))
        elif t == "table":
            cap = blk.get("label", "") + ("　" + blk["caption"] if blk.get("caption") else "")
            body.append(para(cap, bold=True, sz=20, before=140, after=40))
            body.append(add_table(blk))
            body.append(para("", after=60))
        elif t == "image":
            body.append(add_image(blk.get("img", "")))
            cap = blk.get("label", "") + ("　" + blk["caption"] if blk.get("caption") else "")
            body.append(para(cap, bold=True, sz=20, align="center", after=140))

    sectpr = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
              '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
              'w:header="720" w:footer="720" w:gutter="0"/></w:sectPr>')
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<w:body>%s%s</w:body></w:document>' % ("".join(body), sectpr))

    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" '
                 'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
                 'Target="word/document.xml"/></Relationships>')
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                + "".join('<Relationship Id="%s" '
                          'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                          'Target="%s"/>' % (rid, tgt) for rid, tgt in rels)
                + "</Relationships>")
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        '<Default Extension="jpg" ContentType="image/jpeg"/>'
        '<Default Extension="jpeg" ContentType="image/jpeg"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("word/document.xml", document)
        if rels:
            z.writestr("word/_rels/document.xml.rels", doc_rels)
        for fname, raw in media:
            z.writestr("word/media/" + fname, raw)
    return buf.getvalue()


# ----------------------------------------------------------------------
#  HTTP server
# ----------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self._send(200, HTML, "text/html; charset=utf-8")
            return
        if parsed.path == "/api/update-check":
            result = {"current": APP_VERSION, "latest": None, "note": "", "download": ""}
            if UPDATE_URL:
                try:
                    req = urllib.request.Request(UPDATE_URL, headers={"User-Agent": "PsychPaperApp"})
                    with urllib.request.urlopen(req, timeout=10) as r:
                        info = json.loads(r.read().decode("utf-8"))
                    result["latest"] = str(info.get("version", ""))
                    result["note"] = info.get("note", "")
                    result["download"] = info.get("download", "")
                except Exception as e:  # noqa
                    result["error"] = str(e)
            self._send(200, json.dumps(result, ensure_ascii=False))
            return
        if parsed.path == "/api/search":
            qs = urllib.parse.parse_qs(parsed.query)
            q = (qs.get("q", [""])[0]).strip()
            source = qs.get("source", ["cinii"])[0]
            try:
                count = max(1, min(50, int(qs.get("count", ["20"])[0])))
            except ValueError:
                count = 20
            if not q:
                self._send(200, json.dumps({"items": []}))
                return
            try:
                items = fetch_crossref(q, count) if source == "crossref" else fetch_cinii(q, count)
                self._send(200, json.dumps({"items": items}, ensure_ascii=False))
            except Exception as e:  # noqa
                self._send(200, json.dumps({"error": str(e)}, ensure_ascii=False))
            return
        self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/table":
            qs = urllib.parse.parse_qs(parsed.query)
            name = (qs.get("name", [""])[0]).lower()
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > 16 * 1024 * 1024:
                self._send(200, json.dumps({"error": "ファイルサイズが不正です（16MBまで）。"}))
                return
            data = self.rfile.read(length)
            try:
                merges = []
                if name.endswith(".csv"):
                    rows = parse_csv(data, ",")
                elif name.endswith(".tsv"):
                    rows = parse_csv(data, "\t")
                elif name.endswith(".xlsx") or name.endswith(".xlsm"):
                    rows, merges = parse_xlsx(data)
                else:
                    self._send(200, json.dumps({"error": "対応形式は .xlsx / .csv です。"}))
                    return
                rows = [r[:26] for r in rows[:100]]  # 表示上の上限
                merges = [m for m in merges if m["r1"] < 100 and m["c1"] < 26]
                for m in merges:
                    m["r2"] = min(m["r2"], 99)
                    m["c2"] = min(m["c2"], 25)
                self._send(200, json.dumps({"rows": rows, "merges": merges}, ensure_ascii=False))
            except Exception as e:  # noqa
                self._send(200, json.dumps({"error": str(e)}, ensure_ascii=False))
            return
        if parsed.path == "/api/docx":
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            data = self.rfile.read(length) if length > 0 else b"{}"
            try:
                model = json.loads(data.decode("utf-8"))
                blob = build_docx(model)
                self.send_response(200)
                self.send_header("Content-Type",
                                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
                self.send_header("Content-Disposition", "attachment; filename=paper.docx")
                self.send_header("Content-Length", str(len(blob)))
                self.end_headers()
                self.wfile.write(blob)
            except Exception as e:  # noqa
                self._send(200, json.dumps({"error": str(e)}, ensure_ascii=False))
            return
        self._send(404, json.dumps({"error": "not found"}))


HTML = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>心理学 論文執筆アプリ（全体版）</title>
<style>
:root{
  --blue:#2e6da4; --blue-d:#1f5c99; --ex:#1f6feb; --bg:#f4f7fb;
  --line:#d6dee7; --frame:#eef3fa; --ok:#2e8b57; --warn:#b25900; --gray:#667;
}
*{box-sizing:border-box}
body{margin:0;font-family:"Hiragino Sans","Yu Gothic","Meiryo",system-ui,sans-serif;
  color:#1d2733;background:var(--bg);line-height:1.7}
header{background:var(--blue);color:#fff;padding:12px 20px;position:sticky;top:0;z-index:20;
  box-shadow:0 2px 6px rgba(0,0,0,.15)}
.htop{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
header h1{font-size:17px;margin:0;font-weight:700}
header .sub{font-size:12px;color:#dce9f7}
.nav{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}
.nav button{background:rgba(255,255,255,.18);color:#fff;border:0;border-radius:14px;padding:4px 11px;font-size:12px}
.nav button:hover{background:rgba(255,255,255,.34)}
.pbar{height:6px;background:rgba(255,255,255,.25);border-radius:4px;margin-top:9px;overflow:hidden}
.pbar>i{display:block;height:100%;background:#fff;width:0;transition:width .25s}
.pnum{font-size:11.5px;color:#dce9f7;margin-top:4px}
.wrap{display:grid;grid-template-columns:1fr 380px;gap:18px;max-width:1320px;margin:18px auto;padding:0 18px}
@media(max-width:980px){.wrap{grid-template-columns:1fr}}
.group-title{font-size:16px;color:#fff;background:var(--blue);border-radius:8px;padding:8px 14px;
  margin:22px 0 12px;font-weight:700}
.group-title:first-child{margin-top:0}
.group-note{font-size:12px;color:var(--warn);margin:-6px 2px 10px}
.card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:14px;
  box-shadow:0 1px 2px rgba(0,0,0,.03);scroll-margin-top:120px}
.card h3{font-size:14.5px;color:var(--blue-d);margin:0 0 2px}
.card .role{font-size:12.5px;color:var(--gray);margin:0 0 9px}
.frames{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:9px}
.frame{background:var(--frame);border:1px solid #dce6f2;color:#24435f;border-radius:16px;
  padding:5px 11px;font-size:12px;cursor:pointer;transition:.12s}
.frame:hover{background:#e0ecfa;border-color:#b9d2ee}
textarea,input.title{width:100%;border:1px solid var(--line);border-radius:8px;padding:10px 12px;
  font-family:inherit;font-size:14px;line-height:1.8}
textarea{min-height:84px;resize:vertical}
input.title{font-size:15px;font-weight:600}
textarea:focus,input.title:focus{outline:none;border-color:var(--blue);box-shadow:0 0 0 3px rgba(46,109,164,.12)}
.tip{font-size:11.5px;color:var(--gray);margin-top:6px}
.side{position:sticky;top:150px;align-self:start}
@media(max-width:980px){.side{position:static}}
.side h2{font-size:15px;color:var(--blue-d);margin:0 0 10px}
.searchbar{display:flex;gap:6px;margin-bottom:8px}
.searchbar input[type=text]{flex:1;border:1px solid var(--line);border-radius:8px;padding:8px 10px;font-size:14px}
.srcrow{display:flex;gap:12px;align-items:center;font-size:12.5px;margin-bottom:10px;color:var(--gray)}
button{background:var(--blue);color:#fff;border:0;border-radius:8px;padding:8px 12px;font-size:13px;cursor:pointer;font-family:inherit}
button:hover{background:var(--blue-d)}
button.ghost{background:#fff;color:var(--blue);border:1px solid var(--blue)}
button.ghost:hover{background:#eef3fa}
button.sm{padding:4px 9px;font-size:12px}
button.mini{padding:2px 7px;font-size:11px}
.results{max-height:300px;overflow:auto;border:1px solid var(--line);border-radius:8px;margin-bottom:12px}
.res{padding:9px 11px;border-bottom:1px solid #eef1f5;font-size:12.5px}
.res:last-child{border-bottom:0}
.res .t{font-weight:600}
.res .m{color:var(--gray);font-size:11.5px;margin:2px 0 6px}
.badge{display:inline-block;font-size:10px;padding:1px 6px;border-radius:6px;background:#eef3fa;color:var(--blue-d);border:1px solid #dce6f2;margin-right:5px}
.reflist{list-style:none;padding:0;margin:0}
.reflist li{border:1px solid var(--line);border-radius:8px;padding:9px 11px;margin-bottom:8px;font-size:12.5px}
.reflist .row{display:flex;gap:6px;margin-top:7px;flex-wrap:wrap;align-items:center}
.intoken{font-size:11.5px;color:var(--ex);font-weight:600}
.export{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
.empty{color:var(--gray);font-size:12.5px;padding:8px 2px}
.status{font-size:12px;color:var(--gray);min-height:16px;margin-bottom:8px}
.savebar{font-size:11.5px;color:var(--ok);margin-left:6px}
.citebtn{margin-top:8px}
.popover{position:absolute;z-index:60;background:#fff;border:1px solid var(--line);border-radius:8px;
  box-shadow:0 8px 26px rgba(0,0,0,.18);max-width:380px;max-height:300px;overflow:auto;padding:6px}
.popover .pit{padding:7px 9px;border-radius:6px;cursor:pointer;font-size:12.5px}
.popover .pit:hover{background:var(--frame)}
.popover .pit .tk{color:var(--ex);font-weight:600;margin-right:6px}
.popover .empty2{padding:8px;color:var(--gray);font-size:12px;max-width:260px}
.reading{width:132px;border:1px solid var(--line);border-radius:6px;padding:3px 7px;font-size:12px;font-family:inherit}
.rlabel{font-size:11px;color:var(--gray);margin-left:4px}
.hint2{font-size:11.5px;color:var(--gray);margin:2px 0 8px}
.fig{border:1px solid var(--line);border-radius:8px;padding:9px 11px;margin-bottom:8px}
.fig .lab{font-weight:700;color:var(--blue-d);font-size:13px}
.fig img{max-width:100%;border:1px solid var(--line);border-radius:6px;margin-top:6px;display:block}
.fig .cap{width:100%;border:1px solid var(--line);border-radius:6px;padding:5px 8px;font-size:12.5px;margin-top:6px;font-family:inherit}
.minitbl{overflow:auto;margin-top:6px;max-height:190px;border:1px solid var(--line);border-radius:6px}
.minitbl table{border-collapse:collapse;font-size:11.5px}
.minitbl td{border:1px solid #e3e9f0;padding:2px 6px;white-space:nowrap}
.minitbl tr:first-child td{background:var(--frame);font-weight:600}
.fig .row{display:flex;gap:6px;margin-top:7px;flex-wrap:wrap;align-items:center}
footer{max-width:1320px;margin:0 auto 40px;padding:0 18px;color:var(--gray);font-size:11.5px}
</style>
</head>
<body>
<header>
  <div class="htop">
    <h1>心理学 論文執筆アプリ（全体版）</h1>
    <span class="sub">各セクションを順に書く → 文献をCiNii/CrossRefから取り込む → 引用に自動反映</span>
  </div>
  <div class="nav" id="nav"></div>
  <div class="pbar"><i id="pbarfill"></i></div>
  <div class="pnum" id="pnum"></div>
</header>

<div id="updbanner" style="display:none;background:#fff8e1;border-bottom:1px solid #f0d9a0;color:#7a5b00;padding:8px 20px;font-size:13px"></div>

<div class="wrap">
  <main id="sections"></main>

  <aside class="side">
    <div class="card">
      <h2>📚 文献をさがして取り込む</h2>
      <div class="srcrow">
        <label><input type="radio" name="src" value="cinii" checked> CiNii（和文）</label>
        <label><input type="radio" name="src" value="crossref"> CrossRef（欧文）</label>
      </div>
      <div class="searchbar">
        <input type="text" id="q" placeholder="例）孤独感 SNS 大学生 / loneliness social media">
        <button id="searchBtn">検索</button>
      </div>
      <div class="status" id="status"></div>
      <div class="results" id="results" style="display:none"></div>

      <h2 style="margin-top:6px">📝 引用文献リスト <span id="refcount" class="sub" style="color:var(--gray)"></span></h2>
      <div class="tip">並び順：著者姓のアルファベット／五十音順（自動）。和文は「よみ」欄に読みを入れると正確に並びます。</div>
      <ul class="reflist" id="reflist"></ul>
      <div class="empty" id="refempty">まだ文献がありません。上で検索して「文献に追加」を押してください。</div>
      <div class="export"><button class="ghost sm" id="copyRefs">引用文献リストをコピー</button></div>
    </div>

    <div class="card">
      <h2>🖼 図表を取り込む</h2>
      <div class="hint2">Excel(.xlsx)・CSVは表として、画像(PNG/JPG)は図として取り込みます。番号（表1・図1）は自動。本文欄に「表1」「図1」を挿入できます。</div>
      <div class="export">
        <button class="sm" id="addTableBtn">＋ 表を追加（Excel/CSV）</button>
        <button class="sm" id="addFigBtn">＋ 図を追加（画像）</button>
      </div>
      <input type="file" id="tableFile" accept=".xlsx,.xlsm,.csv,.tsv" style="display:none">
      <input type="file" id="figFile" accept="image/*" style="display:none">
      <div class="status" id="figstatus"></div>
      <div class="figs" id="figs"></div>
      <div class="empty" id="figempty">まだ図表がありません。</div>
    </div>

    <div class="card">
      <h2>⬇️ 書き出し</h2>
      <div class="export">
        <button class="sm" id="dlDocx">📄 Wordで保存（図表入り）</button>
        <button class="ghost sm" id="copyAll">論文全体をコピー</button>
        <button class="ghost sm" id="dlMd">Markdownで保存</button>
        <button class="ghost sm" id="dlTxt">テキストで保存</button>
      </div>
      <div class="hint2" style="margin-top:6px">Wordは「図1」「表1」と書いた場所に図表を差し込みます。表は見出し行とExcelのセル結合を反映します。</div>
      <div class="export" style="margin-top:8px">
        <button class="ghost sm" id="clearAll" style="color:#b00;border-color:#e3b7b7">すべて消去</button>
        <span class="savebar" id="savebar">自動保存: 有効</span>
      </div>
    </div>
  </aside>
</div>

<footer>
  ※ 引用文献はAPA（心理学）式で自動整形しますが、データ元により著者表記・巻号ページ等が欠けることがあります。提出前に必ず原典と所属先の様式で確認してください。
  &nbsp;/&nbsp; 検索データ提供：CiNii Research・CrossRef。
  &nbsp;/&nbsp; <span id="ver"></span> &nbsp;<a href="#" id="chkupd">更新を確認</a>
</footer>

<script>
// ---------- セクション定義（論文全体） ----------
const GROUPS = [
 {key:"title", name:"表題", sections:[
   {id:"title", single:true, title:"表題（タイトル）",
    role:"変数＋関連/効果/比較＋対象。20〜30字。",
    frames:["〇〇と△△の関連 ―― □□を対象とした検討","〇〇が△△に及ぼす影響","大学生における〇〇と△△の関係"]},
 ]},
 {key:"abstract", name:"要約", note:"※ 本文を書き終えてから最後に書くとまとめやすい。", sections:[
   {id:"abstract", title:"要約（抄録）",
    role:"背景→目的→方法→主な結果→結論を各1〜2文で。200〜400字。最後にキーワード3〜5語。",
    frames:[
     "〔背景〕近年、〇〇が問題として注目されている。",
     "〔目的〕本研究では、〇〇と△△の関連を検討することを目的とした。",
     "〔方法〕大学生N名を対象に質問紙調査を実施し、〇〇と△△を測定した。",
     "〔結果〕その結果、〇〇と△△の間に有意な正の（負の）相関がみられた（r = .〇〇, p < .05）。",
     "〔結論〕以上より、〇〇が△△と関連することが示唆された。",
     "キーワード：〇〇、△△、対象、方法"]},
 ]},
 {key:"intro", name:"問題と目的",
  note:"理想の流れ：導入→定義→類似概念との異同→先行研究→すきま→目的（②〜④を積むとテーマが必然的に導かれる）。",
  sections:[
   {id:"int1", title:"① 導入（なぜ重要か）",
    role:"なぜこのテーマが重要か。社会的・学術的な入り口を短く。",
    frames:["近年、〇〇が急速に広がり、△△への影響が懸念されている。","〇〇は、現代の□□にとって見過ごせない問題である。"]},
   {id:"int2", title:"② 中心概念の定義（出典を示して定義する）",
    role:"本研究で扱う構成概念を、提唱者・理論の出典を示して定義する。",
    frames:["〇〇とは、……と定義される（提唱者, 年）。","本研究で扱う〇〇とは、……を指す概念である。","〇〇は、□□理論の枠組みにおいて「……」として概念化されてきた（著者, 年）。"]},
   {id:"int3", title:"③ 類似概念との異同（共通点と相違点で輪郭を出す）",
    role:"似た概念を挙げ、共通点と相違点を述べて、扱う概念の輪郭を明確にする。",
    frames:["〇〇と混同されやすい概念に△△がある。両者は……という点で共通するが、〇〇が……であるのに対し、△△は……である点で区別される。","また〇〇は□□とも関連するが、□□が……を指すのに対し、〇〇は……に焦点づけられる点で異なる。","以上をふまえ、本研究では〇〇を「……」として捉える。"]},
   {id:"int4", title:"④ 先行研究の整理（他の心理学的概念との関連）",
    role:"その概念が、これまで他の心理学的概念とどう関連することが示されてきたか。",
    frames:["これまで〇〇は、△△（著者, 年）や□□（著者, 年）と関連することが示されてきた。","近年では、〇〇と◇◇の関連が検討され始めている（著者, 年）。"]},
   {id:"int5", title:"⑤ 研究のすきま（テーマが導かれる所）",
    role:"先行研究で未解明の関連・対象・文脈。②の定義から着眼が理論的に導かれるように。",
    frames:["しかし、これらの研究の多くは……に着目しており、……を検討した研究は少ない。","〇〇が……である以上（＝②の定義から）、……が〇〇に影響する可能性が理論的に想定される。"]},
   {id:"int6", title:"⑥ 本研究の目的と仮説",
    role:"②〜⑤の流れから導出した目的と、先行研究に基づく仮説。",
    frames:["そこで本研究では、……を検討することを目的とする。","〇〇を「……」と定義した上で、……ほど〇〇が高い（低い）という仮説を立てた。"]},
 ]},
 {key:"method", name:"方法",
  note:"他の人が読んで同じ研究を再現できるように、事実を具体的に（過去形で）。",
  sections:[
   {id:"met1", title:"① 参加者（対象者）", role:"誰を対象にしたか（人数・性別・年齢）。",
    frames:["□□大学の学生N名（男性〇名、女性〇名、平均年齢M歳、SD = 〇）を対象とした。"]},
   {id:"met2", title:"② 調査時期・場所", role:"いつ・どこで実施したか。",
    frames:["20〇〇年〇月に、講義時間の一部を用いて質問紙を配布した。"]},
   {id:"met3", title:"③ 材料・尺度", role:"何で測ったか（尺度名・項目数・件法・α係数）。",
    frames:["〇〇を測定するため、△△尺度（著者, 年）を用いた。","△△尺度は□項目からなり、「1．あてはまらない」〜「5．あてはまる」の5件法で回答を求めた。","本研究における△△尺度のα係数は .〇〇であった。"]},
   {id:"met4", title:"④ 手続き", role:"どんな流れで実施したか。",
    frames:["回答者に研究の趣旨を説明したうえで、質問紙に個別に回答を求めた。","回答にかかった時間はおよそ〇分であった。"]},
   {id:"met5", title:"⑤ 倫理的配慮", role:"無記名・自由参加・同意など。",
    frames:["回答は無記名とし、成績と無関係であること、いつでも中止できることを説明した。","同意が得られた者のみを分析対象とした。"]},
   {id:"met6", title:"⑥ 分析方法", role:"どの統計を、どの有意水準で使ったか。",
    frames:["分析には統計ソフト□□を用い、有意水準は5%（両側）とした。","〇〇と△△の関連を検討するため、相関分析（およびt検定）を行った。"]},
 ]},
 {key:"result", name:"結果",
  note:"数値の事実だけを書く（解釈・意見は考察へ）。記述統計→検定の順。図表は番号をつけ本文から参照。",
  sections:[
   {id:"res1", title:"① 記述統計・分析の概要", role:"まず平均・標準偏差などの事実。",
    frames:["各変数の平均値と標準偏差を表1に示す。","〇〇の平均は M = 〇〇（SD = 〇〇）であった。"]},
   {id:"res2", title:"② 主要な分析結果（相関・検定）", role:"相関・検定の結果を数値で。",
    frames:["〔相関〕〇〇と△△の間に有意な正の相関がみられた（r = .〇〇, p < .01）。","〔相関〕〇〇と△△の間に有意な相関はみられなかった（r = .〇〇, n.s.）。","〔t検定〕A群（M = 〇〇, SD = 〇〇）よりB群（M = 〇〇, SD = 〇〇）で有意に高かった（t(df) = 〇〇, p < .05）。"]},
   {id:"res3", title:"③ 図・表への言及", role:"図表に番号をつけ、本文から参照する。",
    frames:["結果を表1（図1）に示す。","図1に示すように、〇〇が増えるにつれて△△も高くなる傾向がみられた。"]},
 ]},
 {key:"discuss", name:"考察",
  note:"問題と目的の逆流れ（狭い→広い）。①まとめ→②解釈→③先行研究との比較→④限界→⑤今後・結論。新しいデータは出さない。",
  sections:[
   {id:"dis1", title:"① 本研究のまとめ", role:"目的と主な結果を再掲し、仮説は支持されたか。",
    frames:["本研究の目的は、〇〇と△△の関連を検討することであった。","その結果、〇〇と△△の間に相関がみられ、仮説は支持された（支持されなかった）。"]},
   {id:"dis2", title:"② 結果の解釈", role:"なぜその結果になったと考えられるか。",
    frames:["この結果は、〇〇が△△を高める（弱める）可能性を示唆している。","その理由として、□□が関与していると考えられる。"]},
   {id:"dis3", title:"③ 先行研究との比較", role:"一致するか／違うか、その理由。",
    frames:["この結果は、〇〇を報告した先行研究（著者, 年）と一致する。","一方で、△△を示した先行研究（著者, 年）とは異なり、□□によると考えられる。"]},
   {id:"dis4", title:"④ 本研究の限界", role:"言い切れない点・弱点を正直に。",
    frames:["本研究は相関研究であり、因果関係を明らかにすることはできない。","対象が□□に限られており、結果の一般化には注意が必要である。"]},
   {id:"dis5", title:"⑤ 今後の課題・結論", role:"次にすべきこと＋結論。",
    frames:["今後は、□□を対象に△△を加えて検討する必要がある。","以上より、本研究は〇〇と△△の関連を示した点で意義があると考えられる。"]},
 ]},
];
const ALL = GROUPS.flatMap(g=>g.sections);

const STORE_KEY = "psychPaperApp.v1";
let state = {texts:{}, refs:[], figures:[]};
let lastFocused = null;
function uid(){ return "f"+Date.now()+Math.random().toString(36).slice(2,6); }

function el(tag, cls, htmlStr){const e=document.createElement(tag); if(cls)e.className=cls; if(htmlStr!=null)e.innerHTML=htmlStr; return e;}

// ---------- 描画 ----------
function renderNav(){
  const nav=document.getElementById("nav"); nav.innerHTML="";
  GROUPS.forEach(g=>{
    const b=el("button",null,g.name);
    b.onclick=()=>{ document.getElementById("grp_"+g.key).scrollIntoView({behavior:"smooth",block:"start"}); };
    nav.appendChild(b);
  });
}

function renderSections(){
  const root=document.getElementById("sections"); root.innerHTML="";
  GROUPS.forEach(g=>{
    const gt=el("div","group-title",g.name); gt.id="grp_"+g.key; root.appendChild(gt);
    if(g.note) root.appendChild(el("div","group-note","💡 "+g.note));
    g.sections.forEach(sec=>{
      const c=el("div","card"); c.id="card_"+sec.id;
      c.appendChild(el("h3",null,sec.title));
      c.appendChild(el("p","role",sec.role));
      let field;
      if(sec.single){
        field=el("input"); field.type="text"; field.className="title";
        field.placeholder="ここに書く";
      }else{
        field=el("textarea"); field.placeholder="ここに書く（言い回しチップを押すと挿入されます）";
      }
      field.id="ta_"+sec.id;
      field.value=state.texts[sec.id]||"";
      field.addEventListener("focus",()=>{ lastFocused=sec.id; });
      field.addEventListener("input",()=>{ state.texts[sec.id]=field.value; save(); renderProgress(); });
      const fr=el("div","frames");
      sec.frames.forEach(f=>{ const b=el("span","frame","▷ "+f); b.onclick=()=>insertAtCursor(field,f); fr.appendChild(b); });
      c.appendChild(fr);
      c.appendChild(field);
      if(!sec.single){
        const cbtn=el("button","ghost sm citebtn","＋ 本文に引用を挿入（著者, 年）");
        cbtn.onclick=(ev)=>{ ev.stopPropagation(); lastFocused=sec.id; openCitePicker(field, cbtn); };
        c.appendChild(cbtn);
      }
      root.appendChild(c);
    });
  });
}

function renderProgress(){
  const done=ALL.filter(s=>(state.texts[s.id]||"").trim().length>0).length;
  const pct=Math.round(done/ALL.length*100);
  document.getElementById("pbarfill").style.width=pct+"%";
  document.getElementById("pnum").textContent=done+" / "+ALL.length+" セクション記入済み（"+pct+"%）";
}

// ---------- 挿入 ----------
function insertAtCursor(field, text){
  const s=field.selectionStart??field.value.length, e=field.selectionEnd??field.value.length;
  field.value=field.value.slice(0,s)+text+field.value.slice(e);
  const pos=s+text.length; field.focus();
  try{ field.setSelectionRange(pos,pos); }catch(_){}
  state.texts[field.id.replace("ta_","")]=field.value; save(); renderProgress();
}
function insertInText(ref){
  const id=lastFocused||ALL.find(s=>!s.single).id;
  const field=document.getElementById("ta_"+id);
  if(!field){ alert("挿入先の欄を一度クリックしてから押してください。"); return; }
  insertAtCursor(field, inTextToken(ref));
}

// セクション横の「＋本文に引用を挿入」ポップオーバー
function closePicker(){ const p=document.getElementById("citepop"); if(p)p.remove(); }
function shortRef(r){
  const a=authorsForRef(r); const t=(r.title||"");
  return a+"『"+t.slice(0,26)+(t.length>26?"…":"")+"』";
}
function openCitePicker(field, anchor){
  closePicker();
  const pop=el("div","popover"); pop.id="citepop";
  const refs=sortedRefs();
  if(refs.length===0){
    pop.appendChild(el("div","empty2","まだ文献がありません。右の「文献をさがして取り込む」で検索し、「＋ 文献に追加」を押してください。"));
  }else{
    refs.forEach(r=>{
      const it=el("div","pit");
      it.innerHTML='<span class="tk">'+escapeHtml(inTextToken(r))+'</span>'+escapeHtml(shortRef(r));
      it.onclick=()=>{ insertAtCursor(field, inTextToken(r)); closePicker(); };
      pop.appendChild(it);
    });
  }
  document.body.appendChild(pop);
  const rect=anchor.getBoundingClientRect();
  pop.style.top=(window.scrollY+rect.bottom+4)+"px";
  pop.style.left=(window.scrollX+Math.min(rect.left, window.innerWidth-400))+"px";
  setTimeout(()=>document.addEventListener("click", closePicker, {once:true}), 0);
}

// ---------- 文献の整形 ----------
function isJa(s){ return /[぀-ヿ㐀-鿿一-龥]/.test(s||""); }
function nameForRef(a){
  if(isJa(a.raw)){ return (a.family+a.given).replace(/\s+/g,"")||a.raw; }
  if(a.family){ const init=a.given? " "+a.given.split(/\s+/).map(x=>x[0]?x[0]+".":"").join(" "):""; return init?(a.family+","+init):a.family; }
  return a.raw;
}
function surname(a){ return a.family||a.raw; }
function authorsForRef(ref){
  const A=ref.authors||[]; if(A.length===0) return "著者不明";
  const ja=isJa(ref.title)||(A[0]&&isJa(A[0].raw));
  const names=A.map(nameForRef);
  if(ja) return names.join("・");
  if(names.length===1) return names[0];
  return names.slice(0,-1).join(", ")+", & "+names[names.length-1];
}
function inTextToken(ref){
  const A=ref.authors||[]; const y=ref.year||"n.d.";
  if(A.length===0) return "（著者不明, "+y+"）";
  const ja=isJa(A[0].raw)||isJa(ref.title);
  if(A.length===1) return "（"+surname(A[0])+", "+y+"）";
  if(A.length===2) return "（"+surname(A[0])+(ja?"・":" & ")+surname(A[1])+", "+y+"）";
  return "（"+surname(A[0])+(ja?"ら":" et al.")+", "+y+"）";
}
function formatReference(ref){
  const ja=isJa(ref.title);
  const y=ref.year? "（"+ref.year+"）":"（n.d.）";
  let s=authorsForRef(ref)+y+(ja?"．":". ")+ref.title+(ja?"．":". ");
  if(ref.journal){
    s+=ref.journal; let vp="";
    if(ref.volume) vp+=ref.volume;
    if(ref.number) vp+="("+ref.number+")";
    if(vp) s+=", "+vp;
    if(ref.spage) s+=", "+ref.spage+(ref.epage? "–"+ref.epage:"");
    s+=".";
  }else if(ref.publisher){ s+=ref.publisher+"."; }
  if(ref.doi) s+=" https://doi.org/"+ref.doi;
  return s;
}
function refSortKey(r){
  if(r.reading && r.reading.trim()) return r.reading.trim().toLowerCase();
  const a=r.authors&&r.authors[0];
  return (a?(a.family||a.raw):"").toLowerCase();
}
function sortedRefs(){
  return [...state.refs].sort((a,b)=>{
    const ka=refSortKey(a)+"|"+(a.year||""), kb=refSortKey(b)+"|"+(b.year||"");
    return ka.localeCompare(kb,"ja");
  });
}
function renderRefs(){
  const ul=document.getElementById("reflist"); ul.innerHTML="";
  const refs=sortedRefs();
  document.getElementById("refempty").style.display=refs.length?"none":"block";
  document.getElementById("refcount").textContent=refs.length?"（"+refs.length+"件）":"";
  refs.forEach(ref=>{
    const li=el("li");
    li.appendChild(el("div","cite",formatReference(ref)));
    const row=el("div","row");
    row.appendChild(el("span","intoken","本文引用: "+inTextToken(ref)));
    const bIns=el("button","sm","本文に挿入"); bIns.onclick=()=>insertInText(ref); row.appendChild(bIns);
    if(isJa(ref.title)||(ref.authors[0]&&isJa(ref.authors[0].raw))){
      const ri=el("input"); ri.className="reading"; ri.placeholder="よみ（例: うえにし）";
      ri.value=ref.reading||""; ri.title="並び順の基準（五十音／アルファベット）";
      ri.addEventListener("input",()=>{ ref.reading=ri.value; save(); });
      ri.addEventListener("change",()=>{ ref.reading=ri.value; save(); renderRefs(); });
      row.appendChild(el("span","rlabel","よみ:")); row.appendChild(ri);
    }
    const bDel=el("button","ghost mini","削除"); bDel.style.color="#b00"; bDel.style.borderColor="#e3b7b7";
    bDel.onclick=()=>{ state.refs=state.refs.filter(r=>r._id!==ref._id); save(); renderRefs(); }; row.appendChild(bDel);
    li.appendChild(row); ul.appendChild(li);
  });
}

// ---------- 図表 ----------
function figNumbers(){
  let f=0,t=0; const map={};
  state.figures.forEach(x=>{ if(x.kind==="table"){ t++; map[x.id]="表"+t; } else { f++; map[x.id]="図"+f; } });
  return map;
}
function renderFigures(){
  const box=document.getElementById("figs"); box.innerHTML="";
  const map=figNumbers();
  document.getElementById("figempty").style.display=state.figures.length?"none":"block";
  state.figures.forEach(fig=>{
    const d=el("div","fig");
    d.appendChild(el("div","lab",map[fig.id]));
    if(fig.kind==="table" && fig.rows){
      // 見出し行数コントロール
      const ctl=el("div","row"); ctl.style.marginTop="4px";
      ctl.appendChild(el("span","rlabel","見出し行数:"));
      const sel=el("select"); sel.className="reading"; sel.style.width="70px";
      [0,1,2,3].forEach(n=>{ const o=el("option",null,String(n)); o.value=n; if((fig.headerRows==null?1:fig.headerRows)===n)o.selected=true; sel.appendChild(o); });
      sel.addEventListener("change",()=>{ fig.headerRows=parseInt(sel.value,10); save(); renderFigures(); });
      ctl.appendChild(sel);
      if(fig.merges&&fig.merges.length) ctl.appendChild(el("span","rlabel","／ セル結合 "+fig.merges.length+"件"));
      d.appendChild(ctl);
      d.appendChild(renderMiniTable(fig));
    }else if(fig.img){
      const im=el("img"); im.src=fig.img; d.appendChild(im);
    }
    const cap=el("input"); cap.className="cap";
    cap.placeholder=(fig.kind==="table")?"表の説明（例：各変数の平均値と標準偏差）":"図の説明（例：SNS利用時間と孤独感の散布図）";
    cap.value=fig.caption||""; cap.addEventListener("input",()=>{ fig.caption=cap.value; save(); });
    d.appendChild(cap);
    const row=el("div","row");
    const ins=el("button","sm","本文に「"+map[fig.id]+"」を挿入"); ins.onclick=()=>insertFigRef(fig); row.appendChild(ins);
    const del=el("button","ghost mini","削除"); del.style.color="#b00"; del.style.borderColor="#e3b7b7";
    del.onclick=()=>{ state.figures=state.figures.filter(f=>f.id!==fig.id); save(); renderFigures(); }; row.appendChild(del);
    d.appendChild(row); box.appendChild(d);
  });
}
function mergeMaps(rows, merges){
  const omit=new Set(), info={};
  const ncols=rows.reduce((m,r)=>Math.max(m,r.length),0);
  (merges||[]).forEach(m=>{
    if(m.c1>=ncols||m.r1>=rows.length) return;
    const c2=Math.min(m.c2,ncols-1), r2=Math.min(m.r2,rows.length-1);
    const span=c2-m.c1+1;
    info[m.r1+","+m.c1]={cs:span, rs:(r2-m.r1+1)};
    for(let c=m.c1+1;c<=c2;c++) omit.add(m.r1+","+c);
    for(let r=m.r1+1;r<=r2;r++){ for(let c=m.c1;c<=c2;c++) omit.add(r+","+c); }
  });
  return {omit, info, ncols};
}
function renderMiniTable(fig){
  const wrap=el("div","minitbl"), tbl=el("table");
  const rows=fig.rows||[], hr=(fig.headerRows==null?1:fig.headerRows);
  const {omit,info,ncols}=mergeMaps(rows, fig.merges);
  rows.slice(0,40).forEach((r,ri)=>{
    const tr=el("tr");
    for(let ci=0; ci<ncols; ci++){
      if(omit.has(ri+","+ci)) continue;
      const td=el("td",null,escapeHtml(r[ci]!=null?r[ci]:""));
      const meta=info[ri+","+ci];
      if(meta){ if(meta.cs>1)td.colSpan=meta.cs; if(meta.rs>1)td.rowSpan=meta.rs; }
      if(ri<hr){ td.style.background="#dce9f7"; td.style.fontWeight="700"; }
      tr.appendChild(td);
    }
    tbl.appendChild(tr);
  });
  wrap.appendChild(tbl);
  return wrap;
}
function insertFigRef(fig){
  const label=figNumbers()[fig.id];
  const id=lastFocused||ALL.find(s=>!s.single).id;
  const field=document.getElementById("ta_"+id);
  if(!field){ alert("挿入先の欄を一度クリックしてから押してください。"); return; }
  insertAtCursor(field, label);
}
function addImageFile(file){
  const st=document.getElementById("figstatus"); st.textContent="画像を読み込み中…";
  const reader=new FileReader();
  reader.onload=e=>{
    const img=new Image();
    img.onload=()=>{
      const maxDim=1400, scale=Math.min(1, maxDim/Math.max(img.width,img.height));
      const w=Math.round(img.width*scale), h=Math.round(img.height*scale);
      const cv=document.createElement("canvas"); cv.width=w; cv.height=h;
      cv.getContext("2d").drawImage(img,0,0,w,h);
      const mime=(file.type==="image/png")?"image/png":"image/jpeg";
      const dataUrl=cv.toDataURL(mime, 0.9);
      state.figures.push({id:uid(),kind:"figure",caption:"",img:dataUrl}); save(); renderFigures();
      st.textContent="図を追加しました。";
    };
    img.onerror=()=>{ st.textContent="画像を読み込めませんでした。"; };
    img.src=e.target.result;
  };
  reader.onerror=()=>{ st.textContent="読み込みに失敗しました。"; };
  reader.readAsDataURL(file);
}
async function addTableFile(file){
  const st=document.getElementById("figstatus"); st.textContent="表を読み込み中…";
  try{
    const buf=await file.arrayBuffer();
    const r=await fetch("/api/table?name="+encodeURIComponent(file.name),{method:"POST",body:buf});
    const d=await r.json();
    if(d.error){ st.textContent="エラー: "+d.error; return; }
    if(!d.rows||!d.rows.length){ st.textContent="空の表のようです。"; return; }
    state.figures.push({id:uid(),kind:"table",caption:"",rows:d.rows,merges:d.merges||[],headerRows:1}); save(); renderFigures();
    st.textContent="表を追加しました。"+((d.merges&&d.merges.length)?"（セル結合"+d.merges.length+"件を反映）":"");
  }catch(e){ st.textContent="読み込み失敗: "+e; }
}

// ---------- 検索 ----------
async function doSearch(){
  const q=document.getElementById("q").value.trim();
  const source=document.querySelector('input[name=src]:checked').value;
  const st=document.getElementById("status"), box=document.getElementById("results");
  if(!q){ st.textContent="キーワードを入力してください。"; return; }
  st.textContent="検索中…（"+(source==="crossref"?"CrossRef":"CiNii")+"）"; box.style.display="none";
  try{
    const r=await fetch("/api/search?"+new URLSearchParams({q,source,count:"20"}));
    const d=await r.json();
    if(d.error){ st.textContent="エラー: "+d.error; return; }
    const items=d.items||[];
    st.textContent=items.length?(items.length+"件見つかりました。「文献に追加」を押してください。"):"見つかりませんでした。語を変えてみてください。";
    box.innerHTML="";
    items.forEach(it=>{
      const div=el("div","res");
      const meta=[authorsForRef(it),it.journal||it.publisher||"",it.year].filter(Boolean).join(" / ");
      div.innerHTML='<div class="t">'+escapeHtml(it.title||"（無題）")+'</div><div class="m"><span class="badge">'+it.source+'</span>'+escapeHtml(meta)+'</div>';
      const add=el("button","sm","＋ 文献に追加"); add.onclick=()=>addRef(it,add); div.appendChild(add);
      box.appendChild(div);
    });
    box.style.display="block";
  }catch(e){ st.textContent="通信に失敗しました: "+e; }
}
function addRef(it,btn){
  const key=(it.doi||"")+"|"+(it.title||"")+"|"+(it.year||"");
  if(state.refs.some(r=>r._key===key)){ if(btn){btn.textContent="追加済み"; btn.disabled=true;} return; }
  it._id="r"+Date.now()+Math.random().toString(36).slice(2,6); it._key=key;
  state.refs.push(it); save(); renderRefs();
  if(btn){ btn.textContent="✓ 追加しました"; btn.disabled=true; }
}

// ---------- 書き出し ----------
function assemble(md){
  const H=md?"# ":"■ ", H2=md?"## ":"";
  let out="";
  GROUPS.forEach(g=>{
    if(g.key==="title"){
      const t=(state.texts["title"]||"").trim();
      out+=(md?"# ":"")+ (t||"（表題未記入）")+"\n\n"; return;
    }
    out+=H+g.name+"\n\n";
    g.sections.forEach(sec=>{
      const t=(state.texts[sec.id]||"").trim();
      if(g.sections.length===1){ out+=(t||"（未記入）")+"\n\n"; }
      else{ out+=H2+sec.title+"\n"+(md?"\n":"")+(t||(md?"_（未記入）_":"（未記入）"))+"\n\n"; }
    });
  });
  out+=H+"引用文献\n\n";
  const refs=sortedRefs();
  out+= refs.length? refs.map(r=>(md?"- ":"")+formatReference(r)).join("\n") : (md?"_（なし）_":"（なし）");
  out+="\n";
  if(state.figures.length){
    out+="\n"+H+"図表\n\n";
    const map=figNumbers();
    state.figures.forEach(fig=>{
      const lab=map[fig.id], cap=(fig.caption||"").trim();
      out+=lab+(cap?"　"+cap:"")+"\n";
      if(fig.kind==="table" && fig.rows && fig.rows.length){
        if(md){
          const rs=fig.rows;
          out+="\n| "+rs[0].map(c=>c||" ").join(" | ")+" |\n| "+rs[0].map(()=>"---").join(" | ")+" |\n";
          rs.slice(1).forEach(r=>{ out+="| "+r.map(c=>c||" ").join(" | ")+" |\n"; });
          out+="\n";
        }else{
          fig.rows.forEach(r=>{ out+=r.join("\t")+"\n"; });
          out+="\n";
        }
      }else if(fig.img){
        if(md){ out+="\n!["+lab+"]("+fig.img+")\n\n"; }
        else{ out+="（"+lab+" の画像。アプリ内で確認するか、Wordに貼り付けてください）\n\n"; }
      }
    });
  }
  return out+"\n";
}
// Word(.docx) 用モデル：図表を本文の該当位置（「図1」「表1」の初出）に差し込む
function buildDocModel(){
  const map=figNumbers();
  const byLabel={}; state.figures.forEach(f=>byLabel[map[f.id]]=f);
  const placed=new Set();
  const blocks=[];
  function figBlock(f){
    const lab=map[f.id];
    if(f.kind==="table") return {type:"table",label:lab,caption:f.caption||"",rows:f.rows||[],merges:f.merges||[],headerRows:(f.headerRows==null?1:f.headerRows)};
    return {type:"image",label:lab,caption:f.caption||"",img:f.img};
  }
  function placeFrom(text){
    const seen=[]; const re=/(表|図)\d+/g; let m;
    while((m=re.exec(text))){ const lab=m[0]; if(byLabel[lab]&&!placed.has(lab)&&seen.indexOf(lab)<0) seen.push(lab); }
    seen.forEach(lab=>{ placed.add(lab); blocks.push(figBlock(byLabel[lab])); });
  }
  blocks.push({type:"title",text:(state.texts["title"]||"").trim()});
  GROUPS.forEach(g=>{
    if(g.key==="title") return;
    blocks.push({type:"heading",level:1,text:g.name});
    g.sections.forEach(sec=>{
      const t=(state.texts[sec.id]||"").trim();
      if(g.sections.length>1) blocks.push({type:"heading",level:2,text:sec.title});
      if(t){ blocks.push({type:"para",text:t}); placeFrom(t); }
    });
  });
  blocks.push({type:"heading",level:1,text:"引用文献"});
  sortedRefs().forEach(r=>blocks.push({type:"para",text:formatReference(r)}));
  const left=state.figures.filter(f=>!placed.has(map[f.id]));
  if(left.length){ blocks.push({type:"heading",level:1,text:"図表"}); left.forEach(f=>blocks.push(figBlock(f))); }
  return {blocks};
}
async function exportDocx(){
  toast("Wordファイルを作成中…");
  try{
    const res=await fetch("/api/docx",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(buildDocModel())});
    const ct=res.headers.get("Content-Type")||"";
    if(!res.ok || ct.indexOf("json")>=0){ const t=await res.text(); toast("作成に失敗しました: "+t.slice(0,120)); return; }
    const blob=await res.blob();
    const a=document.createElement("a"); a.href=URL.createObjectURL(blob); a.download="心理学論文_原稿.docx"; a.click(); URL.revokeObjectURL(a.href);
    toast("Wordファイル（心理学論文_原稿.docx）を保存しました。");
  }catch(e){ toast("作成に失敗しました: "+e); }
}
function download(name,text){
  const blob=new Blob([text],{type:"text/plain;charset=utf-8"});
  const a=document.createElement("a"); a.href=URL.createObjectURL(blob); a.download=name; a.click(); URL.revokeObjectURL(a.href);
}
async function copy(text,ok){ try{ await navigator.clipboard.writeText(text); toast(ok||"コピーしました"); }catch(e){ prompt("コピーしてください:",text); } }
function toast(m){ document.getElementById("status").textContent=m; }

// ---------- 保存 ----------
let saveTimer=null;
function save(){ clearTimeout(saveTimer); saveTimer=setTimeout(()=>{ try{ localStorage.setItem(STORE_KEY,JSON.stringify(state)); }catch(e){ toast("⚠ 保存容量を超えました。画像の数を減らすか小さくしてください。"); } },250); }
function load(){ try{ const s=localStorage.getItem(STORE_KEY); if(s){ state=JSON.parse(s); state.texts=state.texts||{}; state.refs=state.refs||[]; state.figures=state.figures||[]; } }catch(e){} }
function escapeHtml(s){ return (s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }

// ---------- 更新チェック ----------
function cmpVer(a,b){ const pa=String(a).split(".").map(Number), pb=String(b).split(".").map(Number); for(let i=0;i<Math.max(pa.length,pb.length);i++){ const d=(pa[i]||0)-(pb[i]||0); if(d)return d; } return 0; }
async function checkUpdate(manual){
  try{
    const d=await (await fetch("/api/update-check")).json();
    document.getElementById("ver").textContent="バージョン "+d.current;
    if(d.latest && cmpVer(d.latest,d.current)>0){
      const b=document.getElementById("updbanner"); b.style.display="block";
      b.innerHTML="🔔 新しい版 v"+escapeHtml(d.latest)+" があります。"+(d.note?escapeHtml(d.note)+" ":"")
        +(d.download?'<a href="'+escapeHtml(d.download)+'" target="_blank" rel="noopener">入手先を開く</a>':"（先生の案内に従って app.py を差し替えてください）");
    }else if(manual){
      toast(d.latest? ("最新版を使っています（v"+d.current+"）。") : "自動更新は未設定です。更新は app.py の差し替えで行えます。");
    }
  }catch(e){ if(manual) toast("更新確認に失敗しました。"); }
}

// ---------- 初期化 ----------
load(); renderNav(); renderSections(); renderProgress(); renderRefs(); renderFigures();
checkUpdate(false);
document.getElementById("chkupd").onclick=(e)=>{ e.preventDefault(); checkUpdate(true); };
document.getElementById("searchBtn").onclick=doSearch;
document.getElementById("q").addEventListener("keydown",e=>{ if(e.key==="Enter")doSearch(); });
document.getElementById("copyRefs").onclick=()=>copy(sortedRefs().map(formatReference).join("\n"),"引用文献リストをコピーしました");
document.getElementById("dlDocx").onclick=exportDocx;
document.getElementById("copyAll").onclick=()=>copy(assemble(false),"論文全体をコピーしました");
document.getElementById("dlMd").onclick=()=>download("心理学論文_原稿.md",assemble(true));
document.getElementById("dlTxt").onclick=()=>download("心理学論文_原稿.txt",assemble(false));
document.getElementById("addTableBtn").onclick=()=>document.getElementById("tableFile").click();
document.getElementById("addFigBtn").onclick=()=>document.getElementById("figFile").click();
document.getElementById("tableFile").addEventListener("change",e=>{ const f=e.target.files[0]; if(f) addTableFile(f); e.target.value=""; });
document.getElementById("figFile").addEventListener("change",e=>{ const f=e.target.files[0]; if(f) addImageFile(f); e.target.value=""; });
document.getElementById("clearAll").onclick=()=>{ if(confirm("入力・文献・図表をすべて消去します。よろしいですか？")){ state={texts:{},refs:[],figures:[]}; save(); renderSections(); renderProgress(); renderRefs(); renderFigures(); } };
</script>
</body>
</html>
"""


def main():
    base = 8791
    httpd = None
    port = base
    for p in range(base, base + 20):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            continue
    if httpd is None:
        print("空きポートが見つかりませんでした。"); sys.exit(1)
    url = "http://127.0.0.1:%d/" % port
    print("=" * 60)
    print("  心理学 論文執筆アプリ（全体版）を起動しました")
    print("  ブラウザが自動で開きます。開かない場合はこのURLをブラウザに貼り付け:")
    print("  " + url)
    print("  終了するには、このウィンドウ（黒い画面）を閉じてください。")
    print("=" * 60)
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n終了しました。")


if __name__ == "__main__":
    main()
