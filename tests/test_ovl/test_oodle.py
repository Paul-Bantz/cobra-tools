import sys
from types import SimpleNamespace

import pytest

from modules.formats.utils.oodle.oodle import OozDecompressor


def test_ooz_decompressor_uses_expected_output_size(monkeypatch):
	backend = SimpleNamespace(decompress=lambda payload, output_size: b"x" * output_size)
	monkeypatch.setitem(sys.modules, "ooz", backend)

	decompressor = OozDecompressor()

	assert decompressor.decompress(b"compressed", 10, 4) == b"xxxx"


def test_ooz_decompressor_rejects_wrong_output_size(monkeypatch):
	backend = SimpleNamespace(decompress=lambda payload, output_size: b"short")
	monkeypatch.setitem(sys.modules, "ooz", backend)

	with pytest.raises(ValueError, match="output_size=5 expected=10"):
		OozDecompressor().decompress(b"compressed", 10, 10)


def test_ooz_decompressor_does_not_compress(monkeypatch):
	backend = SimpleNamespace(decompress=lambda payload, output_size: b"")
	monkeypatch.setitem(sys.modules, "ooz", backend)

	with pytest.raises(NotImplementedError, match="Windows Oodle DLL"):
		OozDecompressor().compress(b"uncompressed")


def test_ooz_decompressor_retries_independent_restart_blocks(monkeypatch):
	first_block = b"\x8c\x06\x00\x00\x00a"
	second_block = b"\x8c\x06\x00\x00\x00b"
	combined = first_block + second_block

	def decompress(payload, output_size):
		if payload == combined:
			raise RuntimeError("restart blocks cannot be decoded together")
		return payload[-1:] * output_size

	backend = SimpleNamespace(decompress=decompress)
	monkeypatch.setitem(sys.modules, "ooz", backend)
	decompressor = OozDecompressor()
	decompressor.BLOCK_SIZE = 4

	assert decompressor.decompress(combined, len(combined), 7) == b"aaaabbb"
