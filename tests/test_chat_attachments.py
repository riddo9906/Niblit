from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from modules.chat_attachments import AttachmentStore, AttachmentError


def pdf_bytes(texts):
    # A real, small PDF with one Helvetica text stream per page.
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'']
    kids = []
    font_id = 3 + len(texts) * 2
    for text in texts:
        page_id = len(objects) + 1
        kids.append(f'{page_id} 0 R')
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {page_id+1} 0 R >>'.encode())
        text = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        stream = f'BT /F1 12 Tf 40 700 Td ({text}) Tj ET'.encode()
        objects.append(f'<< /Length {len(stream)} >>\nstream\n'.encode()+stream+b'\nendstream')
    objects[1] = f'<< /Type /Pages /Count {len(texts)} /Kids [{" ".join(kids)}] >>'.encode()
    objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    output = b'%PDF-1.4\n'
    positions = [0]
    for index, obj in enumerate(objects, 1):
        positions.append(len(output))
        output += f'{index} 0 obj\n'.encode() + obj + b'\nendobj\n'
    offset = len(output)
    output += f'xref\n0 {len(positions)}\n0000000000 65535 f \n'.encode()
    output += b''.join(f'{position:010d} 00000 n \n'.encode() for position in positions[1:])
    return output + f'trailer\n<< /Size {len(positions)} /Root 1 0 R >>\nstartxref\n{offset}\n%%EOF'.encode()


@pytest.fixture
def store(monkeypatch):
    store = AttachmentStore()
    monkeypatch.setattr(store, '_event', lambda *args: None)
    return store


def test_real_pdf_text_is_indexed_and_query_retrieves_the_right_page(store):
    metadata = store.ingest('programming.pdf', pdf_bytes(['Title and introduction', 'Static binding uses declaration time. Example value 9876.']))
    assert metadata['page_count'] == metadata['pages_indexed'] == 2
    context = store.context([metadata['id']], 'Explain static binding and its example value')
    assert '[Page 2]' in context['text'] and '9876' in context['text']
    assert context['text'].index('[Page 2]') < context['text'].index('[Page 1]')
    assert '%PDF-' not in context['text']


def test_corrupt_and_image_only_pdfs_are_not_reported_understood(store):
    for data in (b'not a pdf', b'%PDF-1.4 garbage', pdf_bytes([''])):
        with pytest.raises(AttachmentError): store.ingest('test.pdf', data)


def test_document_reference_expiry_and_path_validation(store):
    with pytest.raises(AttachmentError, match='expired'): store.context(['missing'], 'question')
    with pytest.raises(AttachmentError): store.ingest('../secret.pdf', b'%PDF-')
    with pytest.raises(AttachmentError): store.ingest('binary.txt', b'\x00')


def test_uploaded_pdf_reaches_selected_model_without_workspace_path_guessing(store, monkeypatch):
    import server
    import niblit_brain
    from modules import chat_attachments, llm_chat_memory
    monkeypatch.setattr(chat_attachments, 'attachment_store', store)
    monkeypatch.setattr(server, 'get_core', lambda: object())
    monkeypatch.setattr(server, '_answer_project_file_question', lambda *a: pytest.fail('Upload routed to workspace guessing'))
    cloud = Mock()
    cloud._request_json.return_value = {'model':'local-test', 'choices':[{'message':{'content':'The document value is 9876 (page 2).'}}]}
    monkeypatch.setattr(niblit_brain, 'get_niblit_cloud_brain', lambda: cloud)
    memory = Mock()
    memory.load_messages.return_value = []
    monkeypatch.setattr(llm_chat_memory, 'get_llm_chat_memory', lambda: memory)
    client = TestClient(server.app)
    response = client.post('/api/chat/attachments?filename=test.pdf', content=pdf_bytes(['Introduction', 'The marker value is 9876.']))
    assert response.status_code == 200
    attachment_id = response.json()['id']
    result = client.post('/chat', json={'text':'View the attached file and report its marker value','model':'local-test','use_model':True,'attachment_ids':[attachment_id]})
    assert result.status_code == 200 and result.json()['document_sources']
    payload = cloud._request_json.call_args.args[1]
    assert payload['model'] == 'local-test'
    assert '[Page 2]' in payload['messages'][-1]['content'] and '9876' in payload['messages'][-1]['content']
    assert '%PDF-' not in str(payload)
    assert '9876' not in memory.add_exchange.call_args.args[0]  # saved reference, not repeated excerpts


def test_legacy_binary_history_is_repaired_without_database_rewrite():
    from modules.llm_chat_memory import readable_history_content
    raw = 'View this file\n--- attached: book.pdf ---\n%PDF-1.7\nRAW BINARY STREAM'
    result = readable_history_content(raw)
    assert 'View this file' in result and 'reattach' in result
    assert '%PDF-' not in result and 'RAW BINARY' not in result
