#!/usr/bin/env python3
"""Read and edit Overleaf documents as tracked changes, without a browser.

Auth comes from an `overleaf_session2` cookie exported as OVERLEAF_SESSION
(see SKILL.md for why password/browser automation does not work).

Transport is socket.io 0.9 over xhr-polling. Every non-obvious detail here was
established empirically against overleaf.com; see references/protocol-notes.md
before changing any of it.

Commands
    list                      list every doc in the project with its id
    read PATH [-o FILE]       fetch a doc's current text
    verify PATH LOCAL         confirm the Overleaf copy matches a local file
    changes PATH              list tracked changes (suggestions) in a doc
    review PATH [--line N]    show full changes, context, and comment threads
    edit PATH --edits F.json  apply anchor-based edits (dry-run unless --apply)
    accept PATH               resolve tracked changes (dry-run unless --apply)
    batch --edits F.json      apply edits to several docs over one connection
    bundle                    print a self-contained installer for this skill

Which Overleaf project is targeted comes from --project, else
$OVERLEAF_PROJECT_ID, else the nearest `.claude/overleaf-project-id` file
walking up from the working directory (the repository root, in practice). There
is no built-in default: a wrong project id would apply one repo's edits to some
other paper without erroring, so an unset id is a hard failure.

Edit file format — a list of exact-text replacements:
    [
      {"find": "text that appears exactly once", "replace": "new text"},
      {"find": "text to delete entirely",        "replace": ""},
      {"insert_before": "anchor text",           "text": "inserted "}
    ]
Anchors must match exactly once in the document; the script refuses ambiguous
or missing anchors rather than guessing, because a wrong offset silently
corrupts prose somewhere else in the file.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import random
import re
import sys
import threading
import time
import zlib

import requests

BASE = "https://www.overleaf.com"
SKILL_DIR = pathlib.Path(__file__).resolve().parent.parent
PROJECT_ID_RE = re.compile(r"^[0-9a-f]{24}$")


ID_FILENAME = ".claude/overleaf-project-id"


def _project_id_files() -> list[pathlib.Path]:
    """Candidate id files, nearest-to-the-project first.

    The id must be per-project, never per-skill, and every candidate here is
    therefore repo-relative. Nothing beside the script is consulted: installed
    as a plugin, this skill's directory is a cache shared by every project on
    the machine, so an id stored there would be picked up by whichever repo ran
    next. A vendored copy lives inside a repository, so the repo-local file
    already covers that case too.
    """
    candidates = []
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        candidates.append(pathlib.Path(env_root) / ID_FILENAME)
    cwd = pathlib.Path.cwd().resolve()
    candidates += [p / ID_FILENAME for p in [cwd, *cwd.parents]]
    return candidates


def resolve_project_id(cli_value: str | None = None) -> str:
    """Find the target project id, or fail loudly.

    Deliberately has no fallback default. An id baked into the source travels
    with any copy of this skill, so a copy installed in another repo would
    silently edit whichever project the original pointed at -- and since the
    anchors either match or abort, nothing in the output would reveal that the
    edits landed in the wrong paper.
    """
    sources = [
        (cli_value, "--project"),
        (os.environ.get("OVERLEAF_PROJECT_ID"), "$OVERLEAF_PROJECT_ID"),
    ]
    for id_file in _project_id_files():
        if id_file.exists():
            sources.append((id_file.read_text(encoding="utf-8"), str(id_file)))
            break
    for raw, origin in sources:
        if not raw or not raw.strip():
            continue
        value = raw.strip()
        if not PROJECT_ID_RE.match(value):
            sys.exit(f"error: project id from {origin} is not 24 hex "
                     f"characters: {value!r}")
        return value
    sys.exit(
        "error: no Overleaf project id.\n"
        "Set one of the following (checked in this order):\n"
        "  --project <id>\n"
        "  export OVERLEAF_PROJECT_ID=<id>\n"
        f"  echo <id> > {ID_FILENAME}   (in the repository root)\n"
        "The id is the 24-hex string in the project URL: "
        "overleaf.com/project/<id>."
    )


def _cookie() -> str:
    c = os.environ.get("OVERLEAF_SESSION", "").strip()
    if not c:
        sys.exit(
            "error: set OVERLEAF_SESSION to an overleaf_session2 cookie value.\n"
            "Get it from a logged-in browser: Web Inspector > Storage > Cookies\n"
            "> www.overleaf.com > overleaf_session2 (see SKILL.md)."
        )
    return c


def http_session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    )
    s.cookies.set("overleaf_session2", _cookie(), domain="www.overleaf.com", path="/")
    return s


# --------------------------------------------------------------------------
# socket.io 0.9 framing
# --------------------------------------------------------------------------
def _decode_frames(payload: str) -> list[str]:
    """Split a multi-frame xhr-polling payload (�<len>�<frame>...)."""
    if not payload:
        return []
    if not payload.startswith("�"):
        return [payload]
    frames, i = [], 0
    while i < len(payload):
        if payload[i] != "�":
            break
        j = payload.index("�", i + 1)
        n = int(payload[i + 1:j])
        frames.append(payload[j + 1:j + 1 + n])
        i = j + 1 + n
    return frames


class Realtime:
    """Overleaf realtime connection (socket.io 0.9, xhr-polling transport)."""

    def __init__(self, project_id: str, verbose: bool = False):
        self.pid = project_id
        self.verbose = verbose
        self.s = http_session()
        self.sid = None
        self._ack_id = 0
        self._pending: dict[int, list] = {}
        self._events: list[dict] = []
        self._lock = threading.Lock()
        self._stop = False

    def connect(self, timeout: int = 30) -> str:
        r = self.s.get(f"{BASE}/socket.io/1/?projectId={self.pid}"
                       f"&t={int(time.time() * 1000)}", timeout=timeout)
        r.raise_for_status()
        self.sid = r.text.split(":")[0]
        # The handshake also sets the load balancer's affinity cookie (GCLB) on
        # this session; subsequent polls must reuse it or they hit a backend
        # that has never heard of this sid.
        threading.Thread(target=self._poll_loop, daemon=True).start()
        return self.sid

    def _url(self) -> str:
        return (f"{BASE}/socket.io/1/xhr-polling/{self.sid}"
                f"?projectId={self.pid}&t={int(time.time() * 1000)}")

    def _poll_loop(self) -> None:
        while not self._stop:
            try:
                r = self.s.get(self._url(), timeout=40)
                if r.status_code != 200:
                    time.sleep(1)
                    continue
                # The transport double-encodes: document UTF-8 bytes are read as
                # latin-1 and re-encoded as UTF-8 on the wire. Undo the extra
                # layer or every curly quote and em dash arrives mangled -- and
                # mangled text means wrong character offsets for edits.
                body = r.content.decode("utf-8")
                try:
                    body = body.encode("latin-1").decode("utf-8")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
                for frame in _decode_frames(body):
                    self._handle(frame)
            except Exception:
                time.sleep(0.5)

    def _post(self, frame: str) -> None:
        if self.verbose:
            print(">>", frame[:200], file=sys.stderr)
        self.s.post(self._url(), data=frame.encode("utf-8"),
                    headers={"Content-Type": "text/plain;charset=UTF-8"}, timeout=30)

    def _handle(self, raw: str) -> None:
        if self.verbose:
            print("<<", raw[:300], file=sys.stderr)
        if raw.startswith("2:"):                      # heartbeat
            self._post("2::")
            return
        m = re.match(r"^6:::(\d+)(\+(.*))?$", raw, re.S)
        if m:                                          # ack
            payload = json.loads(m.group(3)) if m.group(3) else []
            with self._lock:
                self._pending[int(m.group(1))] = payload
            return
        m = re.match(r"^5:(\d*)(\+?)::(.*)$", raw, re.S)
        if m:                                          # event
            try:
                ev = json.loads(m.group(3))
            except ValueError:
                return
            with self._lock:
                self._events.append(ev)

    def emit(self, name: str, args: list, want_ack: bool = True, timeout: int = 40):
        """Emit an event.

        Always emit with an ack id for anything that mutates state: Overleaf
        silently drops applyOtUpdate sent without one.
        """
        if not want_ack:
            self._post("5:::" + json.dumps({"name": name, "args": args}))
            return None
        with self._lock:
            self._ack_id += 1
            aid = self._ack_id
        self._post(f"5:{aid}+::" + json.dumps({"name": name, "args": args}))
        end = time.time() + timeout
        while time.time() < end:
            with self._lock:
                if aid in self._pending:
                    return self._pending.pop(aid)
            time.sleep(0.05)
        raise TimeoutError(f"no ack for {name}")

    def wait_event(self, name: str, timeout: int = 40):
        end = time.time() + timeout
        while time.time() < end:
            with self._lock:
                for i, ev in enumerate(self._events):
                    if ev.get("name") == name:
                        return self._events.pop(i)
            time.sleep(0.05)
        return None

    def close(self) -> None:
        self._stop = True
        try:
            self._post("0::")
        except Exception:
            pass


# --------------------------------------------------------------------------
# project / document helpers
# --------------------------------------------------------------------------
def walk(folder: dict, prefix: str = ""):
    for d in folder.get("docs", []):
        yield f"{prefix}/{d['name']}", d["_id"]
    for sub in folder.get("folders", []):
        yield from walk(sub, f"{prefix}/{sub['name']}")


def generate_id_seed() -> str:
    """18 hex chars, mirroring Overleaf's RangesTracker.generateIdSeed().

    Change ids are this seed plus a 6-hex counter, so the seed must leave room
    for the increment or ids collide.
    """
    return (format(int(time.time()), "08x")
            + format(random.randint(0, 0xFFFFFF), "06x")
            + format(random.randint(0, 0x7FFF), "04x"))


class Project:
    def __init__(self, project_id: str, verbose: bool = False):
        self.pid = project_id
        self.rt = Realtime(project_id, verbose=verbose)
        self.docs: dict[str, str] = {}

    def open(self, attempts: int = 3) -> "Project":
        # Connection resets and join timeouts happen sporadically, especially
        # when several sessions are opened in quick succession, so retry before
        # concluding anything is actually wrong.
        ev = None
        for attempt in range(1, attempts + 1):
            try:
                self.rt.connect()
                self.rt.emit("joinProject", [{"project_id": self.pid}], want_ack=False)
                ev = self.rt.wait_event("joinProjectResponse", timeout=45)
                if ev:
                    break
            except requests.RequestException:
                pass
            if attempt < attempts:
                self.rt = Realtime(self.pid, verbose=self.rt.verbose)
                time.sleep(3 * attempt)
        if not ev:
            raise RuntimeError(
                f"joinProject failed after {attempts} attempts — the "
                "OVERLEAF_SESSION cookie is probably stale."
            )
        project = ev["args"][0]["project"]
        self.docs = {p: i for p, i in walk(project["rootFolder"][0])}
        self.name = project.get("name")
        return self

    def resolve(self, path: str) -> str:
        if path in self.docs:
            return self.docs[path]
        matches = [p for p in self.docs if p.endswith(path) or p.endswith("/" + path)]
        if len(matches) == 1:
            return self.docs[matches[0]]
        if not matches:
            raise SystemExit(f"error: no doc matching {path!r}")
        raise SystemExit(f"error: {path!r} is ambiguous: {matches}")

    def join_doc(self, doc_id: str) -> dict:
        """Returns {text, version, ranges}.

        joinDoc acks as [error, lines, version, pendingOps, ranges, otType, opts]
        -- index 4 is ranges; index 3 is the pending-op list and is usually [].
        """
        ack = self.rt.emit("joinDoc", [doc_id, {"encodeRanges": True}], timeout=45)
        if ack[0]:
            raise RuntimeError(f"joinDoc error: {ack[0]}")
        return {"text": "\n".join(ack[1]), "version": ack[2],
                "ranges": ack[4] if len(ack) > 4 else {}}

    def apply_ops(self, doc_id: str, ops: list, version: int, tracked: bool = True):
        update = {"doc": doc_id, "op": ops, "v": version}
        if tracked:
            update["meta"] = {"tc": generate_id_seed()}
        self.rt.emit("applyOtUpdate", [doc_id, update], want_ack=True, timeout=45)

    def accept(self, doc_id: str, change_ids: list[str]) -> int:
        """Resolve tracked changes via the web endpoint (not the socket).

        Accepting is text-neutral: an accepted insertion is already in the
        document and an accepted deletion is already removed, so this only
        clears the suggestion markers. What it does destroy is the ability to
        reject -- the ranges hold the deleted text, so snapshot them first if
        the before-state matters.
        """
        page = self.rt.s.get(f"{BASE}/project/{self.pid}", timeout=30).text
        m = re.search(r'name="ol-csrfToken"[^>]*content="([^"]+)"', page)
        if not m:
            raise RuntimeError("could not read CSRF token from project page")
        r = self.rt.s.post(
            f"{BASE}/project/{self.pid}/doc/{doc_id}/changes/accept",
            headers={"X-Csrf-Token": m.group(1), "Content-Type": "application/json",
                     "Accept": "application/json"},
            data=json.dumps({"change_ids": change_ids}), timeout=60)
        if r.status_code >= 300:
            raise RuntimeError(f"accept failed: HTTP {r.status_code} {r.text[:200]}")
        return len(change_ids)

    def threads(self) -> dict:
        """Return the project's comment threads over the authenticated session.

        Comment anchors arrive with ``joinDoc`` under ``ranges.comments``, but
        their messages are loaded separately by the Overleaf editor from this
        endpoint.  Keeping the request on the realtime connection's HTTP
        session reuses its authenticated cookie and load-balancer affinity.
        """
        r = self.rt.s.get(
            f"{BASE}/project/{self.pid}/threads",
            headers={"Accept": "application/json"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict):
            raise RuntimeError("Overleaf returned an invalid comment-thread payload")
        return data

    def upload(self, local_path: str, folder_id: str, name: str | None = None) -> dict:
        """Replace or add a binary file (figures, PDFs) in a project folder.

        Text edits go over the realtime protocol, but binaries use the web
        upload endpoint. The filename must be passed as a `qqfilename` form
        field -- sending it only in the multipart part gets a 422
        invalid_filename. Uploading over an existing name replaces it.
        """
        import os
        name = name or os.path.basename(local_path)
        page = self.rt.s.get(f"{BASE}/project/{self.pid}", timeout=30).text
        m = re.search(r'name="ol-csrfToken"[^>]*content="([^"]+)"', page)
        if not m:
            raise RuntimeError("could not read CSRF token from project page")
        with open(local_path, "rb") as fh:
            r = self.rt.s.post(
                f"{BASE}/project/{self.pid}/upload?folder_id={folder_id}",
                headers={"X-Csrf-Token": m.group(1)},
                data={"qqfilename": name, "name": name},
                files={"qqfile": (name, fh)}, timeout=180)
        if r.status_code >= 300 or '"success":true' not in r.text:
            raise RuntimeError(f"upload failed: HTTP {r.status_code} {r.text[:200]}")
        return r.json()

    def folders(self) -> dict[str, str]:
        """Path -> folder id, needed to target an upload."""
        self.rt.emit("joinProject", [{"project_id": self.pid}], want_ack=False)
        ev = self.rt.wait_event("joinProjectResponse", timeout=45)
        root = ev["args"][0]["project"]["rootFolder"][0]

        def walk_dirs(f, prefix=""):
            yield (prefix or "/"), f["_id"]
            for sub in f.get("folders", []):
                yield from walk_dirs(sub, f"{prefix}/{sub['name']}")

        return dict(walk_dirs(root))

    def close(self) -> None:
        self.rt.close()


def build_ops(text: str, edits: list) -> list:
    """Turn anchor-based edits into OT ops, refusing anything ambiguous.

    Ops inside one update are applied in sequence, so an op early in the
    document shifts the offsets of every op after it. Emitting the edits from
    the end of the document backwards keeps each offset valid without having to
    track cumulative drift -- earlier text is untouched when a later edit
    applies.
    """
    groups: list[tuple[int, int, list]] = []   # (position, end, ops)
    for n, e in enumerate(edits, 1):
        if "insert_before" in e:
            anchor, new, old = e["insert_before"], e.get("text", ""), ""
        else:
            anchor = old = e["find"]
            new = e.get("replace", "")
        count = text.count(anchor)
        if count != 1:
            raise SystemExit(
                f"edit {n}: anchor occurs {count} times, need exactly 1: {anchor[:70]!r}\n"
                "Extend the anchor with surrounding text until it is unique."
            )
        p = text.index(anchor)
        ops = []
        if old:
            ops.append({"p": p, "d": old})
        if new:
            ops.append({"p": p, "i": new})
        groups.append((p, p + len(anchor), ops))

    groups.sort(key=lambda g: g[0])
    for (p1, e1, _), (p2, _, _) in zip(groups, groups[1:]):
        if p2 < e1:
            raise SystemExit(
                f"edits overlap at offsets {p1}-{e1} and {p2}; "
                "split or merge them so each edit covers distinct text."
            )
    return [op for _, _, ops in reversed(groups) for op in ops]


def _line_number(text: str, position: int) -> int:
    """Convert a document offset to a one-based source line."""
    position = max(0, min(position, len(text)))
    return text[:position].count("\n") + 1


def _author_names(threads: dict) -> dict[str, str]:
    """Build a user-id -> display-name map without exposing email addresses."""
    names = {}
    for thread in threads.values():
        for message in thread.get("messages", []):
            user = message.get("user") or {}
            user_id = message.get("user_id") or user.get("id")
            full_name = " ".join(
                part for part in (user.get("first_name"), user.get("last_name"))
                if part
            )
            if user_id and full_name:
                names[user_id] = full_name
    return names


def _indent_block(value: str, prefix: str = "      ") -> list[str]:
    lines = value.splitlines() or [""]
    return [prefix + line for line in lines]


def render_review(
    path: str,
    document: dict,
    threads: dict,
    target_line: int | None = None,
    context: int = 2,
) -> str:
    """Render full review context without truncating suggestions or comments.

    Without ``target_line``, every tracked-change line is shown, together with
    comment threads anchored on those lines. With a target, both tracked
    changes and comments are filtered to that exact source line. This keeps the
    default useful on heavily annotated manuscripts instead of dumping every
    historical comment in the project.
    """
    if target_line is not None and target_line < 1:
        raise ValueError("target_line must be at least 1")
    if context < 0:
        raise ValueError("context must be non-negative")

    text = document["text"]
    ranges = document.get("ranges") or {}
    changes = [
        {**change, "line": _line_number(text, change["op"]["p"])}
        for change in ranges.get("changes", [])
    ]
    comments = [
        {**comment, "line": _line_number(text, comment["op"]["p"])}
        for comment in ranges.get("comments", [])
    ]

    if target_line is not None:
        changes = [change for change in changes if change["line"] == target_line]
        comments = [comment for comment in comments if comment["line"] == target_line]
        review_lines = {target_line}
    else:
        review_lines = {change["line"] for change in changes}
        comments = [comment for comment in comments if comment["line"] in review_lines]

    authors = _author_names(threads)
    source_lines = text.splitlines()
    out = [
        f"review {path} (v{document['version']}): "
        f"{len(changes)} tracked change(s), {len(comments)} comment thread(s)"
    ]

    if not review_lines:
        out.append("no tracked changes to review")
        return "\n".join(out) + "\n"

    for line in sorted(review_lines):
        out.append("")
        out.append(f"=== line {line} ===")
        start = max(1, line - context)
        end = min(len(source_lines), line + context)
        out.append(f"SOURCE (lines {start}-{end})")
        for number in range(start, end + 1):
            marker = ">" if number == line else " "
            out.append(f"{marker} {number:>5} | {source_lines[number - 1]}")

        line_changes = [change for change in changes if change["line"] == line]
        for change in line_changes:
            op = change["op"]
            kind = "INSERT" if "i" in op else "DELETE"
            body = op.get("i") if "i" in op else op.get("d", "")
            user_id = (change.get("metadata") or {}).get("user_id", "")
            author = authors.get(user_id, user_id[:8] or "unknown")
            out.append(f"{kind} by {author} (change {change.get('id', 'unknown')})")
            out.extend(_indent_block(body))

        line_comments = [comment for comment in comments if comment["line"] == line]
        for comment in line_comments:
            thread_id = comment["op"].get("t") or comment.get("id")
            anchor = comment["op"].get("c", "")
            thread = threads.get(thread_id, {})
            state = "resolved" if thread.get("resolved") else "open"
            out.append(f"COMMENT THREAD {thread_id} ({state})")
            out.append("  anchor:")
            out.extend(_indent_block(anchor))
            messages = thread.get("messages", [])
            if not messages:
                out.append("  (no messages returned)")
            for message in messages:
                user = message.get("user") or {}
                user_id = message.get("user_id") or user.get("id", "")
                author = authors.get(user_id, user_id[:8] or "unknown")
                out.append(f"  {author}:")
                out.extend(_indent_block(message.get("content", "")))

    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------
BUNDLED_FILES = ("SKILL.md", "references/protocol-notes.md",
                 "scripts/overleaf_client.py")

INSTALLER_TEMPLATE = '''#!/usr/bin/env python3
"""Installer for the overleaf-tracked-changes Claude Code skill.

