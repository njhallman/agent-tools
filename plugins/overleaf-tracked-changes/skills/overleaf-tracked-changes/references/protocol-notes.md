# Overleaf realtime protocol — field notes

Everything here was established empirically against overleaf.com (July 2026)
while building `scripts/overleaf_client.py`. Most of these are **silent
failures**: the server accepts the request and does nothing useful, so they
cost hours to find. Read this before modifying the client.

## Transport

Overleaf's realtime service speaks **socket.io 0.9**, not a modern version.
Handshake:

```
GET /socket.io/1/?projectId=<pid>&t=<ms>
-> "<sessionId>:60:60:websocket,xhr-polling"
```

**Use the xhr-polling transport, not WebSocket.** The WebSocket upgrade
(`wss://www.overleaf.com/socket.io/1/websocket/<sid>`) returns `502 Bad
Gateway` from Google's load balancer in sandboxed/proxied environments.
xhr-polling is plain HTTPS request/response and works anywhere `requests` does:

```
GET  /socket.io/1/xhr-polling/<sid>?projectId=<pid>&t=<ms>   # receive
POST /socket.io/1/xhr-polling/<sid>?projectId=<pid>&t=<ms>   # send
```

**The handshake's cookies must be reused.** Google's load balancer sets a
`GCLB` affinity cookie on the handshake response. Poll or post without it and
requests land on a backend that has never heard of the session id. Using one
`requests.Session` for the handshake and all subsequent calls handles this.

### Frame format (socket.io 0.9)

| Prefix | Meaning |
|---|---|
| `1::` | connected |
| `2::` | heartbeat — echo it back or the server drops the session |
| `5:<ackId>+::{"name":...,"args":[...]}` | event, ack requested |
| `5:::{...}` | event, no ack |
| `6:::<ackId>+[...]` | ack payload |
| `0::` | disconnect |

Multi-frame payloads are `�<charlen>�<frame>` repeated.

## The double-encoding bug

**Symptom:** every curly quote and em dash arrives as mojibake (`â\x80\x93`),
and the document is ~250 characters "longer" than it should be.

**Cause:** the xhr-polling transport reads the document's UTF-8 bytes as
latin-1 and then encodes *that* as UTF-8 on the wire. Raw bytes for `–` arrive
as `c3 a2 c2 80 c2 93` instead of `e2 80 93`.

**Fix:** decode UTF-8, then peel the extra layer.

```python
body = response.content.decode("utf-8")
body = body.encode("latin-1").decode("utf-8")   # undo the extra layer
```

This is not cosmetic. Edits are expressed as character offsets into the
document, so mangled text shifts every offset after the first non-ASCII
character and edits land in the wrong place. **Always `verify` against a known
good copy before the first edit of a session** — that check is what caught this.

Note that `GET /project/<pid>/doc/<doc_id>/download` returns clean UTF-8, which
is a useful cross-check when something looks wrong.

## Joining

```python
emit("joinProject", [{"project_id": pid}], want_ack=False)
# reply arrives as a joinProjectResponse *event*, not an ack
```

The response carries `project.rootFolder` (walk it for doc paths and ids),
`permissionsLevel`, and `features.trackChanges`.

```python
ack = emit("joinDoc", [doc_id, {"encodeRanges": True}])
```

**The ack shape is easy to get wrong:**

```
[0] error
[1] lines          -> document text is "\n".join(lines)
[2] version
[3] pending ops    <- usually [], and NOT the ranges
[4] ranges         <- {"changes": [...], "comments": [...]}
[5] otType         -> "sharejs-text-ot"
[6] options
```

Reading index 3 as ranges makes every document look like it has no tracked
changes, which reads as "tracked changes silently failed" when they actually
worked.

## Comment threads

`joinDoc` returns comment *anchors* under `ranges["comments"]`, but not the
discussion messages. Each anchor has an OT position, selected text, and thread
id:

```json
{"op": {"p": 26540, "c": "selected text", "t": "<thread-id>"}}
```

The editor loads the corresponding messages separately:

```
GET /project/<pid>/threads
```

