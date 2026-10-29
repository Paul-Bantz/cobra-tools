import os
import logging
import ctypes
from ctypes import cdll, create_string_buffer, Structure, Array, c_char_p, c_void_p, c_char, c_int32, c_bool, c_uint32, POINTER
from enum import IntEnum


# Default codec
OODLE_CODEC_NAME = "Kraken"
# Larger factors will send larger buffers to each Oodle thread
INPUT_CHUNK_FACTOR = 32
# Must be divisible by 256KB
INPUT_CHUNK_SIZE = 262144 * INPUT_CHUNK_FACTOR  # Default: 8MB


# taken from quickbms oodle.c
compressions = (
    ("LZH",            0,  7),
    ("LZHLW",          1,  0),
    ("LZNIB",          2,  1),
    ("None",           3,  7),    # 0x8c->0xcc
    ("LZB16",          4,  2),
    ("LZBLW",          5,  3),
    ("LZA",            6,  4),
    ("LZNA",           7,  5),
    ("Kraken",         8,  6),    # Default
    ("Mermaid",        9, 10),
    ("BitKnit",       10, 11),
    ("Selkie",        11, 10),
    ("Hydra",         12,  6),
    ("Leviathan",     13, 12),
    ("NONE", -1, -1))

OodleCompressEnum = IntEnum('OodleEnum', list([(x[0], x[1]) for x in compressions]))
OodleDecompressEnum = IntEnum('OodleEnum', list([(x[0], x[2]) for x in compressions]))

oodle_dll = os.path.join(os.path.dirname(__file__), "oo2core_8_win64.dll")


class OodleLZ_CompressOptions(Structure):
    _pack_: 1
    _fields_ = [
        ("verbosity", c_uint32),
        ("minMatchLength", c_int32),
        ("seekChunkReset", c_bool),
        ("seekChunkLen", c_int32),
        ("profile", c_int32),
        ("dictionarySize", c_int32),
        ("spaceSpeedTradeoffBytes", c_int32),
        ("maxHuffmansPerChunk", c_int32),
        ("sendQuantumCRCs", c_bool),
        ("maxLocalDictionarySize", c_int32),
        ("makeLongRangeMatcher", c_bool),
        ("matchTableSizeLog2", c_int32),
        ("jobify", c_uint32),
        ("jobifyUserPtr", POINTER(c_void_p)),
        ("farMatchMinLen", c_int32),
        ("farMatchOffsetLog2", c_int32),
        ("reserved", c_uint32),
    ]


class OodleDecompressor:
    """
    Oodle decompression implementation.
    Requires Windows and the external Oodle library.
    """
    CHUNK_SIZE = 262144  # 256KB
    SCRATCH_SIZE = 8 * 1024 * 1024  # 8MB
    SCRATCH_MAX_SIZE = 2147483648  # 2GB

    def __init__(self, library_path: str) -> None:
        """
        Initialize instance and try to load the library.
        """
        if not os.path.exists(library_path):
            raise Exception("Could not open Oodle DLL, make sure it is configured correctly.")

        try:
            self.handle = cdll.LoadLibrary(library_path)
        except OSError as e:
            raise Exception("Could not load Oodle DLL, requires Windows and 64bit python to run.") from e

    def compress(self, payload: bytes, codec_name: str = "Kraken", level: int = 6) -> bytes:
        """
        Compress the payload using the given algorithm.
        """
        codec = OodleCompressEnum[codec_name]
        logging.debug(f"Compressing as {codec_name} (value = {codec.value}), level = {level}")
        input_size = len(payload)
        output_size = self.handle.OodleLZ_GetCompressedBufferSizeNeeded(codec.value, input_size)
        output: Array[c_char] = create_string_buffer(output_size)

        OodleLZ_CompressOptions_GetDefault: ctypes._NamedFuncPointer = self.handle.OodleLZ_CompressOptions_GetDefault
        OodleLZ_CompressOptions_GetDefault.restype = POINTER(OodleLZ_CompressOptions)

        OodleLZ_GetCompressScratchMemBound: ctypes._NamedFuncPointer = self.handle.OodleLZ_GetCompressScratchMemBound
        OodleLZ_GetCompressScratchMemBound.restype = c_int32

        comp_options = self.handle.OodleLZ_CompressOptions_GetDefault(codec.value, level)
        comp_options.contents.seekChunkReset = True
        comp_options.contents.seekChunkLen = self.CHUNK_SIZE
        comp_options.contents.makeLongRangeMatcher = False
        if input_size < self.CHUNK_SIZE:
            comp_options.contents.seekChunkLen = 0
            comp_options.contents.seekChunkReset = False

        scratch_size = OodleLZ_GetCompressScratchMemBound(codec.value, level, self.CHUNK_SIZE, comp_options)
        # Can return -1 so provide default size
        if scratch_size < 0 or scratch_size > self.SCRATCH_MAX_SIZE:
            scratch_size = self.SCRATCH_SIZE
        scratch: Array[c_char] = create_string_buffer(scratch_size)

        compressed_size = self.handle.OodleLZ_Compress(
            codec.value, c_char_p(payload), input_size, output, level, comp_options, None, None, scratch, scratch_size)

        logging.debug(f"Oodle compressed {input_size} bytes down to {compressed_size} bytes.")
        if input_size and not compressed_size:
            raise ValueError("Oodle Compression returned no payload for unknown reason!")
        return output.raw[:compressed_size]

    def decompress(self, payload: bytes, size: int, output_size: int) -> bytes:
        """
        Decompress the payload using the given size.
        """
        output = create_string_buffer(output_size)
        ret = self.handle.OodleLZ_Decompress(
            c_char_p(payload), size, output, output_size,
            0, 0, 0, None, None, None, None, None, None, 3)

        # Make sure the result length matches the given output size
        if ret != output_size:
            raise Exception(f"Decompression failed ret={ret} output_size={output_size}")

        return output.raw