Generated by `overleaf_client.py bundle`. Run it from a repository root:

    python3 install_overleaf_skill.py

It writes .claude/skills/overleaf-tracked-changes/ and nothing else. No project
id is included -- set OVERLEAF_PROJECT_ID or write .claude/overleaf-project-id
in the repository root, or the client will refuse to run rather than guess.
"""
import base64
import json
import pathlib
import zlib

PAYLOAD = "{payload}"

root = pathlib.Path(".claude/skills/overleaf-tracked-changes")
files = json.loads(zlib.decompress(base64.b64decode(PAYLOAD)).decode("utf-8"))
for rel, text in sorted(files.items()):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote {{path}} ({{len(text)}} chars)")
print(
    "\\nNext: export OVERLEAF_SESSION (overleaf_session2 cookie from a "
    "logged-in browser)\\nand set the project id in this repository, e.g.\\n"
    "  echo <24-hex-id-from-the-project-URL> > .claude/overleaf-project-id\\n"
    "Then read the skill's SKILL.md."
)
'''


def bundle() -> str:
    """Emit a one-file installer that recreates this skill anywhere.

    Payload is zlib-compressed so the result is small enough to paste into a
    chat, and base64 so that LaTeX backslashes, dollar signs, and the client's
    own triple-quoted docstrings cannot break the quoting.
    """
    missing = [f for f in BUNDLED_FILES if not (SKILL_DIR / f).exists()]
    if missing:
        sys.exit(f"error: cannot bundle, missing {missing} under {SKILL_DIR}")
    files = {f: (SKILL_DIR / f).read_text(encoding="utf-8") for f in BUNDLED_FILES}
    raw = json.dumps(files, ensure_ascii=False).encode("utf-8")
    payload = base64.b64encode(zlib.compress(raw, 9)).decode("ascii")
    return INSTALLER_TEMPLATE.format(payload=payload)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", default=None,
                    help="Overleaf project id; else $OVERLEAF_PROJECT_ID, else "
                         "the skill's project-id file")
    ap.add_argument("--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("bundle", help="print a self-contained installer for this skill")
    p_read = sub.add_parser("read"); p_read.add_argument("path"); p_read.add_argument("-o")
    p_ver = sub.add_parser("verify"); p_ver.add_argument("path"); p_ver.add_argument("local")
    p_chg = sub.add_parser("changes"); p_chg.add_argument("path")
    p_rev = sub.add_parser(
        "review",
        help="show full tracked changes, source context, and attached comments",
    )
    p_rev.add_argument("path")
    p_rev.add_argument("--line", type=int,
                       help="show only changes and comments on this source line")
    p_rev.add_argument("--context", type=int, default=2,
                       help="source lines before and after each result (default: 2)")
    p_ed = sub.add_parser("edit")
    p_ed.add_argument("path"); p_ed.add_argument("--edits", required=True)
    p_ed.add_argument("--apply", action="store_true",
                      help="actually send; without it the ops are only previewed")
    p_ed.add_argument("--untracked", action="store_true",
                      help="apply as a normal edit instead of a suggestion")
    p_b = sub.add_parser("batch")
    p_b.add_argument("--edits", required=True,
                     help='JSON object mapping doc path -> edit list; all docs '
                          'are edited over one connection')
    p_b.add_argument("--dry-run", action="store_true",
                     help="validate anchors and print ops without sending")
    p_b.add_argument("--untracked", action="store_true")
    p_ac = sub.add_parser("accept")
    p_ac.add_argument("path")
    p_ac.add_argument("--apply", action="store_true",
                      help="actually resolve; without it the changes are only listed")
    p_ac.add_argument("--mine-only", action="store_true",
                      help="only resolve changes authored by this session's account")
    a = ap.parse_args()

    # bundle needs no connection, and must work before a project id is set --
    # exporting the skill is exactly what you do in a repo that has no id yet.
    if a.cmd == "bundle":
        sys.stdout.write(bundle())
        return

    proj = Project(resolve_project_id(a.project), verbose=a.verbose).open()
    try:
        if a.cmd == "list":
            for path in sorted(proj.docs):
                print(f"{proj.docs[path]}  {path}")
            return

        if a.cmd == "batch":
            spec = json.load(open(a.edits, encoding="utf-8"))
            total = 0
            for path, edits in spec.items():
                doc_id = proj.resolve(path)
                d = proj.join_doc(doc_id)
                # Anchors are validated here, before anything is sent, so the
                # apply-by-default path still cannot write a bad offset.
                ops = build_ops(d["text"], edits)
                for op in sorted(ops, key=lambda o: o["p"]):
                    line = d["text"][:op["p"]].count("\n") + 1
                    kind = "insert" if "i" in op else "delete"
                    body = op.get("i") or op.get("d")
                    print(f"  {path}:{line} {kind} {json.dumps(body)[:60]}")
                if not a.dry_run:
                    proj.apply_ops(doc_id, ops, d["version"], tracked=not a.untracked)
                    total += len(ops)
            print(f"\n{'validated' if a.dry_run else 'applied'} {total or sum(len(v) for v in spec.values())} "
                  f"op(s) across {len(spec)} doc(s)")
            return

        doc_id = proj.resolve(a.path)
        d = proj.join_doc(doc_id)

        if a.cmd == "read":
            if a.o:
                open(a.o, "w", encoding="utf-8").write(d["text"])
                print(f"wrote {a.o} ({len(d['text'])} chars, v{d['version']})")
            else:
                sys.stdout.write(d["text"])
            return

        if a.cmd == "verify":
            local = open(a.local, encoding="utf-8").read()
            same = d["text"].rstrip("\n") == local.rstrip("\n")
            print(f"overleaf v{d['version']} {len(d['text'])} chars | "
                  f"local {len(local)} chars | MATCH: {same}")
            sys.exit(0 if same else 1)

        if a.cmd == "changes":
            changes = (d["ranges"] or {}).get("changes", [])
            print(f"{len(changes)} tracked change(s) in {a.path} (v{d['version']})")
            for c in changes:
                op = c["op"]
                kind = "INSERT" if "i" in op else "DELETE"
                body = op.get("i") or op.get("d") or ""
                line = d["text"][:op["p"]].count("\n") + 1
                print(f"  line {line:>4} {kind:6} {json.dumps(body)[:60]} "
                      f"user={c['metadata']['user_id'][:8]}")
            return

        if a.cmd == "review":
            if a.line is not None and a.line < 1:
                ap.error("review --line must be at least 1")
            if a.context < 0:
                ap.error("review --context must be non-negative")
            sys.stdout.write(render_review(
                a.path,
                d,
                proj.threads(),
                target_line=a.line,
                context=a.context,
            ))
            return

        if a.cmd == "accept":
            changes = (d["ranges"] or {}).get("changes", [])
            if a.mine_only:
                me = proj.rt.s.get(f"{BASE}/project/{proj.pid}", timeout=30).text
                m = re.search(r'"id":"([0-9a-f]{24})"', me)
                changes = [c for c in changes
                           if m and c["metadata"]["user_id"] == m.group(1)]
            for c in changes:
                op = c["op"]
                line = d["text"][:op["p"]].count("\n") + 1
                kind = "INSERT" if "i" in op else "DELETE"
                print(f"  line {line:>4} {kind:6} {json.dumps(op.get('i') or op.get('d'))[:60]}")
            if not changes:
                print("no tracked changes to accept")
                return
            if not a.apply:
                print(f"\ndry run ({len(changes)} change(s)); re-run with --apply "
                      f"to resolve. Text will not change -- only the markers clear, "
                      f"and rejecting is no longer possible afterwards.")
                return
            n = proj.accept(doc_id, [c["id"] for c in changes])
            time.sleep(2)
            after = proj.join_doc(doc_id)
            print(f"\naccepted {n}; remaining tracked changes: "
                  f"{len((after['ranges'] or {}).get('changes', []))}; "
                  f"text unchanged: {after['text'] == d['text']}")
            return

        if a.cmd == "edit":
            edits = json.load(open(a.edits, encoding="utf-8"))
            ops = build_ops(d["text"], edits)
            for op in ops:
                line = d["text"][:op["p"]].count("\n") + 1
                kind = "insert" if "i" in op else "delete"
                print(f"  line {line:>4} {kind} {json.dumps(op.get('i') or op.get('d'))[:70]}")
            if not a.apply:
                print(f"\ndry run ({len(ops)} ops against v{d['version']}); "
                      f"re-run with --apply to send")
                return
            proj.apply_ops(doc_id, ops, d["version"], tracked=not a.untracked)
            time.sleep(3)
            after = proj.join_doc(doc_id)
            mine = len((after["ranges"] or {}).get("changes", [])) - \
                len((d["ranges"] or {}).get("changes", []))
            print(f"\napplied: v{d['version']} -> v{after['version']}; "
                  f"tracked changes {'+%d' % mine if mine >= 0 else mine}")
    finally:
        proj.close()


if __name__ == "__main__":
    main()
