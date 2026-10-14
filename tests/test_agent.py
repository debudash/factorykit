import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dispatcher import agent  # noqa: E402


class AgentCommandTest(unittest.TestCase):
    def test_no_argument_carries_text_cmd_exe_would_mangle(self):
        # On Windows claude is a .cmd shim: | & < > ^ or a newline in an argument cuts the command line.
        for role in ("reviewer", "fixer"):
            with self.subTest(role):
                cmd = agent.build_agent_command(role, model="sonnet", verify={"test": "python -m unittest"})
                for arg in cmd[1:]:
                    self.assertFalse(set(arg) & set("|&<>^\n"), arg)

    def test_fixer_rules_come_from_a_file_that_exists(self):
        cmd = agent.build_agent_command("fixer")
        path = Path(cmd[cmd.index("--append-system-prompt-file") + 1])
        self.assertTrue(path.is_file())

    def test_fixer_can_commit_but_never_push(self):
        cmd = agent.build_agent_command("fixer", verify={"lint": "ruff check ."})
        allowed, denied = cmd[cmd.index("--allowedTools") + 1], cmd[cmd.index("--disallowedTools") + 1]
        self.assertIn("Bash(git commit *)", allowed)
        self.assertIn("Bash(ruff *)", allowed)
        self.assertIn("Bash(git push *)", denied)
        self.assertIn("Bash(gh *)", denied)

    def test_reviewer_is_read_only(self):
        cmd = agent.build_agent_command("reviewer", model="opus")
        self.assertEqual(cmd[cmd.index("--agent") + 1], "reviewer")
        denied = cmd[cmd.index("--disallowedTools") + 1]
        for tool in ("Edit", "Write", "Bash(git commit *)", "Bash(git push *)"):
            self.assertIn(tool, denied)

    def test_only_claude_has_an_adapter(self):
        with self.assertRaises(ValueError):
            agent.build_agent_command("fixer", harness="codex")


if __name__ == "__main__":
    unittest.main()