The response is an object keyed by thread id. Each value contains `messages`
and, when applicable, resolution metadata. Use the same authenticated
`requests.Session` as the realtime connection; this avoids another cookie setup
and preserves the handshake's load-balancer affinity. A review of one source
line can therefore join the document once, map both tracked changes and comment
anchors to that line, and fetch all discussion text with one additional HTTP
request. Do not print the email field returned inside each message's `user`
object; display names are sufficient for manuscript review.

## Applying edits

```python
emit("applyOtUpdate", [doc_id, {
    "doc":  doc_id,
    "op":   [{"p": offset, "i": "inserted"}, {"p": offset, "d": "deleted"}],
    "v":    current_version,
    "meta": {"tc": id_seed},      # presence of tc => tracked change
}], want_ack=True)
```

**Emit with an ack id.** Sent as `5:::` (no ack), the update is silently
discarded — no error, no version bump. Sent as `5:<n>+::`, it applies and the
server echoes `otUpdateApplied`.

**`meta.tc` is what makes it a suggestion.** It is an id seed, mirroring
Overleaf's `RangesTracker.generateIdSeed()`: 18 hex characters
(8 timestamp + 6 random + 4 random), leaving room for the 6-hex counter that
each individual change id appends. Without `tc` the op applies as an ordinary
edit and no range is recorded.

**`v` must be the current version**, and ops use character offsets into the
joined text. A replacement is a delete plus an insert at the same offset.

**Ops in one update apply sequentially.** Each op's offset is interpreted
against the document *after* the preceding ops in the same list, so a batch
built from a single snapshot of the text must be emitted from the end of the
document backwards -- otherwise the first edit shifts every later offset and
text lands in the wrong place. `build_ops` sorts descending for this reason and
refuses overlapping anchors. A single-edit batch hides the bug entirely, so test
batching with at least two edits of different lengths.

Confirm success by re-joining and counting `ranges["changes"]` — a version bump
alone only proves the text changed, not that it was recorded as a suggestion.

## Accepting and rejecting

Accept goes over plain HTTP, not the socket:

```
POST /project/<pid>/doc/<doc_id>/changes/accept
     {"change_ids": ["<id>", ...]}        -> 204 No Content
```

CSRF token comes from `ol-csrfToken` on the project page. `GET
/project/<pid>/ranges` returns every doc's ranges in one call — much faster
than joining each document when surveying a project.

Accepting is **text-neutral**: insertions are already in the content and
deletions already removed, so only the markers clear (confirmed by identical
before/after hashes on a 59-change accept across three documents). It is,
however, one-way — the range holds the deleted string that a reject would
restore, so snapshot `/ranges` first if the before-state matters.

## Tracked-change semantics

- A tracked **deletion removes the text from the document content** and stores
  the deleted string in the range, so it can be restored on reject. Offsets
  computed from the document text therefore do not include deleted text.
- Tracked changes propagate to the git sync **as if accepted**: insertions
  present, deletions gone.
- `trackChangesState` in the project payload is per-user (`{user_id: true}`).
  It does not gate `meta.tc` — supplying the seed produces a tracked change
  regardless of whether the UI toggle is on for that account.

## Debugging checklist

| Symptom | Likely cause |
|---|---|
| `joinProject` times out once, then works | transient hiccup — the client retries 3x with backoff; common when opening sessions back to back |
| `ConnectionResetError` on a poll/post | same transient class, usually from hammering the endpoint; space calls a few seconds apart |
| `joinProject` times out repeatedly | cookie expired or wrong; re-fetch from the browser |
| WebSocket 502 | expected in proxied environments — use xhr-polling |
| polls 502 / session unknown | handshake cookies (GCLB) not reused |
| mojibake, wrong char count | double-encoding layer not undone |
| edit applies but no suggestion | `meta.tc` missing, or reading ack[3] as ranges |
| edit vanishes entirely | emitted without an ack id |
| text lands in the wrong place | offsets computed from stale or mangled text |
| tracked edit is visible but its discussion is missing | `joinDoc` supplies only the anchor — fetch `/project/<pid>/threads` |
