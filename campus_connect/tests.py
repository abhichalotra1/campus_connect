import threading
from unittest import mock

from django.core.mail import EmailMessage
from django.test import SimpleTestCase

from campus_connect.mail import AsyncSMTPEmailBackend


def _msg():
    return EmailMessage('Hi', 'body', 'from@example.com', ['to@example.com'])


class AsyncEmailBackendTests(SimpleTestCase):
    def test_send_returns_immediately_and_delivers_in_background(self):
        delivered = threading.Event()
        release = threading.Event()
        called_from = {}

        def slow_smtp_send(self_, messages):
            called_from['thread'] = threading.current_thread()
            release.wait(timeout=5)           # simulate a slow mail server
            delivered.set()
            return len(messages)

        with mock.patch('campus_connect.mail.SMTPEmailBackend.send_messages', slow_smtp_send):
            result = AsyncSMTPEmailBackend().send_messages([_msg()])
            # returned while the "server" is still blocked => the caller was not held up
            self.assertEqual(result, 1)
            self.assertFalse(delivered.is_set())
            release.set()
            self.assertTrue(delivered.wait(timeout=5))
        self.assertIsNot(called_from['thread'], threading.main_thread())

    def test_delivery_failure_is_logged_not_raised(self):
        done = threading.Event()

        def boom(self_, messages):
            done.set()
            raise OSError('smtp down')

        with mock.patch('campus_connect.mail.SMTPEmailBackend.send_messages', boom):
            with self.assertLogs('campus_connect.mail', level='ERROR') as logs:
                AsyncSMTPEmailBackend().send_messages([_msg()])
                done.wait(timeout=5)
                # give the worker thread a moment to finish logging
                for t in threading.enumerate():
                    if t is not threading.current_thread() and t.daemon:
                        t.join(timeout=2)
        self.assertTrue(any('delivery failed' in line for line in logs.output))

    def test_empty_list_sends_nothing(self):
        self.assertEqual(AsyncSMTPEmailBackend().send_messages([]), 0)
