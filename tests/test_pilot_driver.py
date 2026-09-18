import importlib.util
import contextlib
import io
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("pilot", Path(__file__).resolve().parents[1] / "scripts" / "run_pilot.py")
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


class ConfigEncodingTests(unittest.TestCase):
    def test_generated_configuration_round_trips(self):
        value = {
            "uat_docs": {"command": "/path with spaces/python", "args": ["-m", "module"],
                         "enabled": True, "startup_timeout_sec": 60},
            "special.key": {"description": "Quotes: \"hello\"\nnewline"},
        }
        self.assertEqual(tomllib.loads("mcp_servers=" + pilot.toml_value(value))["mcp_servers"], value)

    def test_disabled_baseline_stays_false(self):
        value = {"rippletide@personal": {"enabled": False}}
        self.assertEqual(tomllib.loads("plugins=" + pilot.toml_value(value))["plugins"], value)

    def test_skill_array_round_trips(self):
        value = {"config": [{"path": "/tmp/project/.agents/skills/route/SKILL.md", "enabled": True}]}
        self.assertEqual(tomllib.loads("skills=" + pilot.toml_value(value))["skills"], value)

    def test_unsupported_values_are_not_silently_encoded(self):
        with self.assertRaises(TypeError):
            pilot.toml_value(None)


