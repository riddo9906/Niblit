"""Explicit remote-client boundary. Proxy headers never grant trust."""
import re
from urllib.parse import urlsplit


def remote_origin(value):
    if not value:return None
    u=urlsplit(value)
    if (u.scheme!='https' or not u.hostname or u.hostname in {'localhost','127.0.0.1'}
        or u.username or u.password or u.path or u.query or u.fragment or u.port
        or not re.fullmatch(r'[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+',u.hostname)):
        raise ValueError('Remote client origin must be one explicit HTTPS DNS origin, without path or credentials')
    return value


def client_path(path):
    return path in {'/','/portal.js','/portal.css','/api/health','/api/model-status',
        '/api/login','/api/logout','/api/signup','/api/session','/api/messages',
        '/api/plans','/api/workspaces'} or bool(re.fullmatch(r'/api/workspaces/[A-Za-z0-9_-]{1,80}/members',path))
