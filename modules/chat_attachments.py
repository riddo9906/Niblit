"""Local document indexing and bounded, page-cited chat retrieval.

Uploaded bytes never become model input. Indexes live in process memory and
must be reattached after restart; this is not permanent knowledge promotion.
"""
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from math import log
from pathlib import Path
import re
from threading import RLock
from uuid import uuid4

MAX_BYTES = 50_000_000
MAX_PAGES = 1200
MAX_TEXT = 2_000_000
MAX_CONTEXT = 18000
TEXT_TYPES = {'.txt', '.md', '.py', '.js', '.ts', '.tsx', '.jsx', '.json', '.csv', '.rst', '.html', '.css', '.xml', '.yaml', '.yml', '.log'}
STOP = set('the a an and or to of in on is are it this that for with from attached attachment file document pdf view read summarize summary please me what does how can you about'.split())


def words(text):
    return [word for word in re.findall(r'[a-z0-9_]{2,}', text.lower()) if word not in STOP]


class AttachmentError(ValueError):
    pass


class AttachmentStore:
    def __init__(self):
        self.lock = RLock()
        self.documents = OrderedDict()

    def ingest(self, name, data):
        if not isinstance(name, str) or not name or len(name) > 200 or any(c in name for c in '/\\\r\n\x00'):
            raise AttachmentError('Use a filename without directory components')
        if not data or len(data) > MAX_BYTES:
            raise AttachmentError('Attachments must be non-empty and at most 50 MB')
        suffix = Path(name).suffix.lower()
        truncated = False
        if suffix == '.pdf':
            if b'%PDF-' not in data[:1024]:
                raise AttachmentError('This file does not contain a PDF header')
            try:
                from pypdf import PdfReader
                reader = PdfReader(BytesIO(data), strict=False)
                if reader.is_encrypted and not reader.decrypt(''):
                    raise AttachmentError('This PDF is encrypted; provide an unlocked copy')
                page_count = len(reader.pages)
                pages, remaining = [], MAX_TEXT
                for index in range(min(page_count, MAX_PAGES)):
                    if remaining <= 0:
                        truncated = True
                        break
                    text = (reader.pages[index].extract_text() or '').strip()
                    bounded = text[:min(remaining, 16000)]
                    truncated |= len(bounded) < len(text)
                    remaining -= len(bounded)
                    if bounded:
                        pages.append((index + 1, bounded))
                truncated |= page_count > MAX_PAGES
            except AttachmentError:
                raise
            except ImportError:
                raise AttachmentError('The PDF parser is missing from this Core build') from None
            except Exception:
                raise AttachmentError('This PDF could not be parsed; it may be damaged or unsupported') from None
            if not pages:
                raise AttachmentError('No readable PDF text was found. This document needs OCR; no content was sent to a model')
        elif suffix in TEXT_TYPES:
            if len(data) > 2_000_000:
                raise AttachmentError('Text attachments are limited to 2 MB')
            try:
                text = data.decode('utf-8-sig')
            except UnicodeDecodeError:
                raise AttachmentError('This attachment is not readable UTF-8 text') from None
            if '\x00' in text or not text.strip():
                raise AttachmentError('This attachment does not contain readable text')
            pages, page_count = [(1, text[:MAX_TEXT])], 1
            truncated = len(text) > MAX_TEXT
        else:
            raise AttachmentError('Supported attachments: PDF, text, Markdown, source code, CSV and JSON')

        chunks = []
        for page, text in pages:
            for offset in range(0, len(text), 1500):
                content = text[offset:offset + 1800]
                chunks.append({'page': page, 'text': content, 'terms': Counter(words(content))})
        frequencies = Counter(term for chunk in chunks for term in chunk['terms'])
        metadata = {'id': uuid4().hex, 'name': name, 'kind': 'pdf' if suffix == '.pdf' else 'text',
            'sha256': sha256(data).hexdigest(), 'bytes': len(data), 'page_count': page_count,
            'pages_indexed': len(pages), 'characters_indexed': sum(len(text) for _, text in pages),
            'chunks_indexed': len(chunks), 'truncated': truncated,
            'indexed_at': datetime.now(timezone.utc).isoformat(), 'retention': 'Until Core restarts or the index is evicted'}
        with self.lock:
            while len(self.documents) >= 8:
                self.documents.popitem(last=False)
            self.documents[metadata['id']] = (metadata, chunks, frequencies)
        self._event('document.attachment.indexed', metadata)
        return metadata

    def context(self, ids, query):
        if not isinstance(ids, list) or len(ids) > 4 or any(not isinstance(item, str) for item in ids):
            raise AttachmentError('At most four attachment IDs are supported')
        with self.lock:
            try:
                documents = [self.documents[item] for item in dict.fromkeys(ids)]
            except KeyError:
                raise AttachmentError('This attachment index expired. Reattach the document before asking about it') from None
        contexts, sources = [], []
        budget = MAX_CONTEXT // max(len(documents), 1)
        query_terms = set(words(query))
        for metadata, chunks, frequencies in documents:
            def score(chunk):
                return sum((chunk['terms'][term] / (chunk['terms'][term] + .8)) *
                    log(1 + len(chunks) / (1 + frequencies[term])) for term in query_terms if chunk['terms'][term])
            ranked = sorted(enumerate(chunks), key=lambda item: (-score(item[1]), item[0]))
            chosen, page_counts, remaining = [], Counter(), budget
            for _, chunk in ranked:
                if remaining < 300 or len(chosen) >= 6:
                    break
                if page_counts[chunk['page']] >= 2:
                    continue
                content = chunk['text'][:remaining]
                remaining -= len(content)
                page_counts[chunk['page']] += 1
                chosen.append(f"[Page {chunk['page']}]\n{content}")
            contexts.append(f"DOCUMENT {metadata['name']}\nIndexed {metadata['pages_indexed']} of {metadata['page_count']} pages. "
                f"Relevant excerpts only; full document is not in the prompt. Index truncated: {metadata['truncated']}.\n" + '\n\n'.join(chosen))
            sources.append({**metadata, 'pages_selected': list(page_counts), 'characters_selected': budget - remaining})
        result = {'text': '\n\n'.join(contexts), 'sources': sources}
        if sources:
            self._event('document.attachment.context.selected', {'sources': [
                {key: source[key] for key in ('id', 'name', 'pages_selected', 'characters_selected')} for source in sources]})
        return result

    @staticmethod
    def _event(kind, payload):
        from modules.event_bus import get_event_bus, NiblitEvent
        get_event_bus().publish(NiblitEvent(type=kind, source='chat_attachment_index', payload=payload))


attachment_store = AttachmentStore()
