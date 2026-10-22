"""Everyday control, list, comment, and arithmetic forms in the general grammar."""
import unittest

from shipmblang import run_direct_program


def run(source):
    return run_direct_program(source, memory=False, model_provider=None)


class ControlFormTests(unittest.TestCase):
    def assert_prints(self, source, expected):
        result = run(source)
        self.assertEqual(result["status"], "compiled", result)
        self.assertEqual(result["runtime"]["stdout"], expected, result)
        self.assertFalse([item for item in result["diagnostics"] if item.get("level") == "error"], result)
        return result

    def assert_rejected(self, source, status):
        result = run(source)
        self.assertEqual(result["status"], status, result)
        self.assertIsNone(result["target_code"])
        self.assertNotIn("runtime", result)
        return result

    def test_otherwise_if_is_one_condition(self):
        self.assert_prints(
            """Let n be 2.
If n is equal to 1 then:
Show 1.
Otherwise if n is equal to 2 then:
Show 2.
Otherwise:
Show 0.
End the condition.
""",
            "2\n",
        )
        self.assert_prints(
            """Let n be 3.
If n is equal to 1 then:
Show 1.
Otherwise if n is equal to 2 then:
Show 2.
Otherwise if n is equal to 3 then:
Show 3.
Otherwise:
Show 0.
End the condition.
""",
            "3\n",
        )
        self.assert_prints(
            """Let n be 9.
If n is equal to 1 then:
Show 1.
Otherwise if n is equal to 2 then:
Show 2.
Otherwise:
Show 0.
End the condition.
""",
            "0\n",
        )
        self.assert_prints(
            """Let n be 0.
If n is equal to 1 then:
Show 1.
Else:
Show 0.
End the condition.
""",
            "0\n",
        )
        rejected = self.assert_rejected(
            """Otherwise if true then:
Show 1.
End the condition.
""",
            "needs_clarification",
        )
        self.assertTrue(rejected["clarifications"])
        rejected = self.assert_rejected(
            """Let n be true.
If n then:
Show 1.
Otherwise if 1 then:
Show 2.
End the condition.
""",
            "unsupported",
        )
        self.assertIn("boolean", rejected["diagnostics"][0]["message"])

    def test_counted_for_and_repeat(self):
        self.assert_prints(
            """For each number from 1 to 3:
Show number.
End the loop.
""",
            "1\n2\n3\n",
        )
        self.assert_prints(
            """For each count from 1 to 3:
Show count.
End the loop.
""",
            "1\n2\n3\n",
        )
        self.assert_prints(
            """For each number from (1 plus 2) to 4:
Show number.
End the loop.
""",
            "3\n4\n",
        )
        self.assert_prints(
            """For each number from 5 to 4:
Show number.
End the loop.
""",
            "",
        )
        self.assert_prints(
            """Let values be the list of integers 7, 8.
For each value in values:
Show value.
End the loop.
""",
            "7\n8\n",
        )
        self.assert_prints(
            """Let n be a mutable integer with value 0.
While n is less than 2 do:
Set n to n plus 1.
Show n.
End the loop.
""",
            "1\n2\n",
        )
        self.assert_prints(
            """Repeat 3 times:
Show 1.
End the loop.
""",
            "1\n1\n1\n",
        )
        self.assert_prints(
            """Repeat 0 times:
Show 1.
End the loop.
""",
            "",
        )
        self.assert_prints(
            """Let n be a mutable integer with value 2.
Repeat n times:
Set n to 10.
Show 1.
End the loop.
""",
            "1\n1\n",
        )
        self.assert_prints(
            """Repeat the length of "ab" times:
Show 4.
End the loop.
""",
            "4\n4\n",
        )
        rejected = self.assert_rejected(
            """Repeat "3" times:
Show 1.
End the loop.
""",
            "unsupported",
        )
        self.assertIn("integer", rejected["diagnostics"][0]["message"])
        rejected = self.assert_rejected(
            """For each number from "a" to 2:
Show number.
End the loop.
""",
            "unsupported",
        )
        self.assertIn("integer", rejected["diagnostics"][0]["message"])

    def test_append_and_item_forms(self):
        result = self.assert_prints(
            """Let numbers be a mutable list of integers.
Append 4 to numbers.
Show numbers.
""",
            "[4]\n",
        )
        self.assertEqual(result["target_code"]["version"], "0.3")
        self.assertEqual(result["target_code"]["debug"]["grammar"], "general-english-0.10")
        self.assert_prints(
            """Let numbers be a mutable list of integers with value the empty list of integers.
Append 4 to numbers.
Append 5 to numbers.
Show numbers.
""",
            "[4, 5]\n",
        )
        self.assert_prints(
            """Let numbers be a mutable list of integers with value the list of integers 1.
Let alias be numbers.
Append 4 to numbers.
Show alias.
Show numbers.
""",
            "[1]\n[1, 4]\n",
        )
        self.assert_prints(
            """Let numbers be the list of integers 10, 20, 30.
Show the first item in numbers.
Show the last item in numbers.
Show item number 2 in numbers.
Show the item at index 0 in numbers.
Show the item at index 1 in numbers.
""",
            "10\n30\n20\n10\n20\n",
        )
        self.assert_prints(
            """Show the first item in the list of integers 4, 5, 6.
Show the last item in the list of integers 4, 5, 6.
""",
            "4\n6\n",
        )
        empty = run(
            """Let numbers be a mutable list of integers.
Show the first item in numbers.
"""
        )
        self.assertEqual(empty["status"], "compiled", empty)
        self.assertTrue(any("out of bounds" in item["message"] for item in empty["diagnostics"]))
        rejected = self.assert_rejected(
            """Let numbers be the list of integers 1.
Append 4 to numbers.
""",
            "unsupported",
        )
        self.assertIn("immutable", rejected["diagnostics"][0]["message"])
        rejected = self.assert_rejected(
            """Let numbers be a mutable list of integers.
Append "x" to numbers.
""",
            "unsupported",
        )
        self.assertIn("integer", rejected["diagnostics"][0]["message"])

    def test_comments_length_questions_and_arithmetic(self):
        self.assert_prints(
            """Show 1. # note
Show 2.
""",
            "1\n2\n",
        )
        self.assert_prints(
            """# only a comment
Show "a#b". # and show 9
Show 2.
""",
            "a#b\n2\n",
        )
        self.assert_prints('Show the length of "hello".\n', "5\n")
        self.assert_prints(
            """Let numbers be the list of integers 1, 2, 3.
Show the length of numbers.
Show the number of items in numbers.
""",
            "3\n3\n",
        )
        self.assert_rejected('Show the number of items in "hello".\n', "unsupported")
        self.assert_prints("What is the sum of 2 and 3?\n", "5\n")
        self.assert_prints("Show 7 divided by 2.\n", "3\n")
        self.assert_prints("Show the quotient of 7 and 2.\n", "3\n")
        self.assert_prints("Show negative 7 divided by 2.\n", "-3\n")
        self.assert_prints('Show "hello" plus " " plus "world".\n', "hello world\n")
        self.assert_prints('Show the sum of "hello" and " world".\n', "hello world\n")
        self.assert_prints("Show the sum of 2 and 3.\n", "5\n")
        self.assert_prints("Show (2 plus 3) times 4.\n", "20\n")
        mixed = self.assert_rejected("Show 2 plus 3 times 4.\n", "needs_clarification")
        self.assertIn("grouping", mixed["clarifications"][0]["question"])
        chained = self.assert_rejected("Show 2 plus 3 plus 4.\n", "needs_clarification")
        self.assertIn("grouping", chained["clarifications"][0]["question"])
        decimal = self.assert_rejected("Show 3.14.\n", "needs_clarification")
        self.assertIn("Decimals are unsupported", decimal["clarifications"][0]["question"])
        self.assert_prints(
            """Define a function choose with integer parameter n returning integer:
If n is equal to 1 then:
Return 1.
Otherwise if n is equal to 2 then:
Return 2.
Otherwise:
Return 0.
End the condition.
End the function.
Show the result of choose with 2.
""",
            "2\n",
        )


if __name__ == "__main__":
    unittest.main()