class OozDecompressor:
    """Oodle decompression fallback backed by the open-source ooz library."""

    BLOCK_SIZE = 262144
    MODERN_DECODERS = (6, 10, 12)  # Kraken, Mermaid/Selkie, Leviathan

    def __init__(self) -> None:
        import ooz
        self._ooz = ooz

    def compress(self, payload: bytes, codec_name: str = "Kraken", level: int = 6) -> bytes:
        raise NotImplementedError(
            "Oodle compression requires the Windows Oodle DLL; "
            "ooz fallback only supports decompression"
        )

    def decompress(self, payload: bytes, size: int, output_size: int) -> bytes:
        payload = payload[:size]
        try:
            result = self._ooz.decompress(payload, output_size)
        except RuntimeError as direct_error:
            try:
                result = self._decompress_restart_blocks(payload, output_size)
            except (RuntimeError, ValueError):
                raise direct_error
        if len(result) != output_size:
            raise ValueError(
                f"Decompression failed output_size={len(result)} expected={output_size}"
            )
        return result

    def _decompress_restart_blocks(self, payload: bytes, output_size: int) -> bytes:
        """Decompress independently encoded modern Oodle restart blocks.

        ooz does not reset the Kraken dictionary base when a new restart block
        is encountered in one input buffer. Cobra archives can contain several
        such blocks, so retry each independently encoded block on its own.
        """
        payload_offset = 0
        output_offset = 0
        blocks = []
        while output_offset < output_size:
            block_output_size = min(self.BLOCK_SIZE, output_size - output_offset)
            block_end = self._restart_block_end(payload, payload_offset, block_output_size)
            block = self._ooz.decompress(payload[payload_offset:block_end], block_output_size)
            if len(block) != block_output_size:
                raise ValueError(
                    f"Decompression failed output_size={len(block)} expected={block_output_size}"
                )
            blocks.append(block)
            payload_offset = block_end
            output_offset += block_output_size
        if payload_offset != len(payload):
            raise ValueError(
                f"Decompression left {len(payload) - payload_offset} compressed bytes unread"
            )
        return b"".join(blocks)

    def _restart_block_end(self, payload: bytes, offset: int, output_size: int) -> int:
        if offset + 2 > len(payload):
            raise ValueError("Truncated Oodle restart block header")

        flags = payload[offset]
        decoder = payload[offset + 1] & 0x7f
        if flags & 0xbf != 0x8c or decoder not in self.MODERN_DECODERS:
            raise ValueError("Unsupported Oodle restart block")

        cursor = offset + 2
        if flags & 0x40:  # uncompressed block
            block_end = cursor + output_size
        else:
            checksum_size = 3 if payload[offset + 1] & 0x80 else 0
            if cursor + 3 + checksum_size > len(payload):
                raise ValueError("Truncated Oodle quantum header")
            quantum_header = int.from_bytes(payload[cursor:cursor + 3], "big")
            compressed_size = quantum_header & 0x3ffff
            if compressed_size != 0x3ffff:
                block_end = cursor + 3 + checksum_size + compressed_size + 1
            elif quantum_header >> 18 == 1:  # memset block
                block_end = cursor + 4
            else:
                raise ValueError("Unsupported special Oodle quantum")

        if block_end > len(payload):
            raise ValueError("Truncated Oodle restart block")
        return block_end


try:
    oodle_compressor = OodleDecompressor(oodle_dll)
except Exception as dll_error:
    logging.warning(
        "Could not load the Windows Oodle DLL (%s); trying the ooz decompression fallback",
        dll_error,
    )
    try:
        oodle_compressor = OozDecompressor()
    except Exception as ooz_error:
        logging.error(
            "No Oodle decompressor is available (%s). Install pyooz with "
            "'pip install pyooz' to extract Oodle-compressed archives.",
            ooz_error,
        )
        oodle_compressor = None
