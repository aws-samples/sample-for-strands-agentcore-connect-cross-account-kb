"""Pure helpers for filtering and decoding streamed agent responses."""

from http.client import IncompleteRead
import json
import re


_THINKING_RE = re.compile(r"<thinking>.*?</thinking>", re.DOTALL)


def strip_thinking_text(text: str) -> str:
    """Remove complete thinking blocks from a response."""
    return _THINKING_RE.sub("", text).lstrip()


def strip_thinking_stream(stream):
    """Drop thinking blocks even when their tags span streamed chunks."""
    open_tag = "<thinking>"
    close_tag = "</thinking>"
    inside = False
    buffer = ""

    for token in stream:
        buffer += token
        emitted = ""
        while True:
            if not inside:
                index = buffer.find(open_tag)
                if index >= 0:
                    emitted += buffer[:index]
                    buffer = buffer[index + len(open_tag):]
                    inside = True
                    continue
                safe_length = max(0, len(buffer) - (len(open_tag) - 1))
                emitted += buffer[:safe_length]
                buffer = buffer[safe_length:]
                break

            index = buffer.find(close_tag)
            if index >= 0:
                buffer = buffer[index + len(close_tag):]
                inside = False
                continue
            safe_length = max(0, len(buffer) - (len(close_tag) - 1))
            buffer = buffer[safe_length:]
            break

        if emitted:
            yield emitted

    if not inside and buffer:
        yield buffer


def extract_text_from_event(event) -> str:
    """Pull text from a Strands stream event, ignoring control frames."""
    if isinstance(event, str):
        return event
    if not isinstance(event, dict):
        return ""

    inner = event.get("event")
    if isinstance(inner, dict):
        delta = inner.get("contentBlockDelta", {}).get("delta")
        if isinstance(delta, dict):
            return delta.get("text", "") or ""
        return ""

    if "message" in event or "result" in event:
        return ""

    for key in ("data", "text"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    return ""


def _incomplete_read_partial(error) -> bytes | None:
    """Find partial bytes from an IncompleteRead wrapped by botocore/urllib3."""
    pending = [error]
    seen = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))

        if isinstance(current, IncompleteRead):
            partial = current.partial
            return bytes(partial) if partial is not None else b""

        if isinstance(current, BaseException):
            pending.extend(current.args)
            if current.__cause__ is not None:
                pending.append(current.__cause__)
            if current.__context__ is not None:
                pending.append(current.__context__)
            kwargs = getattr(current, "kwargs", None)
            if isinstance(kwargs, dict):
                pending.extend(kwargs.values())
    return None


def iter_streaming_body_chunks(body, chunk_size: int = 1024):
    """Yield body bytes and salvage bytes from a truncated chunk terminator.

    AgentCore Runtime responses use HTTP chunked transfer encoding. In rare
    cases the server closes after sending the final payload but before sending
    the zero-length terminator. Botocore then wraps IncompleteRead and drops
    its partial bytes. Recover those bytes instead of losing the end of an
    otherwise successful response.
    """
    emitted = False
    while True:
        try:
            chunk = body.read(chunk_size)
        except Exception as error:
            partial = _incomplete_read_partial(error)
            if partial is None or (not emitted and not partial):
                raise
            if partial:
                yield partial
            return

        if not chunk:
            return
        emitted = True
        yield chunk


def iter_agentcore_text(chunks):
    """Decode newline-delimited AgentCore Runtime frames into text tokens."""
    buffer = b""
    for chunk in chunks:
        if not chunk:
            continue
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            text = _agentcore_frame_text(line)
            if text:
                yield text

    text = _agentcore_frame_text(buffer)
    if text:
        yield text


def _agentcore_frame_text(frame: bytes) -> str:
    """Extract text from one JSON or SSE-framed AgentCore event."""
    frame = frame.strip()
    if frame.startswith(b"data:"):
        frame = frame[5:].lstrip()
    if not frame:
        return ""
    try:
        event = json.loads(frame)
    except (json.JSONDecodeError, ValueError):
        return ""
    return extract_text_from_event(event)
