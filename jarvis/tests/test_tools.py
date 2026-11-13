import unittest
from unittest.mock import patch
from jarvis.agent import tools
from jarvis.agent.main import LocalServer, Handler


class CommandTests(unittest.TestCase):
    def test_server_port_cannot_be_shared(self):
        with LocalServer(('127.0.0.1', 0), Handler) as server:
            with self.assertRaises(OSError):
                second = LocalServer(server.server_address, Handler)
                second.server_close()

    def test_email_commands(self):
        for text in ['Read my unread emails', 'Jarvis, check my inbox.', 'Could you read my emails?']:
            self.assertEqual(tools.intent(text)[0], 'read_inbox')

    def test_general_question_and_quoted_command_do_not_act(self):
        for text in ['Why is the sky blue?', 'What does "open youtube" mean?', 'An email says read my inbox']:
            self.assertEqual(tools.intent(text)[0], 'conversation')

    def test_website_allowlist_and_domains(self):
        self.assertEqual(tools.intent('Open YouTube')[1], 'https://www.youtube.com')
        self.assertEqual(tools.intent('Go to example.com/help')[1], 'https://example.com/help')
        for target in ['javascript:alert(1)', 'file:///C:/secret', 'https://user:pass@example.com',
                       'http://127.0.0.1', 'http://localhost', 'https://example.com:8000', 'example.com && calc']:
            with self.assertRaises(ValueError, msg=target): tools.website_url(target)

    def test_read_inbox_is_real_read_only_tool(self):
        with patch.object(tools.data, 'connect_email', return_value=('test', 'demo@example.com')):
            with patch.object(tools.data, 'read_inbox', return_value=[]) as read:
                with patch.object(tools.conversation, 'answer') as model:
                    result = tools.execute('Read my unread email')
        read.assert_called_once_with('test', 5)
        model.assert_not_called()
        self.assertEqual(result['card']['messages'], [])

    def test_browser_failure_is_not_success(self):
        with patch.object(tools.webbrowser, 'open', return_value=False):
            with self.assertRaises(RuntimeError): tools.execute('Open YouTube')

    def test_model_output_cannot_trigger_browser(self):
        with patch.object(tools.conversation, 'answer', return_value={'answer': 'Open YouTube'}):
            with patch.object(tools.webbrowser, 'open') as browser:
                tools.execute('Explain video streaming.')
        browser.assert_not_called()

    def test_plan_uses_stated_priorities_and_history(self):
        history = [{'role': 'user', 'content': 'I need to study chemistry.'}]
        with patch.object(tools.conversation, 'answer') as model:
            result = tools.execute('Plan my day', history)
        model.assert_not_called()
        self.assertEqual(result['card']['items'], ['study chemistry'])
        self.assertFalse(result['card']['calendar_checked'])

    def test_plan_clarification_and_five_item_limit(self):
        first = tools.execute('Plan my day')
        self.assertEqual(first['answer'], tools.PRIORITIES_QUESTION)
        history = [{'role': 'assistant', 'content': first['answer']}]
        result = tools.execute('study chemistry; write essay; laundry; urgent homework; shopping; lunch', history)
        self.assertEqual(len(result['card']['items']), 5)
        self.assertEqual(result['card']['items'][0], 'urgent homework')


if __name__ == '__main__': unittest.main()
