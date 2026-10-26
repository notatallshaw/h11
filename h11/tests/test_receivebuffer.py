from __future__ import annotations

import operator
import re

import pytest

from .._receivebuffer import ReceiveBuffer


class CountWithCustomComparison(int):
    """Expose comparisons that slicing an integer subclass does not use."""

    def __gt__(self, other: object) -> bool:
        raise AssertionError("The slice count must not be compared")


@pytest.mark.parametrize(
    "count, expected, remaining",
    [
        (2, b"ab", b"c"),
        (3, b"abc", b""),
        (4, b"abc", b""),
        (2**100, b"abc", b""),
        (0, None, b"abc"),
        (-1, b"ab", b"c"),
        (-2, b"a", b"bc"),
        (-3, None, b"abc"),
        (-4, None, b"abc"),
        (-(2**100), None, b"abc"),
        (True, b"a", b"bc"),
        (False, None, b"abc"),
        (CountWithCustomComparison(2), b"ab", b"c"),
    ],
)
def test_receivebuffer_slice_counts(
    count: int, expected: bytes | None, remaining: bytes
) -> None:
    if isinstance(count, CountWithCustomComparison):
        with pytest.raises(AssertionError):
            operator.gt(count, 0)

    buf = ReceiveBuffer()
    buf += b"abc"

    extracted = buf.maybe_extract_at_most(count)
    if expected is None:
        assert extracted is None
    else:
        assert isinstance(extracted, bytearray)
        assert extracted == expected

    assert bytes(buf) == remaining
    assert len(buf) == len(remaining)


def test_receivebuffer() -> None:
    b = ReceiveBuffer()
    assert not b
    assert len(b) == 0
    assert bytes(b) == b""

    b += b"123"
    assert b
    assert len(b) == 3
    assert bytes(b) == b"123"

    assert bytes(b) == b"123"

    assert b.maybe_extract_at_most(2) == b"12"
    assert b
    assert len(b) == 1
    assert bytes(b) == b"3"

    assert bytes(b) == b"3"

    assert b.maybe_extract_at_most(10) == b"3"
    assert bytes(b) == b""

    assert b.maybe_extract_at_most(10) is None
    assert not b

    ################################################################
    # maybe_extract_until_next
    ################################################################

    b += b"123\n456\r\n789\r\n"

    assert b.maybe_extract_next_line() == b"123\n456\r\n"
    assert bytes(b) == b"789\r\n"

    assert b.maybe_extract_next_line() == b"789\r\n"
    assert bytes(b) == b""

    b += b"12\r"
    assert b.maybe_extract_next_line() is None
    assert bytes(b) == b"12\r"

    b += b"345\n\r"
    assert b.maybe_extract_next_line() is None
    assert bytes(b) == b"12\r345\n\r"

    # here we stopped at the middle of b"\r\n" delimiter

    b += b"\n6789aaa123\r\n"
    assert b.maybe_extract_next_line() == b"12\r345\n\r\n"
    assert b.maybe_extract_next_line() == b"6789aaa123\r\n"
    assert b.maybe_extract_next_line() is None
    assert bytes(b) == b""

    ################################################################
    # maybe_extract_lines
    ################################################################

    b += b"123\r\na: b\r\nfoo:bar\r\n\r\ntrailing"
    lines = b.maybe_extract_lines()
    assert lines == [b"123", b"a: b", b"foo:bar"]
    assert bytes(b) == b"trailing"

    assert b.maybe_extract_lines() is None

    b += b"\r\n\r"
    assert b.maybe_extract_lines() is None

    assert b.maybe_extract_at_most(100) == b"trailing\r\n\r"
    assert not b

    # Empty body case (as happens at the end of chunked encoding if there are
    # no trailing headers, e.g.)
    b += b"\r\ntrailing"
    assert b.maybe_extract_lines() == []
    assert bytes(b) == b"trailing"


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(
            (
                b"HTTP/1.1 200 OK\r\n",
                b"Content-type: text/plain\r\n",
                b"Connection: close\r\n",
                b"\r\n",
                b"Some body",
            ),
            id="with_crlf_delimiter",
        ),
        pytest.param(
            (
                b"HTTP/1.1 200 OK\n",
                b"Content-type: text/plain\n",
                b"Connection: close\n",
                b"\n",
                b"Some body",
            ),
            id="with_lf_only_delimiter",
        ),
        pytest.param(
            (
                b"HTTP/1.1 200 OK\n",
                b"Content-type: text/plain\r\n",
                b"Connection: close\n",
                b"\n",
                b"Some body",
            ),
            id="with_mixed_crlf_and_lf",
        ),
    ],
)
def test_receivebuffer_for_invalid_delimiter(data: tuple[bytes]) -> None:
    b = ReceiveBuffer()

    for line in data:
        b += line

    lines = b.maybe_extract_lines()

    assert lines == [
        b"HTTP/1.1 200 OK",
        b"Content-type: text/plain",
        b"Connection: close",
    ]
    assert bytes(b) == b"Some body"
