import unittest

from quiet_droid.tools.bash import BashTool


class BashToolTests(unittest.TestCase):
    def test_large_output_below_hook_budget_is_not_pretruncated(self):
        tool = BashTool()

        output = tool.execute({"command": 'python3 -c "print(\'x\' * 40000)"'})

        self.assertNotIn("... (truncated) ...", output)
        self.assertGreater(len(output), 30000)


if __name__ == "__main__":
    unittest.main()
