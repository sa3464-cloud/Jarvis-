import json
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener

from jarvis.agent import main


class LocalEmbeddingTest(unittest.TestCase):
    def setUp(self):
        self.server = main.LocalServer(('127.0.0.1', 0), main.Handler)
        self.server.csrf = 'standalone-csrf'
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        self.opener = build_opener(ProxyHandler({}))
        self.thread = Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        mock = patch.object(main.conversation, 'status', return_value={'message': 'Fixture'})
        mock.start()
        self.addCleanup(mock.stop)

    def request(self, path, *, body=None, origin=None, token='', method=None, **extra):
        origin = self.origin if origin is None else origin
        headers = {'Origin': origin, 'X-Jarvis-CSRF': token, **extra}
        data = None if body is None else json.dumps(body).encode()
        try:
            response = self.opener.open(Request(self.origin + path, data=data, headers=headers, method=method))
        except HTTPError as error:
            response = error
        with response:
            return response.code, response.headers, response.read()

    def test_public_origin_can_only_read_the_nonprivate_probe(self):
        probe = self.request('/embed-ready', origin=main.PUBLIC_ORIGIN)
        self.assertEqual(probe[0], 200)
        self.assertEqual(probe[1].get('Access-Control-Allow-Origin'), main.PUBLIC_ORIGIN)
        self.assertEqual(json.loads(probe[2]), {'ready': True})
        foreign = self.request('/embed-ready', origin='https://example.invalid')
        self.assertEqual(foreign[0], 403)
        self.assertIsNone(foreign[1].get('Access-Control-Allow-Origin'))
        chat = self.request('/api/chat', body={}, origin=main.PUBLIC_ORIGIN, token=self.server.csrf)
        self.assertEqual(chat[0], 403)
        self.assertIsNone(chat[1].get('Access-Control-Allow-Origin'))
        status = self.request('/api/status', origin=main.PUBLIC_ORIGIN)
        self.assertIsNone(status[1].get('Access-Control-Allow-Origin'))

    def test_only_the_embedded_document_can_be_framed(self):
        direct = self.request('/')
        self.assertIn("frame-ancestors 'none'", direct[1]['Content-Security-Policy'])
        embedded = self.request('/embedded')
        self.assertIn('frame-ancestors ' + main.PUBLIC_ORIGIN, embedded[1]['Content-Security-Policy'])
        self.assertIn(b'data-mode="embedded"', embedded[2])

    def test_pairing_is_single_use_scoped_and_revocable(self):
        issued = self.request('/api/embed-code', body={}, token=self.server.csrf)
        code = json.loads(issued[2])['code']
        connect = {'body': {'code': code}, 'X-Jarvis-Embedded': 'yes'}
        self.assertEqual(self.request('/api/embed/connect', origin=main.PUBLIC_ORIGIN, **connect)[0], 403)
        self.assertEqual(self.request('/api/embed/chat', body={}, token=self.server.csrf)[0], 401)
        paired = self.request('/api/embed/connect', **connect)
        self.assertEqual(paired[0], 200)
        token = json.loads(paired[2])['csrf']
        self.assertEqual(self.request('/api/embed/connect', **connect)[0], 401)
        self.assertEqual(self.request('/api/chat', body={}, token=token)[0], 403)
        command = self.request('/api/embed/chat', body={'question': 'Plan my day'}, token=token)
        self.assertEqual(json.loads(command[2])['action'], 'plan_day')
        self.assertEqual(self.request('/api/embed-revoke', body={}, token=self.server.csrf)[0], 200)
        self.assertEqual(self.request('/api/embed/chat', body={}, token=token)[0], 401)

    def test_pair_code_and_session_expire(self):
        pairing = main.Pairing()
        with patch.object(main, 'monotonic', return_value=10):
            expired = pairing.issue()
        with patch.object(main, 'monotonic', return_value=11 + pairing.code_lifetime):
            self.assertIsNone(pairing.connect(expired))
            token = pairing.connect(pairing.issue())
            self.assertTrue(pairing.authorized(token))
        with patch.object(main, 'monotonic', return_value=12 + pairing.code_lifetime + pairing.session_lifetime):
            self.assertFalse(pairing.authorized(token))
