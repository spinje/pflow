# MERIDIAN Protocol v1.2 — Reference Specification (Extended)

This document specifies the MERIDIAN protocol, a fictional message-passing
substrate used as a stable reference body for prompt-cache verification.
It is intentionally verbose and self-contained so the same bytes can be
sent to an LLM more than once. The extended edition adds chapters on
state machines, congestion control, observability, and operational
guidance to comfortably exceed Gemini's ~4096-token explicit-cache
threshold.

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

## 8. State Machine

Every MERIDIAN endpoint maintains two layered state machines: a
connection-level machine that tracks the lifecycle states described in
Section 2, and a per-stream machine that tracks individual streams
inside the connection.

### 8.1 Connection States

Five connection states are defined: IDLE, CONNECTING, ESTABLISHED,
DRAINING, CLOSED. The legal transitions are:

- IDLE → CONNECTING: on send or receive of CONNECT.
- CONNECTING → ESTABLISHED: on negotiated CONNECT exchange completion.
- CONNECTING → CLOSED: on ERROR `0x0020`–`0x002F` during handshake.
- ESTABLISHED → DRAINING: on send or receive of CLOSE.
- DRAINING → CLOSED: on receipt of the matching CLOSE.
- ESTABLISHED → CLOSED: on fatal ERROR (`0x0030`–`0x003F` liveness;
  `0x0050`–`0x005F` auth; `0x0060`–`0x006F` resource).

Endpoints MUST reject frames inappropriate for the current state. For
example, DATA frames received in IDLE or CONNECTING MUST trigger
`0x0014` (UNEXPECTED_FRAME) and CLOSE.

### 8.2 Stream States

Each stream maintains its own state machine: OPEN, HALF_CLOSED_LOCAL,
HALF_CLOSED_REMOTE, CLOSED. A stream opens when the first DATA frame
is sent on its identifier. An endpoint signals end-of-stream by setting
the FIN bit in the frame-type field's high bit. Both endpoints close
their write half independently; the stream is fully CLOSED when both
have signalled FIN. Endpoints MUST NOT send DATA on a closed write
half. Receiving DATA on a half that has already been closed MUST
trigger `0x0040` (STREAM_HALF_CLOSED) and ERROR-close the connection.

### 8.3 Reset Semantics

A RESET pseudo-frame (frame type `0x07`) cancels a stream without
graceful drain. Both halves transition immediately to CLOSED. RESET
frames carry an application-defined reason code in the first 4 payload
bytes. Receivers MUST NOT generate ACKs for RESET frames. RESET MUST
NOT be sent before the stream has reached OPEN; doing so triggers
`0x0041` (RESET_BEFORE_OPEN).

## 9. Congestion Control

MERIDIAN combines per-stream flow control with connection-level
congestion control. The congestion control algorithm is loosely based
on TCP CUBIC, adapted for the connection-level scope.

### 9.1 Congestion Window

Each endpoint maintains a congestion window in bytes (`cwnd`). The
window starts at 14×MSS where MSS is the negotiated maximum frame
size. The window grows linearly during the steady state and follows
a cubic function after a loss event. Frames that fail to ACK within
the timeout count as a loss; the sender MUST halve `cwnd` to a
floor of 2×MSS.

### 9.2 Slow Start

During the first 100ms after ESTABLISHED, MERIDIAN runs in slow start
mode: `cwnd` doubles for each successful round trip until it reaches
the slow-start threshold (`ssthresh`, default 64KB) or a loss event
occurs. After slow start, the algorithm transitions to congestion
avoidance.

### 9.3 Pacing

Senders SHOULD pace outgoing frames so that no more than `cwnd / RTT`
bytes are released per second. Bursting beyond this rate amplifies
loss in shared networks. Pacing tokens reset every 5ms.

### 9.4 ECN Support

If both endpoints advertise ECN capability (capability flag bit 4),
they MAY mark frames with ECN-CE in the IP layer. Receiving an ECN-CE
mark causes the receiver to set the ECN-Echo bit in the next ACK,
which the sender treats as equivalent to a single packet loss for
`cwnd` adjustment purposes (multiplicative decrease, no fast
retransmit).

