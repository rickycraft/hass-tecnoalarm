"""Persistent client sessions and serialized cleanup, without network access."""

import threading
import unittest
import warnings
from unittest.mock import MagicMock, patch

from cryptography.utils import CryptographyDeprecationWarning

from custom_components.tecnoalarm.client import Client, auth

CONFIG = dict(host="192.0.2.10", port=10001, appid="0462",
              passphrase="test-passphrase", user_code="0123")


class ClientTests(unittest.TestCase):
    def test_connection_cfb_known_vector_without_deprecation_warning(self):
        key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
        iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        plaintext = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")
        ciphertext = bytes.fromhex("3b3fd92eb72dad20333449f8e83cfb4a")
        with warnings.catch_warnings():
            warnings.simplefilter("error", CryptographyDeprecationWarning)
            with patch.object(auth.socket, "create_connection") as connect, \
                    patch.object(auth.os, "urandom", return_value=iv):
                connect.return_value.recv.return_value = ciphertext
                with auth.Connection(("192.0.2.10", 10001), key) as connection:
                    connection.send(plaintext)
                    connect.return_value.sendall.assert_any_call(iv)
                    connect.return_value.sendall.assert_called_with(ciphertext)
                    self.assertEqual(connection.receive(16), plaintext)

    def test_per_poll_mode_logs_in_and_closes_every_time(self):
        client = Client(**CONFIG, persistent_connection=False)
        sockets = [MagicMock(), MagicMock()]
        with patch.object(auth, "Connection", side_effect=sockets) as connection, \
                patch.object(auth, "login", side_effect=[2, 3]) as login, \
                patch.object(auth, "dle") as dle, \
                patch.object(client, "_read_status", return_value={"ok": True}):
            for index in range(2):
                self.assertEqual(client.read_status(), {"ok": True})
                self.assertEqual(login.call_count, index + 1)
                sockets[index].close.assert_called_once_with()
                self.assertIsNone(client._connection)
                self.assertIsNone(client._utn)
                client.keep_alive()
            self.assertEqual(connection.call_count, 2)
            dle.assert_not_called()
            client.close()

    def test_per_poll_failure_closes_without_retry(self):
        client = Client(**CONFIG, persistent_connection=False)
        with patch.object(auth, "Connection") as connection, \
                patch.object(auth, "login", return_value=2), \
                patch.object(client, "_read_status", side_effect=EOFError()):
            with self.assertRaises(EOFError):
                client.read_status()
            connection.assert_called_once()
            connection.return_value.close.assert_called_once_with()
            self.assertIsNone(client._connection)

    def test_invalid_connection_option_never_connects(self):
        with patch.object(auth, "Connection") as connection:
            with self.assertRaises(ValueError):
                Client(**CONFIG, persistent_connection="false")
            connection.assert_not_called()

    def test_reuses_connection_and_login_then_closes(self):
        client = Client(**CONFIG)
        with patch.object(auth, "Connection") as connection, \
                patch.object(auth, "login", return_value=2) as login, \
                patch.object(client, "_read_status", return_value={"ok": True}):
            self.assertEqual(client.read_status(), {"ok": True})
            self.assertEqual(client.read_status(), {"ok": True})
            connection.assert_called_once()
            login.assert_called_once_with(connection.return_value, 0x0462, "0123")
            connection.return_value.close.assert_not_called()
            client.close()
            client.close()
            connection.return_value.close.assert_called_once()
            with self.assertRaisesRegex(OSError, "closed"):
                client.read_status()
            connection.assert_called_once()

    def test_expired_session_reauthenticates_and_retries_only_once(self):
        client = Client(**CONFIG)
        sockets = [MagicMock(), MagicMock(), MagicMock()]
        with patch.object(auth, "Connection", side_effect=sockets) as connection, \
                patch.object(auth, "login", side_effect=[2, 3, 4]) as login, \
                patch.object(client, "_read_status", side_effect=["first", EOFError(), "second",
                                                                OSError(), OSError()]) as read:
            self.assertEqual(client.read_status(), "first")
            self.assertEqual(client.read_status(), "second")
            sockets[0].close.assert_called_once()
            self.assertIs(client._connection, sockets[1])
            self.assertEqual(client._utn, 3)
            with self.assertRaises(OSError):
                client.read_status()
            self.assertEqual(connection.call_count, 3)
            self.assertEqual(login.call_count, 3)
            self.assertEqual(read.call_count, 5)
            for sock in sockets:
                sock.close.assert_called_once()
            self.assertIsNone(client._connection)
            self.assertIsNone(client._utn)

    def test_failed_new_login_is_closed_without_retry(self):
        for failure in (auth.AuthenticationError(), EOFError()):
            with self.subTest(error=type(failure).__name__), \
                    patch.object(auth, "Connection") as connection, \
                    patch.object(auth, "login", side_effect=failure) as login:
                client = Client(**CONFIG)
                with self.assertRaises(type(failure)):
                    client.read_status()
                login.assert_called_once()
                connection.return_value.close.assert_called_once()
                self.assertIsNone(client._connection)

    def test_invalid_status_discards_session(self):
        client = Client(**CONFIG)
        with patch.object(auth, "Connection") as connection, \
                patch.object(auth, "login", return_value=2), \
                patch.object(client, "_read_status", side_effect=ValueError()):
            with self.assertRaises(ValueError):
                client.read_status()
            connection.return_value.close.assert_called_once()
            connection.assert_called_once()

    def test_keep_alive_uses_existing_auth_and_discards_failed_session(self):
        client = Client(**CONFIG)
        with patch.object(auth, "Connection") as connection, \
                patch.object(auth, "login", return_value=2) as login, \
                patch.object(auth, "dle") as dle, \
                patch.object(client, "_read_status", return_value={}):
            client.keep_alive()
            connection.assert_not_called()
            client.read_status()
            client.keep_alive()
            dle.assert_called_once_with(connection.return_value, 1, b"", 10, utn=2)
            login.assert_called_once()
            dle.side_effect = EOFError()
            with self.assertRaises(EOFError):
                client.keep_alive()
            connection.return_value.close.assert_called_once()
            self.assertIsNone(client._connection)
            client.keep_alive()
            connection.assert_called_once()
            client.close()
            client.keep_alive()
            connection.assert_called_once()

    def test_close_waits_for_inflight_poll(self):
        client = Client(**CONFIG)
        entered, release = threading.Event(), threading.Event()

        def read():
            entered.set()
            return release.wait(3)

        with patch.object(auth, "Connection") as connection, \
                patch.object(auth, "login", return_value=2), \
                patch.object(client, "_read_status", side_effect=read):
            worker = threading.Thread(target=client.read_status)
            worker.start()
            self.assertTrue(entered.wait(3))
            closer = threading.Thread(target=client.close)
            closer.start()
            connection.return_value.close.assert_not_called()
            release.set()
            worker.join(3)
            closer.join(3)
            self.assertFalse(worker.is_alive())
            self.assertFalse(closer.is_alive())
            connection.return_value.close.assert_called_once()
