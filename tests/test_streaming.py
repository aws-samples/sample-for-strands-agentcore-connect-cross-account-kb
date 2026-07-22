import unittest
from http.client import IncompleteRead

from botocore.exceptions import ResponseStreamingError
from urllib3.exceptions import ProtocolError

from streamlit_app.streaming import (
    extract_text_from_event,
    iter_agentcore_text,
    iter_streaming_body_chunks,
    strip_thinking_stream,
    strip_thinking_text,
)


class FakeStreamingBody:
    def __init__(self, reads):
        self.reads = iter(reads)

    def read(self, _chunk_size):
        value = next(self.reads, b"")
        if isinstance(value, BaseException):
            raise value
        return value


def truncated_stream_error(partial: bytes):
    incomplete = IncompleteRead(partial)
    protocol_error = ProtocolError(
        f"Connection broken: {incomplete!r}",
        incomplete,
    )
    return ResponseStreamingError(error=protocol_error)


class StreamingTests(unittest.TestCase):
    def test_strips_complete_thinking_block(self):
        self.assertEqual(
            strip_thinking_text("<thinking>private</thinking>Answer"),
            "Answer",
        )

    def test_strips_thinking_tags_split_across_chunks(self):
        chunks = ["Hello <thin", "king>private", "</think", "ing> world"]

        self.assertEqual("".join(strip_thinking_stream(chunks)), "Hello  world")

    def test_extracts_strands_delta_text(self):
        event = {
            "event": {
                "contentBlockDelta": {
                    "delta": {"text": "token"},
                }
            }
        }

        self.assertEqual(extract_text_from_event(event), "token")

    def test_extracts_agentcore_json_string_token(self):
        self.assertEqual(extract_text_from_event("token"), "token")

    def test_ignores_control_and_final_result_frames(self):
        self.assertEqual(extract_text_from_event({"event": {"messageStop": {}}}), "")
        self.assertEqual(extract_text_from_event({"result": "complete"}), "")

    def test_recovers_partial_bytes_from_truncated_agentcore_stream(self):
        first = (
            b'data: {"event":{"contentBlockDelta":{"delta":{"text":"first "}}}}\n'
        )
        final = (
            b'data: {"event":{"contentBlockDelta":{"delta":{"text":"last"}}}}\n'
        )
        body = FakeStreamingBody([first, truncated_stream_error(final)])

        chunks = iter_streaming_body_chunks(body)

        self.assertEqual("".join(iter_agentcore_text(chunks)), "first last")

    def test_accepts_missing_chunk_terminator_after_complete_payload(self):
        complete = (
            b'{"event":{"contentBlockDelta":{"delta":{"text":"answer"}}}}\n'
        )
        body = FakeStreamingBody([complete, truncated_stream_error(b"")])

        self.assertEqual(
            b"".join(iter_streaming_body_chunks(body)),
            complete,
        )

    def test_decodes_agentcore_json_string_frame(self):
        body = FakeStreamingBody([b'data: "answer"\n\n'])

        self.assertEqual(
            "".join(iter_agentcore_text(iter_streaming_body_chunks(body))),
            "answer",
        )

    def test_raises_when_stream_fails_before_returning_payload(self):
        body = FakeStreamingBody([truncated_stream_error(b"")])

        with self.assertRaises(ResponseStreamingError):
            list(iter_streaming_body_chunks(body))

    def test_raises_unrelated_stream_errors(self):
        body = FakeStreamingBody([RuntimeError("network failure")])

        with self.assertRaisesRegex(RuntimeError, "network failure"):
            list(iter_streaming_body_chunks(body))


if __name__ == "__main__":
    unittest.main()
