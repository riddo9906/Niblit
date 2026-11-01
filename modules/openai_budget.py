"""Local, persistent limits for Niblit's text-only Responses calls.

This ledger does not control spending in the OpenAI browser or other apps.
Reservations use a conservative byte bound; actual reported usage replaces
them after completion. Unknown outcomes retain the reservation as estimated.
"""
import os
from contextlib import contextmanager
from math import isfinite
from pathlib import Path
import sqlite3
from time import time
from uuid import uuid4

RATES = {'gpt-6-astra': (10., 1., 50., 12.5), 'gpt-4o-mini': (.15, .075, .60, .15)}


class BudgetError(ValueError):
    pass


def setting(name, default):
    try:
        value = float(os.getenv(name, str(default)))
        if not isfinite(value) or value <= 0 or value > 1000:
            raise ValueError()
        return value
    except ValueError:
        raise BudgetError(f'{name} must be a positive number no greater than 1000') from None


class OpenAIBudget:
    def __init__(self, path=None):
        history = Path(os.getenv('NIBLIT_LLM_CHAT_DB_PATH', str(Path.cwd() / 'llm_chat_history.sqlite')))
        self.path = Path(path or os.getenv('NIBLIT_OPENAI_USAGE_DB', str(history.parent / 'openai_usage.sqlite')))

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute('CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, at REAL, model TEXT, reserved REAL, charged REAL, state TEXT, input_tokens INTEGER, output_tokens INTEGER)')
        connection.commit()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def preview(self, model, messages, max_tokens):
        if model not in RATES:
            raise BudgetError('No verified price is configured for this model. Use a local model or configure a supported model before spending.')
        limit = int(setting('OPENAI_MAX_OUTPUT_TOKENS', 800))
        output = min(max_tokens, limit)
        texts = [message['content'] for message in messages]
        if sum(len(text) for text in texts) > 16000:
            raise BudgetError('The API input exceeds the 16,000-character local budget. Start a shorter conversation, narrow the document question, or use a local model.')
        # A UTF-8 byte bound plus protocol allowance deliberately overestimates
        # ordinary text token counts. It is a guard, not an invoice prediction.
        input_bound = sum(len(text.encode('utf-8')) for text in texts) + 2048
        rate = RATES[model]
        estimate = (input_bound * max(rate[0], rate[3]) + output * rate[2]) / 1_000_000
        maximum = setting('OPENAI_MAX_REQUEST_USD', .20)
        if estimate > maximum:
            raise BudgetError(f'This request could exceed the ${maximum:.2f} local request limit (conservative bound ${estimate:.3f}). Narrow the input or use a local model.')
        return {'maximum_estimated_usd': estimate, 'max_output_tokens': output, 'request_limit_usd': maximum}

    def reserve(self, model, messages, max_tokens):
        preview = self.preview(model, messages, max_tokens)
        maximum = setting('OPENAI_LOCAL_BUDGET_USD', .50)
        with self.connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            used = connection.execute('SELECT COALESCE(SUM(charged + reserved), 0) FROM requests').fetchone()[0]
            if used + preview['maximum_estimated_usd'] > maximum:
                raise BudgetError(f'Niblit’s ${maximum:.2f} local API budget is exhausted or reserved. Local inference remains available. This budget excludes browser sessions and other apps.')
            request_id = uuid4().hex
            connection.execute('INSERT INTO requests VALUES (?, ?, ?, ?, 0, ?, 0, 0)',
                (request_id, time(), model, preview['maximum_estimated_usd'], 'reserved'))
        return request_id, preview

    def settle(self, reservation, usage=None, *, uncertain=False):
        with self.connection() as connection:
            row = connection.execute('SELECT model, reserved FROM requests WHERE id=? AND state=?', (reservation, 'reserved')).fetchone()
            if not row:
                return None
            model, reserved = row
            inputs, outputs = 0, 0
            if usage and isinstance(usage, dict) and 'input_tokens' in usage and 'output_tokens' in usage:
                inputs, outputs = max(0, int(usage['input_tokens'])), max(0, int(usage['output_tokens']))
                details = usage.get('input_tokens_details') or {}
                cached = max(0, min(inputs, int(details.get('cached_tokens', 0))))
                rate = RATES[model]
                charged = ((inputs-cached)*rate[0] + cached*rate[1] + outputs*rate[2]) / 1_000_000
                state = 'reported_usage'
            else:
                charged, state = (reserved, 'estimated_unknown_outcome') if uncertain else (0, 'not_billed')
            connection.execute('UPDATE requests SET reserved=0, charged=?, state=?, input_tokens=?, output_tokens=? WHERE id=?',
                (charged, state, inputs, outputs, reservation))
            return charged

    def status(self):
        with self.connection() as connection:
            used, reserved, count = connection.execute('SELECT COALESCE(SUM(charged),0), COALESCE(SUM(reserved),0), COUNT(*) FROM requests').fetchone()
        maximum = setting('OPENAI_LOCAL_BUDGET_USD', .50)
        return {'charged_or_estimated_usd': used, 'reserved_usd': reserved, 'request_count': count,
            'local_limit_usd': maximum, 'remaining_usd': max(0, maximum-used-reserved),
            'per_request_limit_usd': setting('OPENAI_MAX_REQUEST_USD', .20),
            'max_output_tokens': int(setting('OPENAI_MAX_OUTPUT_TOKENS', 800)),
            'scope': 'Niblit text API calls since this ledger was created; excludes browser agents and other applications'}
