"""Resolved English syntax directly to the final general bytecode buffer."""
from copy import deepcopy

from .general_english import GRAMMAR_VERSION
from .vision import MODEL_SHA256


class GeneralLimitError(ValueError):
    pass


def emit_general(tree, symbols, *, function=False):
    code, locals_ = [], deepcopy(symbols["locals"])
    capabilities = set()
    effects = set()

    def emit(opcode, operands, source):
        if len(code) >= 10000:
            raise GeneralLimitError("Program exceeds the 10000-instruction limit per execution frame.")
        pc = len(code)
        code.append({"pc": pc, "opcode": opcode, "operands": operands, "source_span": dict(source["span"]),
                     "origin": "bookkeeping" if source["kind"] in {"For", "While", "If", "Program"} or opcode == "clear" else "source"})
        return pc

    def patch(pc):
        code[pc]["operands"]["target"] = len(code)

    def hidden(kind):
        slot = len(locals_)
        locals_.append({"id": slot, "name": f"$temporary{slot}", "type": kind, "mutable": True})
        return slot

    def expression(value):
        kind = value["kind"]
        if kind == 'VLCQuery':
            vlc(value,query=True)
        elif kind == 'VisionQuery':
            vision(value)
        elif kind == "Literal":
            emit("const", {"value": value["value"], "type": value["type"]}, value)
        elif kind == "Name":
            emit("load", {"slot": value["slot"]}, value)
        elif kind == "List":
            for item in value["values"]:
                expression(item)
            emit("make_list", {"count": len(value["values"]), "element_type": value["type"][5:-1]}, value)
        elif kind == "Unary":
            expression(value["operand"])
            emit("unary", {"operator": value["operator"]}, value)
        elif kind == "Binary":
            expression(value["left"])
            operator = value["operator"]
            if operator in {"and", "or"}:
                branch = emit("jump_if_false", {"target": 0}, value)
                if operator == "and":
                    expression(value["right"])
                else:
                    emit("const", {"value": True, "type": "boolean"}, value)
                done = emit("jump", {"target": 0}, value)
                patch(branch)
                if operator == "and":
                    emit("const", {"value": False, "type": "boolean"}, value)
                else:
                    expression(value["right"])
                patch(done)
            else:
                expression(value["right"])
                emit("binary", {"operator": operator}, value)
        elif kind == "Length":
            expression(value["value"])
            emit("length", {}, value)
        elif kind == "TextSeg":
            argument_types = []
            for argument in value["arguments"]:
                expression(argument)
                argument_types.append(argument["type"])
            emit("text_segment", {"operation": value["operation"], "argument_types": argument_types, "return_type": value["type"]}, value)
        elif kind == "Index":
            expression(value["value"])
            expression(value["index"])
            emit("index", {}, value)
        elif kind == "Call":
            for argument in value["arguments"]:
                expression(argument)
            emit("call", {"function": value["function"], "argument_types": value["argument_types"], "return_type": value["type"]}, value)
        elif kind == "MethodCall":
            for argument in value["arguments"]:
                expression(argument)
            choice = _method_choice(value, tree.get("layouts") or [], tree.get("interfaces") or [])
            if choice[0] == "call":
                emit("call", {"function": choice[1], "argument_types": choice[2], "return_type": value["type"]}, value)
            else:
                emit("call_virtual", {"slot": value["slot"], "argument_types": value["static_types"], "return_type": value["type"]}, value)
        elif kind == "IsInstance":
            expression(value["value"])
            emit("is_instance", {"layout": value["layout"]}, value)
        elif kind == "New":
            temps = [hidden(field_type) for field_type in value["field_types"]]
            for offset in value["order"]:
                expression(value["values"][offset])
                emit("store", {"slot": temps[offset]}, value)
            for temp in temps:
                emit("load", {"slot": temp}, value)
            emit("new_object", {"layout": value["layout"]}, value)
            for temp in temps:
                emit("clear", {"slot": temp}, value)
        elif kind == "FieldGet":
            expression(value["value"])
            emit("get_field", {"layout": value["layout"], "offset": value["offset"], "type": value["type"]}, value)
        else:
            raise ValueError(f"Unknown resolved expression: {kind}")

    def clear(slots, source):
        for slot in slots:
            emit("clear", {"slot": slot}, source)

    def vlc(value,query=False):
        capabilities.add('vlc'); effects.add('host_media')
        for argument in value['arguments']: expression(argument)
        operands={'operation':value['operation'],'argument_types':[a['type'] for a in value['arguments']]}
        if query: operands['return_type']=value['type']
        emit('vlc_query' if query else 'vlc_execute',operands,value)

    def vision(value):
        capabilities.add('vision')
        effects.add('host_media')
        for argument in value['arguments']:
            expression(argument)
        emit('vision_query', {
            'operation': value['operation'],
            'argument_types': [argument['type'] for argument in value['arguments']],
            'return_type': value['type'],
            'model_sha256': MODEL_SHA256,
        }, value)

    def block(body):
        for statement in body:
            kind = statement["kind"]
            if kind in {"Declare", "Assign"}:
                expression(statement["value"])
                emit("store", {"slot": statement["slot"]}, statement)
            elif kind == "Append":
                emit("load", {"slot": statement["slot"]}, statement)
                expression(statement["value"])
                emit("append", {}, statement)
                emit("store", {"slot": statement["slot"]}, statement)
            elif kind == "Return":
                expression(statement["value"])
                emit("return", {}, statement)
                return True
            elif kind == "Show":
                effects.add("captured_output")
                expression(statement["value"])
                emit("show", {}, statement)
            elif kind == "UpdateField":
                emit("load", {"slot": statement["slot"]}, statement)
                expression(statement["value"])
                emit("set_field", {"layout": statement["layout"], "offset": statement["offset"], "type": statement["field_types"][statement["offset"]]}, statement)
                emit("store", {"slot": statement["slot"]}, statement)
            elif kind == 'VLC':
                vlc(statement)
            elif kind == "FFmpeg":
                capabilities.add("ffmpeg")
                effects.add("host_media")
                for argument in statement['arguments']:
                    expression(argument)
                emit('ffmpeg_execute', {'job': deepcopy(statement['job']),
                     'argument_types': [a['type'] for a in statement['arguments']]}, statement)
            elif kind == "FFmpegProbe":
                capabilities.add("ffmpeg")
                effects.add("host_media")
                effects.add("captured_output")
                for argument in statement['arguments']:
                    expression(argument)
                emit('ffmpeg_probe', {'argument_types': [a['type'] for a in statement['arguments']]}, statement)
                emit('show', {}, statement)
            elif kind == "If":
                expression(statement["condition"])
                otherwise = emit("jump_if_false", {"target": 0}, statement)
                yes_returns = block(statement["yes"])
                if not yes_returns:
                    clear(statement["yes_slots"], statement)
                if statement["no"]:
                    done = emit("jump", {"target": 0}, statement) if not yes_returns else None
                    patch(otherwise)
                    no_returns = block(statement["no"])
                    if not no_returns:
                        clear(statement["no_slots"], statement)
                    if done is not None:
                        patch(done)
                    if yes_returns and no_returns:
                        return True
                else:
                    patch(otherwise)
            elif kind == "For":
                sequence, index = hidden(statement["value"]["type"]), hidden("integer")
                expression(statement["value"])
                emit("store", {"slot": sequence}, statement)
                emit("const", {"value": 0, "type": "integer"}, statement)
                emit("store", {"slot": index}, statement)
                start = len(code)
                emit("load", {"slot": index}, statement)
                emit("load", {"slot": sequence}, statement)
                emit("length", {}, statement)
                emit("binary", {"operator": "less"}, statement)
                end = emit("jump_if_false", {"target": 0}, statement)
                emit("load", {"slot": sequence}, statement)
                emit("load", {"slot": index}, statement)
                emit("index", {}, statement)
                emit("store", {"slot": statement["slot"]}, statement)
                if not block(statement["body"]):
                    clear(statement["scoped_slots"], statement)
                    emit("load", {"slot": index}, statement)
                    emit("const", {"value": 1, "type": "integer"}, statement)
                    emit("binary", {"operator": "add"}, statement)
                    emit("store", {"slot": index}, statement)
                    emit("jump", {"target": start}, statement)
                patch(end)
                clear([sequence, index], statement)
            elif kind == "While":
                start = len(code)
                expression(statement["condition"])
                end = emit("jump_if_false", {"target": 0}, statement)
                if not block(statement["body"]):
                    clear(statement["scoped_slots"], statement)
                    emit("jump", {"target": start}, statement)
                patch(end)
            else:
                raise ValueError(f"Unknown resolved statement: {kind}")

        return False

    terminal = block(tree["body"])
    if not function:
        emit("halt", {}, tree)
    elif not terminal:
        raise ValueError("A function has an unresolved return path.")
    functions = []
    for definition in tree.get("functions", []):
        definition["layouts"] = tree.get("layouts") or []
        definition["interfaces"] = tree.get("interfaces") or []
        compiled = emit_general(definition, {"locals": definition["locals"]}, function=True)
        effects.update(compiled["runtime_contract"]["effects"])
        capabilities.update(compiled["runtime_contract"]["required_capabilities"])
        functions.append({"id": definition["id"], "name": definition["name"], "parameter_slots": definition["parameter_slots"],
                          "return_type": definition["return_type"], "locals": compiled["locals"], "bytecode": compiled["bytecode"]})
    if len(locals_) > 10000 or len(functions) > 10000:
        raise GeneralLimitError("Program exceeds the supported number of locals or functions.")
    raw_layouts = tree.get("layouts") or []
    id_map = {}
    layouts = []
    if not function:
        staged = []
        for layout in raw_layouts:
            id_map[layout["id"]] = len(staged)
            published = {"id": len(staged), "name": layout["name"], "fields": layout["fields"]}
            if layout.get("methods"):
                published["methods"] = layout["methods"]
            if layout.get("implements"):
                published["implements"] = layout["implements"]
            staged.append(published)
        for layout, published in zip(raw_layouts, staged):
            if "parent" in layout:
                published["parent"] = id_map[layout["parent"]]
        layouts.extend(staged)

        def remap(instructions):
            for instruction in instructions:
                if instruction["opcode"] in {"new_object", "get_field", "set_field", "is_instance"}:
                    instruction["operands"]["layout"] = id_map[instruction["operands"]["layout"]]

        remap(code)
        for compiled_function in functions:
            remap(compiled_function["bytecode"])
    contract = {"effects": sorted(effects), "required_capabilities": sorted(capabilities)}
    artifact = {"producer": "shipmbcompiler", "target": "shipmblang-bytecode", "version": "0.6" if 'vision' in capabilities else "0.5" if 'vlc' in capabilities else "0.4" if 'ffmpeg' in capabilities else "0.3",
            "profile": "general", "native_machine_code": False, "bytecode": code, "locals": locals_, "functions": functions,
            "debug": {"producer": "shipmbcompiler", "pipeline": "direct", "grammar": GRAMMAR_VERSION},
            "runtime_contract": contract}
    if layouts:
        artifact["layouts"] = layouts
        if tree.get("interfaces"):
            artifact["interfaces"] = tree["interfaces"]
        contract["features"] = _object_features(artifact)
    return artifact