class InstalledPluginPreflightTests(unittest.TestCase):
    def test_private_user_layer_installs_and_discovers_only_plugin(self):
        with tempfile.TemporaryDirectory(prefix="rippletide-preflight-test-") as directory:
            isolated = Path(directory) / "private"
            isolated.mkdir()
            skill = f"- rippletide:route-capabilities: Router (file: {isolated}/plugins/cache/personal/rippletide/v1/skills/route-capabilities/SKILL.md)"
            with patch.object(pilot.tempfile, "mkdtemp", return_value=str(isolated)), \
                    patch.object(pilot, "run_cli", side_effect=[(0, {}), (0, [{"name": "rippletide"}]),
                                                               (0, [skill])]) as cli:
                result = pilot.installed_plugin_preflight("codex", "codex-cli 0.132.0", Path(directory))
            self.assertEqual(result["status"], "ready")
            self.assertFalse(result["task_attempted"])
            self.assertFalse(result["model_called"])
            self.assertEqual(isolated.stat().st_mode & 0o777, 0o700)
            config = tomllib.loads((isolated / "config.toml").read_text())
            self.assertEqual(config, {"plugins": {"rippletide@personal": {"enabled": True}}})
            self.assertEqual(cli.call_args_list[0].args[0], ["codex", "plugin", "add", "rippletide@personal"])
            self.assertTrue(all(call.kwargs["env"]["CODEX_HOME"] == str(isolated) for call in cli.call_args_list))

    def test_preflight_blocks_unexpected_personal_services(self):
        with tempfile.TemporaryDirectory(prefix="rippletide-preflight-test-") as directory:
            isolated = Path(directory) / "private"
            isolated.mkdir()
            with patch.object(pilot.tempfile, "mkdtemp", return_value=str(isolated)), \
                    patch.object(pilot, "run_cli", side_effect=[(0, {}),
                        (0, [{"name": "rippletide"}, {"name": "unrelated"}])]):
                result = pilot.installed_plugin_preflight("codex", "codex-cli 0.132.0", Path(directory))
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["reason_code"], "ISOLATED_PLUGIN_PREFLIGHT_FAILED")
            self.assertFalse(result["model_called"])

    def test_installed_config_archives_development_copy_and_preserves_defaults(self):
        with tempfile.TemporaryDirectory(prefix="rippletide-config-test-") as directory:
            run = Path(directory) / "run"
            workspace = run / "workspace"
            (workspace / ".codex").mkdir(parents=True)
            skill = workspace / ".agents" / "skills" / "route-capabilities"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("development fixture")
            fixture = {"model": "must-not-copy", "agents": {"max_threads": 2},
                       "mcp_servers": {"rippletide": {"command": "development"},
                                       "uat_docs": {"command": "fixture"}},
                       "plugins": {"rippletide@personal": {"enabled": False}}}
            (workspace / ".codex" / "config.toml").write_text(
                "\n".join(f"{key}={pilot.toml_value(value)}" for key, value in fixture.items()))
            isolated = Path(directory) / "private"
            isolated.mkdir()
            snapshot = pilot.installed_session_config(workspace, run, isolated, "session")
            config = tomllib.loads(snapshot.read_text())
            self.assertNotIn("model", config)
            self.assertNotIn("skills", config)
            self.assertEqual(set(config["mcp_servers"]), {"uat_docs"})
            self.assertTrue(config["plugins"]["rippletide@personal"]["enabled"])
            self.assertFalse(skill.exists())
            self.assertFalse((workspace / ".codex" / "config.toml").exists())
            self.assertTrue((snapshot.parent / "development-skill" / "SKILL.md").is_file())
            self.assertTrue((snapshot.parent / "development-config.toml").is_file())

    def test_auth_is_only_linked_then_exact_link_removed(self):
        with tempfile.TemporaryDirectory(prefix="rippletide-auth-test-") as directory:
            source_home = Path(directory) / "source"
            isolated = Path(directory) / "private"
            source_home.mkdir()
            isolated.mkdir()
            source = source_home / "auth.json"
            source.write_text("non-secret test fixture")
            with patch.dict(pilot.os.environ, {"CODEX_HOME": str(source_home),
                                              "OPENAI_API_KEY": "not-used-by-this-cli", "CODEX_API_KEY": ""}):
                link = pilot.link_auth_if_needed(isolated)
            self.assertTrue((isolated / "auth.json").is_symlink())
            pilot.remove_auth_link(link)
            self.assertFalse((isolated / "auth.json").exists())
            self.assertTrue(source.is_file())

    def test_auth_status_does_not_capture_or_emit_credentials(self):
        with patch.object(pilot.subprocess, "run") as check:
            check.return_value.returncode = 0
            self.assertTrue(pilot.isolated_authentication_ready("codex", Path("/private/test")))
            self.assertEqual(check.call_args.kwargs["stdout"], pilot.subprocess.DEVNULL)
            self.assertEqual(check.call_args.kwargs["stderr"], pilot.subprocess.DEVNULL)

    def test_direct_capture_cannot_silently_fall_back_to_development(self):
        with patch.object(pilot.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(ValueError, "Installed-plugin isolation"):
                pilot.capture_session("codex", Path("missing"), Path("missing"),
                                      "session", "prompt", 10, installed_plugin=True)
            launch.assert_not_called()

    def test_installed_mode_blocks_before_prepare_or_task(self):
        with tempfile.TemporaryDirectory(prefix="rippletide-preflight-test-") as directory:
            args = ["run_pilot.py", "--scenario", "U02", "--installed-plugin",
                    "--codex", "/test/codex", "--output-root", directory]
            with patch("sys.argv", args), patch.object(pilot.shutil, "which", return_value="/test/uv"), \
                    patch.object(pilot.subprocess, "check_output", return_value="codex-cli 0.132.0\n"), \
                    patch.object(pilot, "run_cli") as prepare, \
                    patch.object(pilot, "capture_session") as capture, \
                    patch.object(pilot, "installed_plugin_preflight", return_value={"status": "blocked"}), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(pilot.main(), 2)
            prepare.assert_not_called()
            capture.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])
            self.assertEqual(json.loads(output.getvalue())["event"], "installed_plugin_preflight")

    def test_development_mode_still_prepares_and_captures(self):
        with tempfile.TemporaryDirectory(prefix="rippletide-driver-test-") as directory:
            run = Path(directory) / "U02-D-test"
            workspace = run / "workspace"
            workspace.mkdir(parents=True)
            (run / "run.json").write_text("{}")
            prepared = {"run": str(run), "workspace": str(workspace), "prompt": "fixture prompt"}
            captured = {"exit_code": 0, "timed_out": False, "thread_id": "test",
                        "elapsed_seconds": 0, "raw_events": None, "events": str(run / "session.jsonl")}
            args = ["run_pilot.py", "--scenario", "U02", "--codex", "/test/codex",
                    "--output-root", directory]
            with patch("sys.argv", args), patch.object(pilot.shutil, "which", return_value="/test/uv"), \
                    patch.object(pilot.subprocess, "check_output", return_value="codex-cli 0.132.0\n"), \
                    patch.object(pilot, "run_cli", side_effect=[(0, prepared), (0, {}),
                                                               (0, {"status": "passed"}), (0, {})]) as cli, \
                    patch.object(pilot, "capture_session", return_value=captured) as capture, \
                    patch.object(pilot, "installed_plugin_preflight") as preflight, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pilot.main(), 0)
            self.assertIn("prepare", cli.call_args_list[0].args[0])
            capture.assert_called_once()
            self.assertFalse(capture.call_args.kwargs["installed_plugin"])
            preflight.assert_not_called()
            result = json.loads((run / "pilot-run.json").read_text())
            self.assertEqual(result["plugin_mode"], "development")
            self.assertEqual(result["status"], "needs_evidence_review")


if __name__ == "__main__":
    unittest.main()
