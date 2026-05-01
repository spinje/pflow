# MERIDIAN Protocol v1.2 — Reference Specification

This document specifies the MERIDIAN protocol, a fictional message-passing
substrate used as a stable reference body for prompt-cache verification.
It is intentionally verbose and self-contained so the same bytes can be
sent to an LLM more than once.

## 1. Frame Layout

Every MERIDIAN frame consists of a 24-byte header followed by an optional
payload. The header layout is fixed across all frame versions:

- Bytes 0–3: magic value `0x4D45524E` (ASCII "MERN") in little-endian.
- Bytes 4–5: protocol version, currently `0x0102` for v1.2.
- Bytes 6–7: frame type, one of CONNECT (0x01), DATA (0x02), ACK (0x03),
  HEARTBEAT (0x04), CLOSE (0x05), or ERROR (0x06).
- Bytes 8–11: stream identifier, an unsigned 32-bit integer assigned at
  connect time.
- Bytes 12–15: sequence number within the stream, monotonically increasing.
- Bytes 16–19: payload length in bytes, capped at 65,535.
- Bytes 20–23: CRC-32C of the payload, or zero when the payload is empty.

Frames are aligned on 8-byte boundaries. Implementations MUST pad the
payload with zero bytes to maintain alignment and MUST NOT include the
padding in the payload-length field. Endpoints that observe a misaligned
frame MUST close the stream with ERROR code `0x0011` (FRAME_ALIGNMENT).

## 2. Connection Lifecycle

A MERIDIAN connection passes through five states: IDLE, CONNECTING,
ESTABLISHED, DRAINING, and CLOSED. Transitions are driven by frame
exchange, not by timers.

### 2.1 Connect Handshake

The initiator sends a CONNECT frame with a payload containing the proposed
session parameters: maximum frame size, supported compression codes,
authentication challenge, and capability flags. The responder replies
with either a CONNECT frame echoing the negotiated parameters, or an
ERROR frame with one of the connect-failure codes (`0x0020` through
`0x002F`). A responder that does not understand the proposed version
MUST reply with ERROR `0x0021` (VERSION_UNSUPPORTED) and include the
highest version it supports in the payload.

### 2.2 Established State

In the ESTABLISHED state, both endpoints may send DATA, ACK, and
HEARTBEAT frames. DATA frames carry application bytes and require an
ACK within the configured ack timeout (default 250ms). Endpoints SHOULD
coalesce ACK frames covering contiguous sequence ranges to reduce
overhead. HEARTBEAT frames are sent every 10 seconds in the absence of
other traffic; three missed heartbeats terminate the connection with
CLOSE code `0x0030` (PEER_UNRESPONSIVE).

### 2.3 Draining

Either endpoint may initiate a graceful close by sending a CLOSE frame
with reason code `0x0000` (NORMAL_SHUTDOWN). The peer transitions to
DRAINING, completes outstanding ACKs, then sends its own CLOSE frame.
After both CLOSE frames have been exchanged, both sides transition to
CLOSED and free the stream identifier. Stream identifiers MUST NOT be
reused for at least 60 seconds after CLOSED.

## 3. Stream Multiplexing

A MERIDIAN connection may carry up to 1024 concurrent streams. Stream
identifiers are assigned by the initiator and must be unique within the
connection lifetime. Identifiers in the range `0x00000001`–`0x000003FF`
are reserved for control streams; application streams use identifiers
`0x00000400` and above.

Flow control is per-stream. Each endpoint advertises a receive window in
bytes during the CONNECT handshake; the peer MUST NOT have more than
that many unacknowledged DATA bytes in flight on a given stream. Window
updates travel in ACK frames, in the optional `window_delta` field.
Receivers SHOULD send window updates eagerly when their available window
drops below 25% of the negotiated maximum to avoid stalls.

## 4. Error Codes

Error codes are 16-bit unsigned integers grouped by class:

- `0x0000`–`0x000F`: graceful conditions (NORMAL_SHUTDOWN and reserved).
- `0x0010`–`0x001F`: framing errors. Sender violated the wire format.
- `0x0020`–`0x002F`: handshake errors. Negotiation failed.
- `0x0030`–`0x003F`: liveness errors. Peer unresponsive or timed out.
- `0x0040`–`0x004F`: stream errors. Per-stream protocol violations.
- `0x0050`–`0x005F`: authentication errors. Credentials rejected.
- `0x0060`–`0x006F`: resource errors. Out of memory, too many streams.
- `0x0070`–`0x007F`: application-defined errors. Forwarded as-is.

Endpoints receiving an error code outside the defined ranges MUST treat
it as `0x0001` (UNKNOWN_ERROR) and log the original code for diagnostics.

## 5. Heartbeat and Keep-Alive

HEARTBEAT frames carry a 64-bit nonce in the payload. The receiver MUST
echo the nonce back in the next HEARTBEAT or ACK frame within 1 second.
Heartbeat round-trip times feed the adaptive ack-timeout estimator;
implementations SHOULD smooth measurements with a weighted moving
average using factor 0.125 (RFC 6298 style).

## 6. Compatibility Rules

A v1.2 endpoint MUST interoperate with v1.0 and v1.1 peers by negotiating
the highest common version during the connect handshake. Capabilities
introduced in v1.2 (compression code 4, capability flag bit 7) MUST be
disabled when speaking to a peer that did not advertise them. Future
extensions are permitted via the capability-flags field, but endpoints
MUST NOT change the meaning of existing flag bits.

## 7. Security Considerations

MERIDIAN does not specify transport encryption. Deployments SHOULD run
MERIDIAN inside an authenticated, encrypted carrier such as TLS 1.3 or
QUIC. The CONNECT-frame challenge field MAY carry an application-defined
authentication payload (HMAC tag, signed token, etc.) but the protocol
itself does not validate it.
