"""Local Quectel/Acceleronix protocol used by Wonderfree."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Iterable
import hashlib
import logging
import socket
import struct
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .const import (
    ALL_DPS,
    DEFAULT_PORT,
    DISCOVERY_PORT,
    DP_COUNTDOWN,
    DP_DISPLAY,
    DP_MODE,
    DP_OSCILLATION,
    DP_POWER,
    DP_SOUND,
    DP_SPEED,
    DP_TEMPERATURE,
)
from .models import DiscoveredDevice, FanStatus

_LOGGER = logging.getLogger(__name__)


class WonderfreeError(Exception):
    """Base protocol error."""


class WonderfreeConnectionError(WonderfreeError):
    """Connection or timeout error."""


class WonderfreeAuthenticationError(WonderfreeError):
    """Authentication failed."""


def _checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def _stuff(data: bytes) -> bytes:
    result = bytearray(data[:2])
    for index in range(2, len(data)):
        result.append(data[index])
        if (
            index + 1 < len(data)
            and data[index] == 0xAA
            and data[index + 1] in (0x55, 0xAA)
        ):
            result.append(0x55)
    return bytes(result)


def encode_frame(packet_id: int, command: int, payload: bytes = b"") -> bytes:
    """Encode one Quectel frame."""
    body = struct.pack(">HH", packet_id & 0xFFFF, command & 0xFFFF) + payload
    frame = bytearray(b"\xaa\xaa" + struct.pack(">H", len(payload) + 5) + b"\x00" + body)
    frame[4] = _checksum(frame[5:])
    return _stuff(bytes(frame))


def extract_frame(buffer: bytearray) -> bytes | None:
    """Extract and unstuff one complete frame from a stream buffer."""
    start = buffer.find(b"\xaa\xaa")
    if start < 0:
        buffer.clear()
        return None
    if start:
        del buffer[:start]
    if len(buffer) < 4:
        return None

    logical = bytearray(buffer[:2])
    raw_index = 2
    expected: int | None = None
    while raw_index < len(buffer):
        byte = buffer[raw_index]
        logical.append(byte)
        raw_index += 1
        if (
            byte == 0xAA
            and raw_index + 1 < len(buffer)
            and buffer[raw_index] == 0x55
            and buffer[raw_index + 1] in (0x55, 0xAA)
        ):
            raw_index += 1
        if expected is None and len(logical) >= 4:
            expected = 4 + struct.unpack(">H", logical[2:4])[0]
        if expected is not None and len(logical) == expected:
            del buffer[:raw_index]
            frame = bytes(logical)
            if _checksum(frame[5:]) != frame[4]:
                raise WonderfreeError("Invalid frame checksum")
            return frame
    return None


def _numeric(value: int) -> bytes:
    negative = value < 0
    magnitude = abs(value)
    raw = magnitude.to_bytes(max(1, (magnitude.bit_length() + 7) // 8), "big")
    return bytes(((0x80 if negative else 0) | (len(raw) - 1),)) + raw


def encode_ttlv(identifier: int, value: bool | int | bytes | str) -> bytes:
    """Encode one TTLV value."""
    if isinstance(value, bool):
        return struct.pack(">H", (identifier << 3) | (1 if value else 0))
    if isinstance(value, int):
        return struct.pack(">H", (identifier << 3) | 2) + _numeric(value)
    raw = value.encode() if isinstance(value, str) else value
    return struct.pack(">HH", (identifier << 3) | 3, len(raw)) + raw


def decode_ttlvs(payload: bytes) -> list[tuple[int, int, Any]]:
    """Decode a flat TTLV payload."""
    result: list[tuple[int, int, Any]] = []
    offset = 0
    while offset + 2 <= len(payload):
        tag = struct.unpack(">H", payload[offset : offset + 2])[0]
        offset += 2
        identifier, value_type = tag >> 3, tag & 7
        if value_type in (0, 1):
            value: Any = value_type == 1
        elif value_type == 2:
            if offset >= len(payload):
                raise WonderfreeError("Truncated numeric TTLV")
            header = payload[offset]
            offset += 1
            length = (header & 7) + 1
            if offset + length > len(payload):
                raise WonderfreeError("Truncated numeric value")
            value = int.from_bytes(payload[offset : offset + length], "big")
            offset += length
            if header & 0x80:
                value = -value
        elif value_type in (3, 5):
            if offset + 2 > len(payload):
                raise WonderfreeError("Truncated binary TTLV")
            length = struct.unpack(">H", payload[offset : offset + 2])[0]
            offset += 2
            if offset + length > len(payload):
                raise WonderfreeError("Truncated binary value")
            value = payload[offset : offset + length]
            offset += length
        else:
            raise WonderfreeError(f"Unsupported TTLV type {value_type}")
        result.append((identifier, value_type, value))
    return result


def parse_frame(frame: bytes) -> tuple[int, int, bytes]:
    """Return packet id, command and payload."""
    if len(frame) < 9 or frame[:2] != b"\xaa\xaa":
        raise WonderfreeError("Invalid frame")
    return struct.unpack(">HH", frame[5:9]) + (frame[9:],)


def parse_discovery(frame: bytes, source_host: str) -> DiscoveredDevice | None:
    """Parse a discovery response."""
    _, command, payload = parse_frame(frame)
    if command != 0x7031:
        return None
    values = {identifier: value for identifier, _, value in decode_ttlvs(payload)}
    try:
        product_key = bytes(values[3]).decode()
        device_key = bytes(values[4]).decode()
        host = bytes(values[5]).decode() or source_host
        port = int(values.get(6, DEFAULT_PORT))
    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as err:
        raise WonderfreeError("Invalid discovery response") from err
    return DiscoveredDevice(
        host=host,
        port=port,
        product_key=product_key,
        device_key=device_key,
        name=f"OmniBreeze Tower Fan_{device_key[-4:]}",
    )


def discover_devices(broadcast_addresses: list[str] | None = None, device_addresses: list[str] | None = None, timeout: float = 2.0,) -> list[DiscoveredDevice]:
    """Discover Wonderfree devices using the proprietary UDP broadcast."""
    _LOGGER.debug("Received discovery input Broadcast addresses: %s Device addresses: %s", broadcast_addresses, device_addresses)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.2)
    devices: dict[str, DiscoveredDevice] = {}
    try:
        try:
            sock.bind(("", DISCOVERY_PORT))
            _LOGGER.debug("Bound discovery port: %s", DISCOVERY_PORT)
        except OSError as err:
            sock.bind(("", 0))
            _LOGGER.debug("Bind to %s failed (%s), using ephemeral port", DISCOVERY_PORT, err)
        destinations = {
            "255.255.255.255",
            *(broadcast_addresses or []),
            *(device_addresses or []),
        }

        payload = encode_frame(1000, 0x7030)

        for address in destinations:
            _LOGGER.debug("Sending discovery packet to %s:%s", address, DISCOVERY_PORT)
            sock.sendto(payload, (address, DISCOVERY_PORT))

        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, address = sock.recvfrom(2048)
            except TimeoutError:
                continue
            _LOGGER.debug("RX from %s: %s", address, data.hex())
            buffer = bytearray(data)
            frame = extract_frame(buffer)
            if frame is None:
                _LOGGER.debug("extract_frame rejected it")
                continue
            device = parse_discovery(frame, address[0])
            if device is not None:
                _LOGGER.debug("Found device with key: %s", device.device_key)
                devices[device.device_key] = device
    finally:
        sock.close()
    return list(devices.values())


class WonderfreeClient:
    """Persistent local client for one Wonderfree fan."""

    def __init__(self, host: str, port: int, auth_key: str) -> None:
        self.host = host
        self.port = port
        try:
            self._key = base64.b64decode(auth_key, validate=True)
        except ValueError as err:
            raise WonderfreeAuthenticationError("Invalid Base64 auth key") from err
        if len(self._key) != 16:
            raise WonderfreeAuthenticationError("Auth key must decode to 16 bytes")
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._buffer = bytearray()
        self._sequence = 1000
        self._iv: bytes | None = None
        self._lock = asyncio.Lock()

    def _next_sequence(self) -> int:
        self._sequence = 1000 if self._sequence >= 65534 else self._sequence + 1
        return self._sequence

    def _crypt(self, payload: bytes, *, decrypt: bool = False) -> bytes:
        if self._iv is None:
            return payload
        cipher = Cipher(algorithms.AES(self._key), modes.CBC(self._iv))
        if decrypt:
            decryptor = cipher.decryptor()
            padded = decryptor.update(payload) + decryptor.finalize()
            unpadder = padding.PKCS7(128).unpadder()
            return unpadder.update(padded) + unpadder.finalize()
        padder = padding.PKCS7(128).padder()
        padded = padder.update(payload) + padder.finalize()
        encryptor = cipher.encryptor()
        return encryptor.update(padded) + encryptor.finalize()

    async def connect(self) -> None:
        """Connect and authenticate if necessary."""
        if self._writer is not None and not self._writer.is_closing():
            return
        await self.disconnect()
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port), 5
            )
            self._iv = None
            await self._send(0x7032)
            _, command, payload = await self._receive(3)
            if command != 0x7033:
                raise WonderfreeAuthenticationError("Missing authentication challenge")
            nonce = next(
                value for identifier, _, value in decode_ttlvs(payload) if identifier == 1
            )
            if not isinstance(nonce, bytes) or len(nonce) != 16:
                raise WonderfreeAuthenticationError("Invalid authentication nonce")
            digest = hashlib.sha256(
                (self._key.hex() + ";" + nonce.decode()).encode()
            ).hexdigest()
            await self._send(0x7034, encode_ttlv(2, digest))
            _, command, payload = await self._receive(3)
            if command != 0x7035:
                raise WonderfreeAuthenticationError("Missing authentication response")
            status = next(
                (value for identifier, _, value in decode_ttlvs(payload) if identifier == 3),
                -1,
            )
            if status != 0:
                raise WonderfreeAuthenticationError(f"Device rejected auth key ({status})")
            self._iv = nonce
            await self._send(0x7039, encode_ttlv(1, 30) + encode_ttlv(2, 1))
        except WonderfreeError:
            await self.disconnect()
            raise
        except (OSError, asyncio.TimeoutError, UnicodeDecodeError) as err:
            await self.disconnect()
            raise WonderfreeConnectionError(str(err)) from err

    async def disconnect(self) -> None:
        """Close the TCP connection."""
        writer, self._writer = self._writer, None
        self._reader = None
        self._buffer.clear()
        self._iv = None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    async def _send(self, command: int, payload: bytes = b"") -> None:
        if self._writer is None:
            raise WonderfreeConnectionError("Not connected")
        encrypted = self._crypt(payload) if payload and self._iv is not None else payload
        self._writer.write(encode_frame(self._next_sequence(), command, encrypted))
        await self._writer.drain()

    async def _receive(self, timeout: float) -> tuple[int, int, bytes]:
        if self._reader is None:
            raise WonderfreeConnectionError("Not connected")
        async def _read() -> tuple[int, int, bytes]:
            while True:
                frame = extract_frame(self._buffer)
                if frame is not None:
                    packet_id, command, payload = parse_frame(frame)
                    if payload and self._iv is not None:
                        payload = self._crypt(payload, decrypt=True)
                    return packet_id, command, payload
                chunk = await self._reader.read(1024)
                if not chunk:
                    raise WonderfreeConnectionError("Connection closed by device")
                self._buffer.extend(chunk)
        try:
            return await asyncio.wait_for(_read(), timeout)
        except asyncio.TimeoutError as err:
            raise WonderfreeConnectionError("Device response timed out") from err

    async def read_status(self) -> FanStatus:
        """Read all supported data points."""
        async with self._lock:
            await self.connect()
            await self._send(17, b"".join(struct.pack(">H", dp) for dp in ALL_DPS))
            values: dict[int, Any] = {}
            try:
                while len(values) < len(ALL_DPS):
                    _, command, payload = await self._receive(2)
                    if command not in (20, 50):
                        continue
                    for identifier, _, value in decode_ttlvs(payload):
                        if identifier in ALL_DPS:
                            values[identifier] = value
            except WonderfreeError:
                await self.disconnect()
                raise
            _LOGGER.debug("Read status: %s", values)
            missing = set(ALL_DPS) - values.keys()
            if missing:
                raise WonderfreeError(f"Missing data points: {sorted(missing)}")
            return FanStatus(
                power=bool(values[DP_POWER]),
                mode=int(values[DP_MODE]),
                speed=int(values[DP_SPEED]),
                oscillating=bool(values[DP_OSCILLATION]),
                sound=bool(values[DP_SOUND]),
                display=bool(values[DP_DISPLAY]),
                temperature=int(values[DP_TEMPERATURE]),
                countdown=int(values[DP_COUNTDOWN]),
            )

    async def write(self, values: Iterable[tuple[int, bool | int]]) -> FanStatus:
        """Write data points and return confirmed state."""
        async with self._lock:
            await self.connect()
            payload = b"".join(encode_ttlv(identifier, value) for identifier, value in values)
            await self._send(19, payload)
            try:
                await self._receive(1)
            except WonderfreeConnectionError:
                pass
        return await self.read_status()
