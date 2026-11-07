"""Tecnoalarm transport and authentication helpers."""

import os
import re
import socket
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

try:
    from cryptography.hazmat.decrepit.ciphers.modes import CFB
except ImportError:  # cryptography < 47
    from cryptography.hazmat.primitives.ciphers.modes import CFB


class AuthenticationError(OSError):
    """Panel rejected the numeric user code."""


def utf16_units(value):
    raw = value.encode("utf-16-le", errors="surrogatepass")
    return struct.unpack(f"<{len(raw) // 2}H", raw)


def direct_key(passphrase):
    if not passphrase:
        raise ValueError("Panel passphrase is required")
    # Direct passphrases are padded or truncated to 16 UTF-16 code units.
    units = utf16_units(passphrase)
    return bytes(unit & 255 for unit in (units[:16] + (32,) * max(0, 16 - len(units))))


class Connection:
    def __init__(self, address, session_key):
        self.socket = socket.create_connection(address, timeout=20)
        try:
            self.socket.settimeout(10)
            self.reset(session_key)
        except Exception:
            self.close()
            raise

    def reset(self, session_key):
        iv = os.urandom(16)
        cipher = Cipher(algorithms.AES(session_key), CFB(iv))
        self.tx = cipher.encryptor()
        self.rx = cipher.decryptor()
        self.socket.sendall(iv)

    def send(self, plaintext):
        self.socket.sendall(self.tx.update(plaintext))

    def receive(self, length):
        ciphertext = bytearray()
        while len(ciphertext) < length:
            part = self.socket.recv(length - len(ciphertext))
            if not part:
                raise EOFError("Truncated server response")
            ciphertext.extend(part)
        return self.rx.update(bytes(ciphertext))

    def close(self):
        self.socket.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def crc(data):
    value = 0xffff
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0xa001 if value & 1 else 0)
    return value


def frame(opcode, payload, utn=0, index=0):
    packet = struct.pack("<6H", 0x0900, utn, len(payload) + 6, opcode, index, len(payload)) + payload
    packet += struct.pack("<H", crc(packet))
    return b"\x10\x02" + packet.replace(b"\x10", b"\x10\x10")


def dle(connection, opcode, payload, expected, utn=0, index=0):
    connection.send(frame(opcode, payload, utn, index))
    control = connection.receive(2)
    if control == b"\x10\x0f":
        control = connection.receive(2)
    if control != b"\x10\x0c":
        raise OSError(f"Unexpected DLE response control: {control.hex()}")
    response = bytearray()
    while len(response) < expected + 14:
        byte = connection.receive(1)
        if byte == b"\x10" and connection.receive(1) != b"\x10":
            raise OSError("Invalid DLE escaping")
        response.extend(byte)
    header = struct.unpack_from("<6H", response)
    if (header != (0x0900, utn, expected + 6, opcode, index, expected)
            or struct.unpack_from("<H", response, len(response) - 2)[0] != crc(response[:-2])):
        raise OSError("Invalid DLE response header or checksum")
    return bytes(response[12:-2])


def validate_code(code):
    if not re.fullmatch(r"[0-9]{4,6}", code):
        raise ValueError("User code must contain 4..6 numeric digits")


def login(connection, appid, code):
    validate_code(code)
    if not 0 <= appid <= 0xffff:
        raise ValueError("APPID out of range")
    dle(connection, 1, b"", 10)  # Read the panel clock before login.
    packet = bytearray(48)
    struct.pack_into("<H", packet, 0, appid)
    packet[2:2 + len(code)] = bytes(ord(digit) & 15 for digit in code)
    packet[8] = 1
    reply = dle(connection, 0x0901, bytes(packet), 3)
    if reply[0] != 6:
        raise AuthenticationError("Panel authentication denied")
    return struct.unpack_from("<H", reply, 1)[0]
