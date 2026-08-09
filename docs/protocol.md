# Wire Protocol

Newline-delimited JSON over TCP, UTF-8, port 5000 by default. One message per
line. `json.dumps` escapes newlines inside string values, so a serialised
message can never contain a bare `\n` of its own — the delimiter is unambiguous
and a `readline()`-based reader is safe.

Authoritative definitions live in `common/constants.py` (every type name) and
`common/protocol.py` (construction, encoding, envelope validation). This
document explains them; where the two disagree, the code is right.

## Envelope

Every message, in both directions:

```json
{
  "type": "APP_DATA",
  "timestamp": "2026-08-09T14:32:01.482Z",
  "client_id": "lab1-pc-07",
  "payload": { }
}
```

| Field | Required | Notes |
|---|---|---|
| `type` | yes | Non-empty string, one of the types below |
| `timestamp` | yes | ISO-8601 UTC, millisecond precision, trailing `Z` |
| `payload` | yes | Object. May be empty, never absent or a non-object |
| `client_id` | contextual | The peer a message is from, or the client it concerns |
| `command_id` | commands | Names one execution; see below |
| `admin_id` | admin→engine | Recorded in `command_log.admin_id` |
| `trace_id` | optional | Follows one message through the Engine; see below |

`validate_message` enforces only `type` and `payload`. Payload *contents* are
the receiving handler's business — the envelope check exists so a handler can
rely on those two fields and nothing more.

Timestamps are stored the same way they travel: fixed-width ISO-8601 strings, so
lexicographic comparison is chronological and `WHERE timestamp >= ?` works
directly against a string bound parameter.

### `command_id` vs `trace_id`

Two identifiers with different lifetimes, and conflating them causes confusion.

- **`command_id`** (`cmd_<12 hex>`) names one *execution*. A script keys its log
  file and its termination request off it, and it lives as long as the script
  does. **Every dispatch gets its own, even in a broadcast** — a shared id would
  duplicate audit rows, make one status update hit all of them, and leave
  `TERMINATE_SCRIPT` unable to name a single run.
- **`trace_id`** (`trc_<8 hex>`) names one *message's passage* through the
  Engine: arrival, persistence, relay. Telemetry has no `command_id`, which is
  precisely why an unrelayed `APP_DATA` used to be untraceable. The Engine mints
  one on arrival if the peer did not supply one, honours an inbound one so a
  client that stamps its own messages gets a single id spanning both components,
  and bounds it to `MAX_TRACE_ID_LENGTH` since it is peer-supplied text that
  reaches every log line.

## Registration

Sequential, and the Engine hangs up after `REGISTRATION_TIMEOUT` (30s) at any
step. Implemented in `engine/main.py:perform_registration`.

```
client                                   engine
  |-- REGISTER {role, hostname, os} -------->|   role: "client" | "admin"
  |<------- REGISTER_CHALLENGE {nonce} ------|
  |-- REGISTER_RESPONSE {response} --------->|
  |<------- REGISTER_ACK {status} -----------|
```

Rejections come back as `REGISTER_REJECT {reason}` and the socket closes:
missing `client_id`, unknown role, server at capacity (`MAX_CLIENTS` 50 for
clients, `MAX_ADMINS` 5 for admins, counted separately so a full lab can still
be administered), a wrong message type, or a failed challenge.

Once a client is acknowledged the Engine flushes its outbox (see below) before
anything else.

**`DEV_BYPASS_AUTH=1` skips the handshake entirely** — no nonce is sent and no
response is expected, so bypassed traffic is unmistakable in a packet capture.
That is deliberate: a validation step that quietly passes would look identical
to working authentication.

> Challenge verification is currently a stub that accepts any response. The
> handshake's *motions* are real and exercised; its *verification* is Phase 7.

## Transport security

Presence-based. Once `certs/engine-cert.pem` exists the Engine and both clients
enable TLS automatically — there is no flag to forget. `ENGINE_TLS=0` /
`CLIENT_TLS=0` / `ADMIN_TLS=0` are the deliberate escape hatches, and startup
always logs which mode is active.