def _composed_type(kind):
    if not isinstance(kind, str):
        return False
    if kind.startswith("object[") or kind.startswith("interface["):
        return True
    if kind.startswith("list[") and kind.endswith("]"):
        inner = kind[5:-1]
        return inner.startswith("object[") or inner.startswith("interface[")
    return False


def _object_features(artifact):
    features = ["objects"]
    composed = any(_composed_type(field["type"]) for layout in artifact["layouts"] for field in layout["fields"])
    for function in artifact["functions"]:
        types = [function["return_type"], *(slot["type"] for slot in function["locals"] if slot["id"] in function["parameter_slots"])]
        composed = composed or any(_composed_type(kind) for kind in types)
        for instruction in function["bytecode"]:
            if instruction["opcode"] == "make_list" and _composed_type(instruction["operands"].get("element_type", "")):
                composed = True
    for instruction in artifact["bytecode"]:
        if instruction["opcode"] == "make_list" and _composed_type(instruction["operands"].get("element_type", "")):
            composed = True
    if composed:
        features.append("object_composition")
    if any(layout.get("methods") for layout in artifact["layouts"]):
        features.append("methods")
    if any("parent" in layout for layout in artifact["layouts"]):
        features.append("inheritance")
    if artifact.get("interfaces"):
        features.append("interfaces")
    return features


