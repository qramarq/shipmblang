import unittest

from shipmblang import compile_natural_program, run_natural_program


def reference_targets(program):
    return {
        reference.get("target")
        for reference in program["semantic_model"]["declaration_resolution"]["references"]
        if reference.get("resolved")
    }


class DeclarationResolutionTests(unittest.TestCase):
    def test_forward_function_and_variable_references_resolve_without_reordering_bytecode(self):
        program = compile_natural_program(
            "Use Python. Call helper with total. "
            "Define a function helper that takes value and returns total. "
            "Declare an integer variable total set to 0. Show program."
        )

        resolution = program["semantic_model"]["declaration_resolution"]
        self.assertEqual(resolution["name_resolution"], "order_insensitive")
        self.assertEqual(resolution["unresolved_references"], [])
        self.assertIn("function:helper", reference_targets(program))
        self.assertIn("variable:total", reference_targets(program))

        ops = program["bytecode"]
        call_index = next(index for index, op in enumerate(ops) if op.get("op") == "call")
        function_index = next(index for index, op in enumerate(ops) if op.get("op") == "define_function")
        variable_index = next(index for index, op in enumerate(ops) if op.get("op") == "declare_variable")
        self.assertLess(call_index, function_index)
        self.assertLess(function_index, variable_index)

    def test_method_owner_and_return_property_resolve_to_later_class_declaration(self):
        result = run_natural_program(
            "Use Python. Define a method add_item on class Cart that takes item and returns items. "
            "Create a class Cart with property items. Show program."
        )

        program = result["program"]
        self.assertEqual(program["semantic_model"]["declaration_resolution"]["unresolved_references"], [])
        self.assertIn("class:Cart", reference_targets(program))
        self.assertIn("property:Cart.items", reference_targets(program))

        cart = result["state"]["classes"]["Cart"]
        self.assertEqual([method["name"] for method in cart["methods"]], ["add_item"])
        self.assertEqual([property_model["name"] for property_model in cart["properties"]], ["items"])


if __name__ == "__main__":
    unittest.main()