Clients pin the Engine's self-signed certificate and pass
`server_hostname="labmonitor-engine"` — a fixed name, not the address — so
hostname verification stays on even when the Engine's IP changes.

## Flows

Every inbound message runs one declared flow. `engine/routing.py` is the
mechanism; the `_ROUTES` table in `engine/command_handler.py` is the
declaration. Steps run **persist → handler → relay**, and the sending peer's
role is checked before any of them.

| Flow | Shape |
|---|---|
| `telemetry` | Client reports; Engine stores it and relays to every admin |
| `lifecycle` | Client reports on a command; status updated, admins told |
| `stream` | Client output passing straight to admins, stored nowhere |
| `query` | Admin asks, Engine alone answers |
| `dispatch` | Admin acts on clients — the only flow that fans out |
| `presence` | Liveness bookkeeping; relays only on change |

A type absent from `_ROUTES` is refused with a logged reason, never silently
ignored.

## Client → Engine

### `HEARTBEAT` — every 15s (`presence`)

```json
{"status": "active", "idle_time": 12.4, "screen_locked": false,
 "paused": false, "pause_until": null}
```

Admins heartbeat on the same interval. Nothing else makes an idle Admin GUI send
traffic, and the reaper drops any peer silent past `HEARTBEAT_TIMEOUT` (60s)
regardless of role. A change in `paused` triggers a `PAUSE_STATE` relay.

### `APP_DATA` — every 30s (`telemetry`)

```json
{"applications": [
  {"process_name": "chrome.exe", "pid": 4812, "window_title": "Docs",
   "start_time": "2026-08-09T13:02:11.000Z", "cpu_percent": 4.2,
   "memory_mb": 512.7}
]}
```

A hundred-plus entries per batch per client is normal; the Engine writes them
with one `executemany`.

### `NETWORK_DATA` — every 60s (`telemetry`)

```json
{"bytes_sent": 61326492, "bytes_received": 24399023,
 "packets_sent": 16796, "packets_received": 32231, "active_connections": 14}
```

**Counters are cumulative since the client booted.** Samples are stored as
received and differenced at query time: summaries sum positive deltas and skip
negatives, because a negative delta is a reboot, not negative usage.

### `USB_EVENT` (`telemetry`)

```json
{"event": "inserted", "device_name": "KINGSTON"}
```

The first poll after startup establishes a baseline, so drives already mounted
are not reported as insertions.

### Command lifecycle (`lifecycle`, and `stream` for output)

| Type | Payload | Effect |
|---|---|---|
| `COMMAND_ACCEPTED` | `command_id` | Status → `running` |
| `COMMAND_OUTPUT` | `command_id`, `chunk` | Relayed only, never stored |
| `COMMAND_COMPLETE` | `command_id`, `status`, `returncode` | Status → final |
| `COMMAND_RESPONSE` | `command_id`, `status`, `message` | Status → reported |

`COMMAND_OUTPUT` is deliberately not persisted: the client's log file is
per-execution scratch space and is deleted when the run reports complete.

## Admin → Engine

### `ADMIN_COMMAND` (`dispatch`)

```json
{"command_type": "TERMINATE_PROCESS",
 "target_clients": ["lab1-pc-07"],
 "parameters": {"process_name": "steam.exe"}}
```

An empty or absent `target_clients` broadcasts. `command_type` must be one of
`CLIENT_COMMANDS` or the Engine answers `COMMAND_RESPONSE` with an error. An
admin-supplied `command_id` is honoured only for a single target.

### `CLIENT_LIST` and `REPORT_REQUEST` (`query`)

`CLIENT_LIST` takes an empty payload and returns the roster, merging the live
registry with the database so a client that disconnects does not vanish from the
operator's list. Each entry carries `connected`.

`REPORT_REQUEST {report, client_id}` returns
`REPORT {report, client_id, status, data}`. Valid reports: `network_24h`,
`network_weekly`, `app_usage`, `usb_events`, `command_history`.