def _extends(layout_id, ancestor_id, layouts):
    seen = set()
    current = layout_id
    while current not in seen:
        if current == ancestor_id:
            return True
        seen.add(current)
        parent = layouts[current].get("parent")
        if parent is None:
            return False
        current = parent
    return False


def _method_choice(node, layouts, interfaces):
    """Return ('call', function id, argument types) or ('virtual',)."""
    by_id = {layout["id"]: layout for layout in layouts}

    def resolve(layout_id):
        seen = set()
        current = layout_id
        while current not in seen:
            seen.add(current)
            for method in by_id[current].get("methods", []):
                if method["slot"] == node["slot"]:
                    return method
            parent = by_id[current].get("parent")
            if parent is None:
                return None
            current = parent
        return None

    def possible():
        static = node["static_type"]
        if static.startswith("interface["):
            name = static[len("interface["):-1]
            interface = next(item for item in interfaces if item["name"] == name)
            roots = []
            for layout in layouts:
                current = layout["id"]
                seen = set()
                while current not in seen:
                    seen.add(current)
                    if interface["id"] in by_id[current].get("implements", []):
                        roots.append(layout["id"])
                        break
                    parent = by_id[current].get("parent")
                    if parent is None:
                        break
                    current = parent
            return [layout["id"] for layout in layouts if any(_extends(layout["id"], root, by_id) for root in roots)]
        name = static[len("object["):-1]
        root = next(layout["id"] for layout in layouts if layout["name"] == name)
        return [layout["id"] for layout in layouts if _extends(layout["id"], root, by_id)]

    if node["static_type"].startswith("interface["):
        return ("virtual",)
    if node.get("fixed"):
        method = resolve(next(layout["id"] for layout in layouts if layout["name"] == node["static_type"][len("object["):-1]))
        return ("call", method["function"], method["parameter_types"])
    ids = {}
    for layout_id in possible():
        method = resolve(layout_id)
        if method is not None:
            ids[method["function"]] = method
    if len(ids) == 1:
        method = next(iter(ids.values()))
        return ("call", method["function"], method["parameter_types"])
    return ("virtual",)
