"""Articles and pronouns in general English names and assignment targets."""
import unittest

from shipmblang import run_direct_program

ODD_NUMBERS = "Add the odd numbers in 2, 5, 8, and 11 and show the total."


class ArticleAndPronounTests(unittest.TestCase):
    def compile(self, source):
        return run_direct_program(source, memory=False, model_provider=None)

    def test_leading_articles_bind_the_name_under_them(self):
        cases = (
            ("Let the total be 4. Show the total.", "4\n"),
            ("Let a be 1. Show a.", "1\n"),
            ("Let an amount be 5. Show an amount.", "5\n"),
            ("Start with the total at 4. Show the total.", "4\n"),
            ("Start with a at 1. Show a.", "1\n"),
            ("Let total be a mutable integer with value 1. Add 3 to total. Show total.", "4\n"),
            ("Let the total be a mutable integer with value 1. Add 8 to the total. Show the total.", "9\n"),
            ("Let total be a mutable integer with value 1. Add 8. Show total.", "9\n"),
            ("Let total be a mutable integer with value 0. Add 8 to it. Show it.", "8\n"),
            ("Let total be a mutable integer with value 1. Set it to 6. Show it.", "6\n"),
            ("Let the total be a mutable integer with value 1. Change the total to 6. Show the total.", "6\n"),
            ("Let total be a mutable integer with value 3. Multiply it by 4. Show it.", "12\n"),
            ("Let total be a mutable integer with value 8. Divide the total by 2. Show the total.", "4\n"),
        )
        for source, expected in cases:
            with self.subTest(source=source):
                result = self.compile(source)
                self.assertEqual(result["status"], "compiled", result)
                self.assertEqual(result["runtime"]["stdout"], expected)

    def test_ambiguous_it_asks_for_a_name(self):
        result = self.compile(
            "Let total be a mutable integer with value 1. "
            "Let extra be a mutable integer with value 2. Add 8 to it."
        )
        self.assertEqual(result["status"], "needs_clarification", result)
        self.assertIsNone(result["target_code"])
        self.assertNotIn("runtime", result)
        self.assertTrue(any(
            item["question"] == "Which declared value does this reference mean? Use its name."
            for item in result["clarifications"]
        ), result)

    def test_them_shows_the_single_list_and_is_not_an_integer_target(self):
        shown = self.compile("Let values be the list of integers 2, 5. Show them.")
        self.assertEqual(shown["status"], "compiled", shown)
        self.assertEqual(shown["runtime"]["stdout"], "[2, 5]\n")
        with_integer = self.compile(
            "Let total be a mutable integer with value 0. "
            "Let values be the list of integers 2, 5. Show them."
        )
        self.assertEqual(with_integer["status"], "compiled", with_integer)
        self.assertEqual(with_integer["runtime"]["stdout"], "[2, 5]\n")
        added = self.compile("Let values be the list of integers 2, 5. Add 1 to them.")
        self.assertEqual(added["status"], "unsupported", added)
        self.assertIsNone(added["target_code"])
        self.assertNotIn("runtime", added)
        # them binds to that one list; the list is not a mutable integer target.
        self.assertEqual(added["diagnostics"][0]["message"], "The arithmetic target must be mutable.")

    def test_odd_numbers_stay_a_clarification(self):
        result = self.compile(ODD_NUMBERS)
        self.assertEqual(result["status"], "needs_clarification", result)
        self.assertIsNone(result["target_code"])
        self.assertNotIn("runtime", result)
        questions = [item["question"] for item in result["clarifications"]]
        self.assertTrue(questions, result)
        self.assertNotEqual(questions, ["Name the arithmetic target explicitly."])
        combined = " ".join(questions)
        self.assertNotEqual(combined, "Name the arithmetic target explicitly.")
        self.assertTrue("for each" in combined.lower() or "not an integer update" in combined.lower(), result)

    def test_integer_implicit_add_still_names_a_missing_target(self):
        for source in (
            "Add 3.",
            "Let total be a mutable integer with value 1. Let extra be a mutable integer with value 2. Add 3.",
        ):
            with self.subTest(source=source):
                result = self.compile(source)
                self.assertEqual(result["status"], "needs_clarification", result)
                self.assertIsNone(result["target_code"])
                self.assertEqual(
                    [item["question"] for item in result["clarifications"]],
                    ["Name the arithmetic target explicitly."],
                    result,
                )

    def test_reserved_name_mentions_the_word(self):
        result = self.compile("Let if be 1.")
        self.assertNotEqual(result["status"], "compiled", result)
        self.assertIsNone(result["target_code"])
        messages = [item["message"] for item in result["diagnostics"]]
        messages += [item["question"] for item in result["clarifications"]]
        self.assertTrue(any("'if' is reserved." in message for message in messages), result)
        function = self.compile("Define a function if returning integer.")
        function_messages = [item["message"] for item in function["diagnostics"]]
        function_messages += [item["question"] for item in function["clarifications"]]
        self.assertTrue(any("'if' is reserved." in message for message in function_messages), function)


if __name__ == "__main__":
    unittest.main()
