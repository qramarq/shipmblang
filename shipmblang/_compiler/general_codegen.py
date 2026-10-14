"""Resolved English syntax directly to the final general bytecode buffer."""
from copy import deepcopy

from .general_english import GRAMMAR_VERSION


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
        elif kind == "Index":
            expression(value["value"])
            expression(value["index"])
            emit("index", {}, value)
        elif kind == "Call":
            for argument in value["arguments"]:
                expression(argument)
            emit("call", {"function": value["function"], "argument_types": value["argument_types"], "return_type": value["type"]}, value)
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

    def block(body):
        for statement in body:
            kind = statement["kind"]
            if kind in {"Declare", "Assign"}:
                expression(statement["value"])
                emit("store", {"slot": statement["slot"]}, statement)
            elif kind == "Return":
                expression(statement["value"])
                emit("return", {}, statement)
                return True
            elif kind == "Show":
                effects.add("captured_output")
                expression(statement["value"])
                emit("show", {}, statement)
            elif kind == 'VLC':
                vlc(statement)
            elif kind == "FFmpeg":
                capabilities.add("ffmpeg")
                effects.add("host_media")
                for argument in statement['arguments']:
                    expression(argument)
                emit('ffmpeg_execute', {'job': deepcopy(statement['job']),
                     'argument_types': [a['type'] for a in statement['arguments']]}, statement)
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
        compiled = emit_general(definition, {"locals": definition["locals"]}, function=True)
        effects.update(compiled["runtime_contract"]["effects"])
        capabilities.update(compiled["runtime_contract"]["required_capabilities"])
        functions.append({"id": definition["id"], "name": definition["name"], "parameter_slots": definition["parameter_slots"],
                          "return_type": definition["return_type"], "locals": compiled["locals"], "bytecode": compiled["bytecode"]})
    if len(locals_) > 10000 or len(functions) > 10000:
        raise GeneralLimitError("Program exceeds the supported number of locals or functions.")
    return {"producer": "shipmbcompiler", "target": "shipmblang-bytecode", "version": "0.5" if 'vlc' in capabilities else "0.4" if 'ffmpeg' in capabilities else "0.3",
            "profile": "general", "native_machine_code": False, "bytecode": code, "locals": locals_, "functions": functions,
            "debug": {"producer": "shipmbcompiler", "pipeline": "direct", "grammar": GRAMMAR_VERSION},
            "runtime_contract": {"effects": sorted(effects), "required_capabilities": sorted(capabilities)}}
