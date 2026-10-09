"""
The Company Brain (Growth Mentorship and up): the owner's own documents — price list, catalogue, FAQs, policies, past
quotations — that every AI staff member answers from. Files are turned into plain text and cut into short passages;
for each question the most relevant passages are handed to the AI. Nothing is sent anywhere else.
"""
import csv
import io
import re

from fastapi import HTTPException

from .db import db, now
from .services import new_id

MAX_FILE = 8 * 1024 * 1024
MAX_DOCS = 60
MAX_CHARS = 200_000          # per document, after extraction
CHUNK = 900
KINDS = {"price_list": "Price list", "catalogue": "Catalogue", "faq": "FAQs", "policy": "Policies", "quotation": "Past quotation", "other": "Other"}
STOP = set("the a an and or of to in on for with is are was were be by at as it this that from your our we you i me my their they "
           "ka ki ke hai hain aur se ko par me mein".split())


def extract(data: bytes, filename: str, ctype: str) -> str:
    name = (filename or "").lower()
    try:
        if name.endswith(".pdf") or ctype == "application/pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in reader.pages[:200])
        if name.endswith(".docx"):
            import docx
            d = docx.Document(io.BytesIO(data))
            parts = [p.text for p in d.paragraphs]
            for t in d.tables:
                for row in t.rows:
                    parts.append(" | ".join(c.text.strip() for c in row.cells))
            return "\n".join(parts)
        if name.endswith((".xlsx", ".xlsm")):
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            rows = []
            for ws in wb.worksheets[:10]:
                rows.append(f"# {ws.title}")
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i > 5000:
                        break
                    cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                    if cells:
                        rows.append(" | ".join(cells))
            return "\n".join(rows)
        if name.endswith(".csv") or ctype == "text/csv":
            text = data.decode("utf-8-sig", errors="replace")
            return "\n".join(" | ".join(c.strip() for c in row if c.strip()) for row in csv.reader(io.StringIO(text)))
        if name.endswith((".txt", ".md")) or ctype.startswith("text/"):
            return data.decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001  a broken file is the owner's to fix, not a crash
        raise HTTPException(400, f"We couldn't read that file ({type(e).__name__}). Try saving it again as PDF, Word, Excel or CSV.")
    raise HTTPException(415, "Upload a PDF, Word (.docx), Excel (.xlsx), CSV or text file.")


def chunks(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text)
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n(?=[#•\-\d])", text) if p.strip()]
    out, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 1 > CHUNK and cur:
            out.append(cur)
            cur = ""
        while len(p) > CHUNK:
            out.append(p[:CHUNK])
            p = p[CHUNK:]
        cur = (cur + "\n" + p).strip()
    if cur:
        out.append(cur)
    return out[:400]


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9ऀ-૿]{2,}", (text or "").lower()) if w not in STOP}


async def add(ws: str, actor: str, title: str, kind: str, text: str, filename: str = "") -> dict:
    if await db().brain_docs.count_documents({"ws": ws}) >= MAX_DOCS:
        raise HTTPException(400, f"The Company Brain holds up to {MAX_DOCS} documents. Remove an old one first.")
    text = (text or "").strip()[:MAX_CHARS]
    if len(text) < 20:
        raise HTTPException(400, "We couldn't find any text in that. If it's a scanned picture, type or paste the key facts instead.")
    parts = chunks(text)
    doc = {"_id": new_id(), "ws": ws, "title": (title or filename or "Document")[:120], "kind": kind if kind in KINDS else "other",
           "filename": filename[:200], "chars": len(text), "passages": len(parts), "by": actor, "created_at": now()}
    await db().brain_docs.insert_one(doc)
    if parts:
        await db().brain_chunks.insert_many([{"_id": new_id(), "ws": ws, "doc_id": doc["_id"], "n": i, "text": p, "words": sorted(words(p))[:300]}
                                             for i, p in enumerate(parts)])
    return doc


async def context(ws: str, query: str, k: int = 5) -> str:
    """The k passages that share the most words with the question (price lists and FAQs first on a tie)."""
    q = words(query)
    if not q:
        return ""
    found = []
    async for c in db().brain_chunks.find({"ws": ws, "words": {"$in": list(q)[:60]}}, {"text": 1, "words": 1, "doc_id": 1}).limit(400):
        overlap = len(q & set(c.get("words") or []))
        found.append((overlap, c["text"]))
    found.sort(key=lambda x: -x[0])
    return "\n---\n".join(t for _, t in found[:k])


async def remove(ws: str, doc_id: str) -> None:
    await db().brain_docs.delete_one({"_id": doc_id, "ws": ws})
    await db().brain_chunks.delete_many({"doc_id": doc_id, "ws": ws})


async def ensure_indexes() -> None:
    await db().brain_docs.create_index([("ws", 1), ("created_at", -1)])
    await db().brain_chunks.create_index([("ws", 1), ("words", 1)])
    await db().brain_chunks.create_index("doc_id")