**Admins never touch the database directly** — every read goes through the
Engine, which is what keeps the storage layer swappable.

## Engine → Client

All dispatched via `ADMIN_COMMAND`, arriving with a `command_id`.

| Type | Parameters |
|---|---|
| `EXECUTE_SCRIPT` | `script`, `script_type` (`python`\|`powershell`), `timeout_seconds` |
| `TERMINATE_SCRIPT` | `target_command_id`, `force` |
| `TERMINATE_PROCESS` | `process_name`, `force` |
| `SCREEN_CAPTURE` | `quality` (1–95) |
| `SET_WEBSITE_POLICY` | `mode` (`blacklist`\|`whitelist`), `urls`, `action` |
| `SET_APP_BLACKLIST` | `process_names` — empty list clears |
| `SET_TIME_RESTRICTION` | `start`, `end` (ISO-8601), or `clear: true` |
| `SET_PAUSE` | `action` (`pause`\|`resume`), `seconds` |
| `SHOW_DIALOG` | `message`, `title`, `timeout`, `allow_cancel` |

`mode` on website policy is **required and always explicit** — which one is
active must never be inferred. Applications are blacklist-only by design:
whitelisting them cannot reliably enumerate the OS and helper processes
legitimate work depends on, so unlisted applications are allowed.

### Script execution never blocks

The client writes stdout/stderr to `logs/{command_id}.log`, sends
`COMMAND_ACCEPTED` immediately, then polls the log on a fixed interval and reads
only when the file has grown. On exit it sends one `COMMAND_COMPLETE` and
deletes both the log and the temp script.

Scripts are capped at 5 minutes, 15 maximum, and are standard-library plus
`subprocess` only — enforced by reading imports with `ast`, never a regex. A run
stopped at the cap reports `status: "timeout"`, distinct from `"error"`.

## Engine → Admin

Relayed unchanged from the source client, with `client_id` naming it:
`APP_DATA`, `NETWORK_DATA`, `USB_EVENT`, `COMMAND_ACCEPTED`, `COMMAND_OUTPUT`,
`COMMAND_COMPLETE`, `COMMAND_RESPONSE`. Answers to queries: `CLIENT_LIST`,
`REPORT`. Pushed on change: `PAUSE_STATE {paused, pause_until}`.

## The outbox

A command for a client that is not connected is not always lost.

**Durable commands** — `SET_WEBSITE_POLICY`, `SET_APP_BLACKLIST`,
`SET_TIME_RESTRICTION` — declare *state the client should converge to*, so
delivering one late is still correct. They are held as a `command_log` row with
status `queued` and flushed on that client's next registration. A newer command
of the same type supersedes the older one, which bounds the queue to one row per
type. Staleness is bounded by `ENGINE_OUTBOX_TTL` (default 24h), after which a
row becomes `expired`.

Everything else is a point-in-time action whose moment has passed — a
`SCREEN_CAPTURE` replayed twenty minutes later is a surprise, not a recovery —
and is marked `undeliverable` as before. `SET_PAUSE` is excluded deliberately:
the client already persists pause state across a reboot, so replaying it would
re-freeze a machine whose pause had legitimately lapsed.

There is no separate outbox table, so the queue and the audit trail cannot
disagree, and retention prunes both at once.

## Limits

| Limit | Value | Why |
|---|---|---|
| `STREAM_LIMIT` | 16 MB | asyncio caps a line at 64 KiB by default; a base64 screen capture blows past it. **Both** ends must set it |
| `STREAM_OVERHEAD_ALLOWANCE` | 64 KB | Envelope room; payloads budget against `STREAM_LIMIT` minus this |
| `HEARTBEAT_TIMEOUT` | 60s | Any peer silent this long is reaped |
| `MAX_CLIENTS` / `MAX_ADMINS` | 50 / 5 | Counted separately |

A line over `STREAM_LIMIT` makes the reader raise mid-stream and costs the peer
its connection, reporting nothing about the cause — so the client refuses to
build an oversized capture in the first place, with a message naming the reason.
