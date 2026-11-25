"""Collect bounded public web documents into the existing evidence audit volume."""
import base64
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import http.client
import ipaddress
from pathlib import Path
import socket
import ssl
from urllib.parse import urljoin, urlsplit, urlunsplit
from uuid import uuid4

from research_app.evidence import source_record
from research_app.search_audit import _write_json


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.hidden += 1
        if tag in ('p', 'div', 'br', 'article', 'section', 'li', 'h1', 'h2', 'h3'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript') and self.hidden:
            self.hidden -= 1
        if tag in ('p', 'div', 'article', 'section', 'li'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _public_address(url):
    parsed = urlsplit(url)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
            or parsed.password or any(c.isspace() or ord(c) < 32 for c in url)):
        raise ValueError('Source URL must be public HTTP(S) without credentials.')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    if port not in (80, 443):
        raise ValueError('Source URL must use a standard web port.')
    addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('Source URL resolves to a non-public address.')
    return parsed, addresses[0][4][0], port


def fetch_document(url, *, timeout=10, max_bytes=2_000_000):
    """Fetch HTML/plain text, validating every redirect and pinning the resolved IP."""
    for _ in range(6):
        parsed, address, port = _public_address(url)
        connection = http.client.HTTPConnection(parsed.hostname, port, timeout=timeout)
        # Pin the validated address, retaining the original hostname for TLS and Host.
        sock = socket.create_connection((address, port), timeout)
        try:
            if parsed.scheme == 'https':
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parsed.hostname)
            connection.sock = sock
            target = urlunsplit(('', '', parsed.path or '/', parsed.query, ''))
            connection.request('GET', target, headers={'User-Agent': 'HomicideResearch/1.0',
                                                      'Accept': 'text/html,text/plain', 'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location:
                    raise ValueError('Redirect has no destination.')
                url = urljoin(url, location)
                continue
            if not 200 <= response.status < 300:
                raise ValueError(f'Source returned HTTP {response.status}.')
            media_type = response.headers.get_content_type()
            if media_type not in ('text/html', 'application/xhtml+xml', 'text/plain'):
                raise ValueError(f'Unsupported source media type: {media_type}.')
            if response.getheader('Content-Encoding', 'identity') != 'identity':
                raise ValueError('Unsupported compressed response.')
            raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise ValueError('Source exceeds retrieval size limit.')
            decoded = raw.decode(response.headers.get_content_charset() or 'utf-8', errors='replace')
            if media_type != 'text/plain':
                parser = _Text()
                parser.feed(decoded)
                decoded = '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())
            if not decoded.strip():
                raise ValueError('Source contains no readable text.')
            return dict(text=decoded, raw_base64=base64.b64encode(raw).decode('ascii'),
                        media_type=media_type, final_url=url)
        finally:
            connection.close()
            sock.close()
    raise ValueError('Source exceeded redirect limit.')


def _associate(source, association):
    links = source.setdefault('search_results', [])
    if association not in links:
        links.append(association)


def collect_sources(results, assessments, search_run_id, *, existing_sources=None,
                    volume_path=None, fetch=fetch_document):
    """Accumulate eligible source versions; failed fetches retain labeled excerpts."""
    sources = deepcopy(existing_sources or {})
    eligible = {item['result_rank'] for item in assessments
                if item['label'] in ('candidate_evidence', 'primary_target', 'uncertain')}
    known = {source['url']: source_id for source_id, source in sources.items()
             if source.get('retrieval_status') == 'retrieved'}
    for result in results:
        if result['result_rank'] not in eligible:
            continue
        url = result['url']
        association = {'search_run_id': search_run_id, 'result_rank': result['result_rank'],
                       'search_result_id': result.get('search_result_id')}
        if url in known:
            _associate(sources[known[url]], association)
            continue
        fetched_at = datetime.now(timezone.utc).isoformat()
        outcome = None
        error = None
        try:
            outcome = fetch(url)
            if not isinstance(outcome.get('text'), str) or not outcome['text'].strip():
                raise ValueError('Source contains no readable text.')
        except (ValueError, OSError, http.client.HTTPException) as exc:
            error = str(exc)
        text = outcome['text'] if outcome and error is None else result.get('snippet') or ''
        kind = 'source_text' if error is None else 'search_excerpt'
        identity = url + '\n' + kind + '\n' + text
        source_id = 'src_' + sha256(identity.encode('utf-8')).hexdigest()
        if source_id in sources:
            _associate(sources[source_id], association)
            continue
        source = source_record(source_id, url=url, text=text, title=result.get('title'),
                               published_at=result.get('published_date'), search_run_id=search_run_id,
                               result_rank=result['result_rank'], retrieval_status='retrieved' if error is None else 'failed',
                               retrieved_at=fetched_at, evidence_kind=kind)
        _associate(source, association)
        source['retrieval_error'] = error
        source['final_url'] = outcome.get('final_url', url) if outcome else url
        if volume_path:
            path = Path(volume_path) / 'raw' / 'source_documents' / source_id / f'{uuid4()}.json'
            source['artifact_path'] = str(path)
            # Storage failures propagate: retrieval must never pretend an audit write succeeded.
            _write_json(path, {'source': source, 'response': outcome})
        sources[source_id] = source
        if error is None:
            known[url] = source_id
    return sources
