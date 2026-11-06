from subprocess import TimeoutExpired
from unittest.mock import MagicMock, call, patch

from modules.formats.utils import lua_conversion


def test_bin_to_lua_retries_nonzero_result_with_s_flag():
	failed = MagicMock(returncode=1)
	failed.communicate.return_value = (b"-- Decompiled using luadec", b"cannot find blockend")
	succeeded = MagicMock(returncode=0)
	succeeded.communicate.return_value = (b"return true", b"")

	with patch("utils.shared.resolve_binary", return_value="/usr/bin/luadec"), \
		patch.object(lua_conversion, "invocation_for_binary", return_value=(["/usr/bin/luadec"], lambda p: p)), \
		patch.object(lua_conversion.subprocess, "Popen", side_effect=[failed, succeeded]) as popen:
		output, err = lua_conversion.bin_to_lua("/tmp/example.lua.bin")

	assert output == b"return true"
	assert err == ""
	assert popen.call_args_list == [
		call(
			["/usr/bin/luadec", "/tmp/example.lua.bin"],
			stdout=lua_conversion.subprocess.PIPE,
			stderr=lua_conversion.subprocess.PIPE,
		),
		call(
			["/usr/bin/luadec", "-s", "/tmp/example.lua.bin"],
			stdout=lua_conversion.subprocess.PIPE,
			stderr=lua_conversion.subprocess.PIPE,
		),
	]


def test_bin_to_lua_uses_noninteractive_wine_environment():
	proc = MagicMock(returncode=0)
	proc.communicate.return_value = (b"return true", b"")

	with patch("utils.shared.resolve_binary", return_value="/tmp/luadec.exe"), \
		patch.object(lua_conversion, "invocation_for_binary", return_value=(["wine", "/tmp/luadec.exe"], lambda p: p)), \
		patch.object(lua_conversion, "wine_env", return_value={"WINEDEBUG": "-all"}), \
		patch.object(lua_conversion.subprocess, "Popen", return_value=proc) as popen:
		output, err = lua_conversion.bin_to_lua("/tmp/example.lua.bin")

	assert output == b"return true"
	assert err == ""
	popen.assert_called_once_with(
		["wine", "/tmp/luadec.exe", "/tmp/example.lua.bin"],
		stdout=lua_conversion.subprocess.PIPE,
		stderr=lua_conversion.subprocess.PIPE,
		env={"WINEDEBUG": "-all"},
	)


def test_bin_to_lua_kills_timed_out_attempt_then_retries_with_s_flag():
	timed_out = MagicMock()
	timed_out.communicate.side_effect = [TimeoutExpired("luadec", 10), (b"", b"timed out")]
	succeeded = MagicMock(returncode=0)
	succeeded.communicate.return_value = (b"return true", b"")

	with patch("utils.shared.resolve_binary", return_value="/usr/bin/luadec"), \
		patch.object(lua_conversion, "invocation_for_binary", return_value=(["/usr/bin/luadec"], lambda p: p)), \
		patch.object(lua_conversion.subprocess, "Popen", side_effect=[timed_out, succeeded]) as popen:
		output, err = lua_conversion.bin_to_lua("/tmp/example.lua.bin")

	assert output == b"return true"
	assert err == ""
	timed_out.kill.assert_called_once_with()
	assert popen.call_args_list[1].args[0] == ["/usr/bin/luadec", "-s", "/tmp/example.lua.bin"]