## 10. Observability

MERIDIAN endpoints SHOULD expose the following metrics for operations
teams to consume:

### 10.1 Per-Connection Metrics

- `meridian_connections_active`: gauge, current ESTABLISHED count.
- `meridian_connections_total`: counter, sum of connections ever opened.
- `meridian_bytes_sent_total`: counter, payload bytes egress.
- `meridian_bytes_received_total`: counter, payload bytes ingress.
- `meridian_handshake_failures_total{code}`: counter labelled by
  failure code (`0x0020`–`0x002F`).
- `meridian_rtt_seconds{quantile}`: histogram of round-trip time.

### 10.2 Per-Stream Metrics

- `meridian_streams_active`: gauge, current OPEN count.
- `meridian_stream_window_bytes{stream}`: gauge, current flow window.
- `meridian_resets_total{reason}`: counter labelled by application
  reason code.

### 10.3 Sampling

The metric volume on a busy endpoint can dominate the host's metric
budget. Implementations SHOULD support per-stream metric sampling at
configurable rates (default 1:100 for high-cardinality labels). The
aggregate counters MUST NOT be sampled — only the labelled
disaggregations.

### 10.4 Tracing

When the deployment includes a distributed tracing system,
implementations SHOULD propagate trace context in the optional
trace-context capability field of CONNECT and DATA frames. The trace
context follows the W3C Trace Context recommendation: a 16-byte
trace-id, 8-byte span-id, and 1-byte trace-flags field.

## 11. Operational Guidance

This section captures lessons learned from production deployments of
MERIDIAN. It is non-normative but reflects established practice.

### 11.1 Tuning Heartbeats

The default 10-second heartbeat interval works for most deployments
but is too aggressive on networks with measurable packet loss. On
intercontinental links, heartbeat misses can spike the connection
close rate even though the connection is functionally healthy.
Operators SHOULD tune the interval and miss-tolerance together: longer
intervals reduce false positives at the cost of slower failure
detection.

### 11.2 Window Sizing

A 64KB receive window suffices for low-latency local-area connections.
For long-fat-network deployments (RTT > 50ms, bandwidth > 1Gbps), the
window must grow proportionally to the bandwidth-delay product. A
common operational error is to advertise a fixed window across all
deployment classes; this caps throughput well below link capacity on
the long-fat case.

### 11.3 Authentication

Although MERIDIAN itself does not specify authentication, the
challenge field is the natural place to embed application-layer
credentials. Production deployments commonly use a short-lived JWT
signed with EdDSA, or a HMAC-SHA256 token derived from a shared
secret. Avoid embedding long-lived bearer tokens; the CONNECT frame
is replayable once captured.

### 11.4 Migration

When migrating from MERIDIAN v1.0 or v1.1 to v1.2, run mixed-version
traffic in production for at least 30 days before disabling the older
versions. The capability-flags field is the only reliable indicator of
version compatibility; the version negotiation in the CONNECT frame
fails closed (older endpoints reject unknown versions outright), so
gradual rollout requires both endpoints to advertise v1.2 capability
flags before either side enforces v1.2-only behaviour.

### 11.5 Capacity Planning

For a single endpoint serving N concurrent connections, expect:

- Memory: ~12KB per active connection plus ~3KB per active stream.
- CPU: ~0.5% of one core per 1,000 frames-per-second under default
  configuration. CRC-32C dominates the CPU budget; deployments with
  hardware CRC offload can reduce this by ~70%.
- File descriptors: 1 per connection, regardless of stream count.

These figures assume a 64KB receive window. Larger windows increase
memory linearly.

### 11.6 Debugging Hints

When a MERIDIAN connection misbehaves in production, the first three
diagnostic steps are: capture the CONNECT-frame negotiation, dump the
heartbeat sequence numbers and round-trip times, and examine the
ERROR-frame history. Most production incidents resolve into one of
five categories: misconfigured maximum frame size, mismatched
capability flags, expired authentication tokens, asymmetric flow
windows, or third-party middleboxes corrupting the alignment padding.

## 12. Future Work

The MERIDIAN working group is considering several extensions for v1.3:

