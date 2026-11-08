"""Synchronous read-only Tecnoalarm panel client."""

import ipaddress
import re
import threading

from . import auth
from .status import (LAYOUTS, authorized_indices, decode_identity, decode_status,
                     description_size, permission_size)

READ_OPCODES = frozenset({0x0909, 0x090A, 0x0903, 0x090D, 0x0924, 0x090E})


def validate_config(host, port, appid, passphrase, user_code):
    if not isinstance(host, str) or not host or host != host.strip() or any(
            c.isspace() or ord(c) < 33 for c in host) or "/" in host or "://" in host:
        raise ValueError("Host must be a hostname or IP address")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        try:
            hostname = host.removesuffix(".").encode("idna").decode("ascii")
        except UnicodeError:
            raise ValueError("Invalid hostname") from None
        if (len(hostname) > 253 or re.fullmatch(r"[0-9.]+", hostname)
                or any(not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                       for label in hostname.split("."))):
            raise ValueError("Invalid hostname")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("TCP port must be between 1 and 65535")
    if not isinstance(appid, str) or not re.fullmatch(r"[0-9a-fA-F]{1,4}", appid):
        raise ValueError("APPID must contain 1..4 hexadecimal digits")
    if not isinstance(passphrase, str) or not passphrase.strip():
        raise ValueError("Set TCS_PASSPHRASE before login")
    if not isinstance(user_code, str):
        raise ValueError("TCS_USER_CODE must contain 4..6 numeric digits")
    auth.validate_code(user_code)


class Client:
    def __init__(self, host, port, appid, passphrase, user_code, *, persistent_connection=True):
        validate_config(host, port, appid, passphrase, user_code)
        if type(persistent_connection) is not bool:
            raise ValueError("Persistent connection must be a boolean")
        self._persistent_connection = persistent_connection
        self.address = (host, port)
        self._appid = int(appid, 16)
        self._key = auth.direct_key(passphrase)
        self._code = user_code
        self._lock = threading.Lock()
        self._connection = None
        self._utn = None
        self._closed = False

    def authenticate(self):
        with self._lock, auth.Connection(self.address, self._key) as connection:
            auth.login(connection, self._appid, self._code)

    def read_status(self):
        # Keep socket and cipher state serialized, even if the async caller is cancelled.
        with self._lock:
            if self._closed:
                raise OSError("Client is closed")
            reused = self._connection is not None
            for attempt in range(2):
                try:
                    if self._connection is None:
                        self._connection = auth.Connection(self.address, self._key)
                        self._utn = auth.login(self._connection, self._appid, self._code)
                    result = self._read_status()
                    if not self._persistent_connection:
                        self._disconnect()
                    return result
                except (OSError, EOFError):
                    self._disconnect()
                    if not reused or attempt:
                        raise
                except BaseException:
                    self._disconnect()
                    raise

    def _disconnect(self):
        connection, self._connection = self._connection, None
        self._utn = None
        if connection is not None:
            connection.close()

    def keep_alive(self):
        with self._lock:
            if self._connection is None or self._closed:
                return
            try:
                # The app reads the panel clock on an authenticated session too.
                auth.dle(self._connection, 1, b"", 10, utn=self._utn)
            except BaseException:
                self._disconnect()
                raise

    def close(self):
        with self._lock:
            self._closed = True
            self._disconnect()

    def disconnect(self):
        """Release the panel session, allowing a later status read to reconnect."""
        with self._lock:
            self._disconnect()

    def _read_status(self):
        def read(opcode, size, index=0):
            if opcode not in READ_OPCODES:
                raise ValueError("Read-only opcode required")
            return auth.dle(self._connection, opcode, b"", size, utn=self._utn, index=index)

        identity_raw = read(0x0909, 16)
        identity = decode_identity(identity_raw)
        model = identity["model_id"]
        permissions = read(0x090A, permission_size(model), self._utn)
        opcode, size, _, _ = LAYOUTS[model]
        groups = read(opcode, size)
        panel_status = read(0x090E, 16)
        descriptions = {
            index: read(0x0903, description_size(model), index)
            for index in authorized_indices(model, permissions)
        }
        return decode_status(identity_raw, permissions, groups, panel_status, descriptions)