- 0-RTT reconnection using session tickets.
- Optional payload compression negotiated per-stream rather than
  per-connection.
- A DATAGRAM frame type for unreliable, unordered delivery.
- Multi-path support, allowing a single connection to span multiple
  network paths.

These extensions are exploratory and MUST NOT be relied upon by v1.2
implementations. They are listed here so operators can budget for the
likely shape of future upgrades.

## 13. Wire Format Reference

This appendix gathers all wire-format details into a single reference
table for implementers.

### 13.1 Frame Type Values

| Value | Name      | Direction       | ACK required |
|-------|-----------|-----------------|--------------|
| 0x01  | CONNECT   | initiator first | yes          |
| 0x02  | DATA      | both            | yes          |
| 0x03  | ACK       | both            | no           |
| 0x04  | HEARTBEAT | both            | yes          |
| 0x05  | CLOSE     | both            | yes          |
| 0x06  | ERROR     | both            | no           |
| 0x07  | RESET     | both            | no           |

The high bit of the frame-type byte (0x80) carries the FIN flag for
DATA frames. All other frame types MUST clear the FIN bit.

### 13.2 Capability Flags

| Bit | Meaning                                |
|-----|----------------------------------------|
| 0   | Compression supported                  |
| 1   | Tracing context propagation            |
| 2   | Authentication required                |
| 3   | Reserved for v1.3 0-RTT                |
| 4   | ECN-aware congestion signalling        |
| 5   | DATAGRAM frame support (v1.3 preview)  |
| 6   | Reserved                               |
| 7   | v1.2 capability acknowledgement        |

### 13.3 Compression Codes

The compression-code field is 4 bits wide:

- 0: identity (no compression).
- 1: zstd level 3.
- 2: zstd level 9.
- 3: snappy.
- 4: brotli quality 5 (v1.2 only; advertise via capability bit 0).
- 5–15: reserved for future use.

Endpoints MUST advertise supported compression codes during the
CONNECT handshake. The compression code applies only to DATA frame
payloads; control frames are always sent uncompressed so middleboxes
can inspect them.

### 13.4 Maximum Frame Size

The default maximum frame size is 16,384 bytes. Endpoints MAY negotiate
a smaller value during CONNECT (minimum 1,024) but MUST NOT negotiate
a larger value than 65,535 bytes minus header overhead. Choosing a
small frame size increases header overhead per byte transmitted; the
recommended floor for production deployments is 4,096.

### 13.5 Round-Trip Time Estimation

The recommended RTT estimator follows RFC 6298:

```
SRTT  = (1 - alpha) * SRTT  + alpha * RTTm
RTTVAR = (1 - beta) * RTTVAR + beta * |SRTT - RTTm|
RTO    = SRTT + 4 * RTTVAR
```

with alpha = 1/8 and beta = 1/4. Implementations SHOULD floor RTO at
200ms and cap it at 60 seconds. The first measurement initialises
SRTT directly: `SRTT = RTTm; RTTVAR = RTTm / 2`. ECN-CE marks do not
contribute to RTT samples (they are neither losses nor clean ACKs).

## 14. Glossary

For convenience, this glossary collects the protocol-specific
terminology used throughout the document.

- **Frame**: the atomic unit of transmission, header plus optional
  payload, aligned to 8 bytes.
- **Stream**: an ordered, reliable, flow-controlled sequence of DATA
  frames sharing a stream identifier within a connection.
- **Endpoint**: one side of a MERIDIAN connection. Endpoints are not
  inherently client or server; either side may initiate.
- **Initiator**: the endpoint that sent the first CONNECT frame.
- **Responder**: the endpoint that received the first CONNECT frame
  and replied.
- **Capability flag**: a 1-bit field in the CONNECT payload that
  advertises optional protocol features; both endpoints must set the
  bit for the feature to be in use.
- **MSS**: maximum segment size, the negotiated maximum frame size in
  bytes.
- **cwnd**: congestion window in bytes; the maximum number of unacked
  bytes the sender may have outstanding.
- **ssthresh**: slow-start threshold; the cwnd value above which the
  sender transitions from slow start to congestion avoidance.
