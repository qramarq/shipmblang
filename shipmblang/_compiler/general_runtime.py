"""Bounded, preflight-validated stack VM for general English bytecode."""
from collections import deque
from .models import Diagnostic, Span

MAX_ITEMS = 10000
MAX_TEXT = 1000000
MAX_BITS = 4096
SCALARS = {'integer', 'boolean', 'text'}
TYPES = SCALARS | {f'list[{kind}]' for kind in SCALARS}
BINARY = {'add', 'subtract', 'multiply', 'divide', 'modulo', 'equal', 'not_equal', 'greater', 'less', 'greater_equal', 'less_equal', 'and', 'or'}
TEXT_SEGMENT = {
    'graphemes': (['text'], 'list[text]'),
    'words': (['text', 'text'], 'list[text]'),
    'sentences': (['text', 'text'], 'list[text]'),
    'chunks': (['text', 'integer', 'text'], 'list[text]'),
    'chunks_words': (['text', 'integer', 'integer', 'text'], 'list[text]'),
    'frames': (['text', 'integer'], 'list[text]'),
    'unframe': (['list[text]'], 'text'),
}
FIELDS = {'const': {'value','type'}, 'load': {'slot'}, 'store': {'slot'}, 'clear': {'slot'},
          'binary': {'operator'}, 'unary': {'operator'}, 'make_list': {'count','element_type'},
          'length': set(), 'index': set(), 'append': set(), 'jump': {'target'}, 'jump_if_false': {'target'},
          'show': set(), 'halt': set(), 'return': set(),
          'call': {'function','argument_types','return_type'},
          'text_segment': {'operation','argument_types','return_type'},
          'ffmpeg_execute': {'job', 'argument_types'},
          'ffmpeg_probe': {'argument_types'},
          'vlc_execute': {'operation','argument_types'},
          'vlc_query': {'operation','argument_types','return_type'},
          'vision_query': {'operation','argument_types','return_type','model_sha256'},
          'new_object': {'layout'},
          'get_field': {'layout', 'offset', 'type'},
          'set_field': {'layout', 'offset', 'type'},
          'call_virtual': {'slot', 'argument_types', 'return_type'},
          'is_instance': {'layout'},
          'alloc': {'type'},
          'deref_get': {'type'},
          'deref_set': {'type'},
          'release': {'slot'},
          'same_object': set()}
FEATURE_NAMES = ('objects', 'object_composition', 'methods', 'inheritance', 'interfaces', 'references', 'equality')

class ObjectValue:
    """Immutable object value: layout id plus field values in offset order."""
    __slots__ = ('layout', 'fields')

    def __init__(self, layout, fields):
        self.layout = layout
        self.fields = tuple(fields)


class RefValue:
    """Handle to a shared object cell. owning counts toward the cell; stale was released."""
    __slots__ = ('cell', 'owning', 'stale')

    def __init__(self, cell, owning=True, stale=False):
        self.cell = cell
        self.owning = owning
        self.stale = stale


class VMError(ValueError):
    def __init__(self, message, pc=0):
        super().__init__(message)
        self.pc = pc


def _object_name(kind):
    if isinstance(kind, str) and kind.startswith('object[') and kind.endswith(']') and '[' not in kind[7:-1]:
        return kind[7:-1]
    return None


def _ref_target(kind):
    if isinstance(kind, str) and kind.startswith('ref[') and kind.endswith(']'):
        inner = kind[4:-1]
        if _object_name(inner):
            return inner
    return None


def _contains_object(kind):
    if _object_name(kind):
        return True
    if isinstance(kind, str) and kind.startswith('list[') and kind.endswith(']'):
        return _contains_object(kind[5:-1])
    return False


def _interface_name(kind):
    if isinstance(kind, str) and kind.startswith('interface[') and kind.endswith(']') and '[' not in kind[10:-1]:
        return kind[10:-1]
    return None


def _composed(kind):
    """Object or interface used as a parameter, result, field, or list element."""
    if _object_name(kind) or _interface_name(kind):
        return True
    if isinstance(kind, str) and kind.startswith('list[') and kind.endswith(']'):
        inner = kind[5:-1]
        return _object_name(inner) is not None or _interface_name(inner) is not None
    return False


def _flat_fields(layout, layouts):
    fields = layout['fields']
    parent = layout.get('parent')
    if parent is None:
        return fields
    return _flat_fields(layouts[parent], layouts) + fields


def _field_layout_ok(obj, layout_id, layouts, features):
    if not isinstance(obj, ObjectValue):
        return False
    if obj.layout == layout_id:
        return True
    return 'inheritance' in features and _extends(obj.layout, layout_id, layouts)


def _resolve_method(layout, slot, layouts):
    seen = set()
    current = layout
    while current is not None and current['id'] not in seen:
        seen.add(current['id'])
        for method in current.get('methods', ()):
            if method['slot'] == slot:
                return method
        parent = current.get('parent')
        current = layouts[parent] if parent is not None else None
    return None


def _virtual_signature(args, layouts, interfaces, features):
    types = args['argument_types']
    if not types or any(type(kind) is not str for kind in types):
        return False
    receiver = types[0]
    kind, iface = _object_name(receiver), _interface_name(receiver)
    if kind:
        layout = _layout_named(kind, layouts)
        method = _resolve_method(layout, args['slot'], layouts) if layout is not None else None
        if method is None or not _subtype(receiver, method['parameter_types'][0], layouts, interfaces, features):
            return False
    elif iface:
        interface = next((item for item in interfaces if item['name'] == iface), None)
        method = next((item for item in interface['methods'] if item['slot'] == args['slot']), None) if interface else None
        if method is None or method['parameter_types'][0] != receiver:
            return False
    else:
        return False
    return (method['parameter_types'][1:] == list(types[1:]) and method['return_type'] == args['return_type']
            and all(_type_known(item, layouts, interfaces) for item in (*types, args['return_type'])))


def _extends(layout_id, ancestor_id, layouts):
    seen = set()
    current = layout_id
    while current not in seen:
        if current == ancestor_id:
            return True
        seen.add(current)
        parent = layouts[current].get('parent')
        if parent is None:
            return False
        current = parent
    return False


def _implements(layout, interface_id, layouts):
    seen = set()
    current = layout
    while current['id'] not in seen:
        seen.add(current['id'])
        if interface_id in current.get('implements', ()):
            return True
        parent = current.get('parent')
        if parent is None:
            return False
        current = layouts[parent]
    return False


def _layout_named(name, layouts):
    for layout in layouts:
        if layout['name'] == name:
            return layout
    return None


def _subtype(actual, expected, layouts, interfaces, features):
    if actual == expected:
        return True
    if 'inheritance' in features:
        child, parent = _object_name(actual), _object_name(expected)
        if child and parent:
            child_layout, parent_layout = _layout_named(child, layouts), _layout_named(parent, layouts)
            if child_layout and parent_layout and _extends(child_layout['id'], parent_layout['id'], layouts):
                return True
    if 'interfaces' in features:
        kind, iface = _object_name(actual), _interface_name(expected)
        if kind and iface:
            layout = _layout_named(kind, layouts)
            interface = next((item for item in interfaces if item['name'] == iface), None)
            if layout and interface and _implements(layout, interface['id'], layouts):
                return True
    return False


def _value(value, kind, layouts=None):
    if kind == 'integer': return type(value) is int and value.bit_length() <= MAX_BITS
    if kind == 'boolean': return type(value) is bool
    if kind == 'text': return type(value) is str and len(value.encode('utf-8')) <= MAX_TEXT
    name = _object_name(kind)
    if name is not None:
        if not isinstance(value, ObjectValue) or layouts is None:
            return False
        layout = next((item for item in layouts if item['name'] == name and item['id'] == value.layout), None)
        flat = _flat_fields(layout, layouts) if layout is not None else None
        return (flat is not None and len(value.fields) == len(flat)
                and all(_value(item, field['type'], layouts) for item, field in zip(value.fields, flat)))
    return (isinstance(kind, str) and kind.startswith('list[') and type(value) is list
            and len(value) <= MAX_ITEMS and all(_value(item, kind[5:-1], layouts) for item in value))


def _features(contract):
    if 'features' not in contract:
        return []
    features = contract['features']
    if not isinstance(features, list):
        raise VMError('Invalid feature list.')
    seen = set()
    for item in features:
        if type(item) is not str or item not in FEATURE_NAMES:
            raise VMError('Unknown feature requirement.')
        if item in seen:
            raise VMError('Duplicate feature requirement.')
        seen.add(item)
    for name in ('object_composition', 'methods', 'inheritance', 'interfaces', 'references', 'equality'):
        if name in seen and 'objects' not in seen:
            raise VMError(f'Feature {name} requires objects.')
    if 'interfaces' in seen and 'methods' not in seen:
        raise VMError('Feature interfaces requires methods.')
    if [name for name in FEATURE_NAMES if name in seen] != features:
        raise VMError('Invalid feature list.')
    return features


def _type_known(kind, layouts, interfaces):
    if kind in TYPES:
        return True
    name = _object_name(kind)
    if name is not None:
        return _layout_named(name, layouts) is not None
    iface = _interface_name(kind)
    if iface is not None:
        return any(item['name'] == iface for item in interfaces)
    if isinstance(kind, str) and kind.startswith('list[') and kind.endswith(']') and kind.count('[') == 1:
        return kind[5:-1] in SCALARS
    if isinstance(kind, str) and kind.startswith('list[') and kind.endswith(']'):
        return _type_known(kind[5:-1], layouts, interfaces)
    return False


def _interfaces(artifact, features):
    present = 'interfaces' in artifact
    wanted = 'interfaces' in features
    if wanted != present:
        raise VMError('Interfaces feature and interfaces must agree.')
    if not wanted:
        return []
    items = artifact['interfaces']
    if not isinstance(items, list) or not items or len(items) > MAX_ITEMS:
        raise VMError('Invalid interface table.')
    names = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict) or set(item) != {'id', 'name', 'methods'}:
            raise VMError('Invalid interface.')
        if type(item.get('id')) is not int or item['id'] != index or type(item.get('name')) is not str or not item['name'] or item['name'] in names:
            raise VMError('Invalid interface.')
        methods = item.get('methods')
        if not isinstance(methods, list) or not methods or len(methods) > 256:
            raise VMError('Invalid interface methods.')
        seen = set()
        for method in methods:
            if (not isinstance(method, dict) or set(method) != {'name', 'slot', 'parameter_types', 'return_type'}
                    or type(method.get('name')) is not str or not method['name'] or method['name'] in seen
                    or type(method.get('slot')) is not int or method['slot'] < 0
                    or not isinstance(method.get('parameter_types'), list) or not method['parameter_types']
                    or method['parameter_types'][0] != f"interface[{item['name']}]"
                    or type(method.get('return_type')) is not str):
                raise VMError('Invalid interface method.')
            seen.add(method['name'])
        names.add(item['name'])
    return items


def _layouts(artifact, features, interfaces):
    objects = 'objects' in features
    layouts = artifact['layouts'] if 'layouts' in artifact else []
    if not isinstance(layouts, list) or len(layouts) > MAX_ITEMS:
        raise VMError('Invalid layout table.')
    if objects != bool(layouts):
        raise VMError('Objects feature and layouts must agree.')
    names, has_parent, has_methods = set(), False, False
    allowed = {'id', 'name', 'fields'}
    if 'inheritance' in features:
        allowed.add('parent')
    if 'methods' in features:
        allowed.add('methods')
    if 'interfaces' in features:
        allowed.add('implements')
    for index, layout in enumerate(layouts):
        if not isinstance(layout, dict) or not {'id', 'name', 'fields'} <= set(layout) <= allowed:
            raise VMError('Invalid layout.')
        if type(layout.get('id')) is not int or layout['id'] != index or type(layout.get('name')) is not str or not layout['name'] or layout['name'] in names:
            raise VMError('Invalid layout.')
        if 'parent' in layout:
            has_parent = True
            parent = layout['parent']
            if type(parent) is not int or not 0 <= parent < index:
                raise VMError('Invalid layout.')
        base = len(_flat_fields(layouts[layout['parent']], layouts)) if 'parent' in layout else 0
        fields = layout.get('fields')
        if not isinstance(fields, list) or len(fields) > 256 or base + len(fields) > 256:
            raise VMError('Invalid layout fields.')
        if 'parent' not in layout and not 1 <= len(fields) <= 256:
            raise VMError('Invalid layout fields.')
        if base + len(fields) < 1:
            raise VMError('Invalid layout fields.')
        seen = set()
        for offset, field in enumerate(fields):
            field_keys = {'name', 'type', 'offset'}
            if 'methods' in features:
                field_keys.add('private')
            if (not isinstance(field, dict) or not {'name', 'type', 'offset'} <= set(field) <= field_keys
                    or type(field.get('name')) is not str or not field['name'] or field['name'] in seen
                    or type(field.get('offset')) is not int or field['offset'] != base + offset
                    or type(field.get('type')) is not str):
                raise VMError('Invalid layout field.')
            if 'private' in field and field['private'] is not True:
                raise VMError('Invalid layout field.')
            if field['type'] not in TYPES and not (
                    'object_composition' in features and (
                        _object_name(field['type']) or _interface_name(field['type'])
                        or (field['type'].startswith('list[') and (_object_name(field['type'][5:-1]) or _interface_name(field['type'][5:-1]))))):
                raise VMError('Invalid layout field.')
            seen.add(field['name'])
        if 'methods' in layout:
            has_methods = True
            methods = layout['methods']
            if not isinstance(methods, list) or not methods or len(methods) > 256:
                raise VMError('Invalid layout.')
            slots, method_names = set(), set()
            for method in methods:
                if (not isinstance(method, dict)
                        or set(method) != {'name', 'slot', 'function', 'fixed', 'parameter_types', 'return_type'}
                        or type(method.get('name')) is not str or not method['name'] or method['name'] in method_names
                        or type(method.get('slot')) is not int or method['slot'] < 0 or method['slot'] in slots
                        or type(method.get('function')) is not int or method['function'] < 0
                        or type(method.get('fixed')) is not bool
                        or not isinstance(method.get('parameter_types'), list) or not method['parameter_types']
                        or method['parameter_types'][0] != f"object[{layout['name']}]"
                        or type(method.get('return_type')) is not str):
                    raise VMError('Invalid layout.')
                slots.add(method['slot'])
                method_names.add(method['name'])
        if 'implements' in layout:
            claimed = layout['implements']
            if not isinstance(claimed, list) or not claimed or any(type(item) is not int or not 0 <= item < len(interfaces) for item in claimed) or len(set(claimed)) != len(claimed):
                raise VMError('Invalid layout.')
        names.add(layout['name'])
    if has_parent != ('inheritance' in features):
        raise VMError('Inheritance feature and layouts must agree.')
    if has_methods != ('methods' in features):
        raise VMError('Methods feature and layouts must agree.')
    for layout in layouts:
        for field in layout['fields']:
            if not _type_known(field['type'], layouts, interfaces):
                raise VMError('Invalid layout field.')
        for method in layout.get('methods', []):
            if not all(_type_known(kind, layouts, interfaces) for kind in method['parameter_types']) or not _type_known(method['return_type'], layouts, interfaces):
                raise VMError('Invalid layout.')
            parent_id = layout.get('parent')
            while parent_id is not None:
                parent = layouts[parent_id]
                ancestor = next((item for item in parent.get('methods', []) if item['name'] == method['name']), None)
                if ancestor:
                    if ancestor['fixed']:
                        raise VMError('Invalid layout.')
                    if (ancestor['slot'] != method['slot'] or ancestor['parameter_types'][1:] != method['parameter_types'][1:]
                            or ancestor['return_type'] != method['return_type']):
                        raise VMError('Invalid layout.')
                    break
                else:
                    taken = {item['slot'] for item in parent.get('methods', [])}
                    if method['slot'] in taken:
                        raise VMError('Invalid layout.')
                parent_id = parent.get('parent')
    for interface in interfaces:
        for method in interface['methods']:
            if not all(_type_known(kind, layouts, interfaces) for kind in method['parameter_types']) or not _type_known(method['return_type'], layouts, interfaces):
                raise VMError('Invalid interface method.')
    return layouts


def _find_layout(kind, layouts):
    name = _object_name(kind)
    if name is None:
        return None
    for layout in layouts:
        if layout['name'] == name:
            return layout
    raise VMError('Unknown layout.')


def _validate(artifact):
    if not isinstance(artifact, dict): raise VMError('Artifact must be an object.')
    for field, value in [('producer','shipmbcompiler'), ('target','shipmblang-bytecode'), ('profile','general')]:
        if artifact.get(field) != value: raise VMError(f'Invalid artifact {field}.')
    if artifact.get('version') not in ('0.3', '0.4', '0.5', '0.6'): raise VMError('Invalid artifact version.')
    if artifact.get('native_machine_code') is not False: raise VMError('Native code is not accepted.')
    if not isinstance(artifact.get('debug'),dict) or artifact['debug'].get('producer')!='shipmbcompiler': raise VMError('Invalid producer metadata.')
    contract=artifact.get('runtime_contract',{})
    if not isinstance(contract,dict) or not isinstance(contract.get('required_capabilities',[]),list): raise VMError('Invalid runtime contract.')
    capabilities=contract.get('required_capabilities',[])
    effects=contract.get('effects',[])
    allowed_capabilities={'ffmpeg','vlc','vision'} if artifact['version']=='0.6' else {'ffmpeg','vlc'} if artifact['version']=='0.5' else {'ffmpeg'} if artifact['version']=='0.4' else set()
    allowed_effects={'captured_output', 'host_media'} if artifact['version'] in ('0.4','0.5','0.6') else {'captured_output'}
    if ('vision' in capabilities) != (artifact['version']=='0.6'): raise VMError('Bytecode 0.6 requires the vision capability.')
    if not isinstance(effects,list) or any(type(effect) is not str or effect not in allowed_effects for effect in effects): raise VMError('Invalid effect requirement.')
    if any(type(capability) is not str or capability not in allowed_capabilities for capability in capabilities): raise VMError('Unknown capability requirement.')
    if any(type(c) is not str for c in capabilities): raise VMError('Invalid capability requirement.')
    features = _features(contract)
    objects = 'objects' in features
    interfaces = _interfaces(artifact, features)
    layouts = _layouts(artifact, features, interfaces)
    functions=artifact.get('functions',[])
    if not isinstance(functions,list) or len(functions)>MAX_ITEMS: raise VMError('Invalid function table.')
    signatures={}; names=set(); instruction_count=len(artifact.get('bytecode',[])) if isinstance(artifact.get('bytecode'),list) else 0
    for function in functions:
        if (not isinstance(function,dict) or type(function.get('id')) is not int or function['id']<0
            or function['id'] in signatures or not isinstance(function.get('name'),str)
            or not function['name'] or function['name'] in names
            or not isinstance(function.get('return_type'),str)):
            raise VMError('Invalid function signature.')
        if _composed(function['return_type']) and 'object_composition' not in features:
            raise VMError('Phase 1 does not support objects as parameters or results.')
        if not _type_known(function['return_type'], layouts, interfaces):
            raise VMError('Invalid function signature.')
        slots=_local_slots(function.get('locals'), layouts, features, interfaces)
        parameters=function.get('parameter_slots')
        if (not isinstance(parameters,list) or any(type(slot) is not int or slot not in slots for slot in parameters)
            or len(set(parameters))!=len(parameters) or any(slots[slot]['mutable'] for slot in parameters)):
            raise VMError('Invalid function parameters.')
        argument_types = [slots[slot]['type'] for slot in parameters]
        if any(_composed(kind) and 'object_composition' not in features for kind in argument_types):
            raise VMError('Phase 1 does not support objects as parameters or results.')
        if not all(_type_known(kind, layouts, interfaces) for kind in argument_types):
            raise VMError('Invalid function signature.')
        signatures[function['id']]={**function, 'slots':slots, 'argument_types':argument_types}
        names.add(function['name'])
        if isinstance(function.get('bytecode'),list): instruction_count+=len(function['bytecode'])
    for layout in layouts:
        for method in layout.get('methods', []):
            function = signatures.get(method['function'])
            if not function or function['argument_types'] != method['parameter_types'] or function['return_type'] != method['return_type']:
                raise VMError('Invalid layout.')
    if ('object_composition' in features) != _composition_used(artifact, layouts, signatures):
        raise VMError('Feature object_composition requires a composed object type.')
    if instruction_count>MAX_ITEMS: raise VMError('Total instruction limit exceeded.')
    observed = {'references': False, 'equality': False}
    code,slots=_validate_unit(artifact.get('bytecode'),_local_slots(artifact.get('locals'), layouts, features, interfaces),
                             capabilities,effects,signatures,layouts,objects,features,interfaces,observed=observed)
    for function in signatures.values():
        try:
            _validate_unit(function.get('bytecode'),function['slots'],capabilities,effects,signatures,
                           layouts,objects,features,interfaces,function['parameter_slots'],function['return_type'],observed)
        except VMError as exc:
            exc.code=function.get('bytecode')
            raise
    if ('references' in features) != observed['references']:
        raise VMError('References feature and reference operations must agree.')
    if ('equality' in features) != observed['equality']:
        raise VMError('Equality feature and object comparisons must agree.')
    return code,slots,signatures,layouts


def _composition_used(artifact, layouts, signatures):
    def interesting(kind):
        # A bare object local is phase 1. Composition is a field, parameter, result, or list element.
        return _composed(kind)
    if any(interesting(field['type']) for layout in layouts for field in layout['fields']):
        return True
    for function in signatures.values():
        if interesting(function['return_type']) or any(interesting(kind) for kind in function['argument_types']):
            return True
    for unit in (artifact, *signatures.values()):
        code = unit.get('bytecode')
        if not isinstance(code, list):
            continue
        for item in code:
            args = item.get('operands') if isinstance(item, dict) else None
            if not isinstance(args, dict):
                continue
            if item.get('opcode') == 'make_list' and interesting(args.get('element_type', '')):
                return True
    return False


def _local_slots(descriptions, layouts=(), features=(), interfaces=()):
    if isinstance(features, bool):
        features = ['objects'] if features else []
    objects = 'objects' in features
    if not isinstance(descriptions,list) or len(descriptions)>MAX_ITEMS: raise VMError('Invalid local descriptors.')
    slots={}
    for item in descriptions:
        if (not isinstance(item,dict) or type(item.get('id')) is not int or item['id']<0
            or not isinstance(item.get('name'),str) or not isinstance(item.get('type'),str)
            or type(item.get('mutable')) is not bool or item['id'] in slots): raise VMError('Invalid local descriptor.')
        kind = item['type']
        if kind not in TYPES:
            if _object_name(kind) is not None:
                if not objects:
                    raise VMError('Object type requires the objects feature.')
                _find_layout(kind, layouts)
            elif _interface_name(kind) is not None:
                if 'interfaces' not in features or not any(item_name['name'] == _interface_name(kind) for item_name in interfaces):
                    raise VMError('Invalid local descriptor.')
            elif _ref_target(kind) is not None:
                if 'references' not in features:
                    raise VMError('Reference type requires the references feature.')
                _find_layout(_ref_target(kind), layouts)
            elif _composed(kind) and 'object_composition' in features and _type_known(kind, layouts, interfaces):
                pass
            else:
                raise VMError('Invalid local descriptor.')
        slots[item['id']]=item
    return slots


def _validate_unit(code,slots,capabilities,effects,signatures,layouts=(),objects=False,features=(),interfaces=(),parameters=(),return_type=None,observed=None):
    if observed is None:
        observed = {'references': False, 'equality': False}
    if not isinstance(code,list) or not 0<len(code)<=MAX_ITEMS: raise VMError('Invalid instruction count.')
    if any(_ref_target(slot['type']) for slot in slots.values()):
        observed['references'] = True
    for pc, item in enumerate(code):
        if not isinstance(item,dict) or type(item.get('pc')) is not int or item['pc']!=pc: raise VMError('Invalid instruction address.',pc)
        op=item.get('opcode'); args=item.get('operands'); span=item.get('source_span',{})
        if not isinstance(op,str) or op not in FIELDS or not isinstance(args,dict) or set(args)!=FIELDS[op]: raise VMError('Invalid instruction schema.',pc)
        if (not isinstance(span,dict) or type(span.get('start',0)) is not int or type(span.get('end',0)) is not int
            or not 0<=span.get('start',0)<=span.get('end',0)): raise VMError('Invalid source span.',pc)
        if op=='const' and (not isinstance(args['type'],str) or args['type'] not in SCALARS or not _value(args['value'],args['type'])): raise VMError('Invalid constant.',pc)
        if op in ('load','store','clear') and (type(args['slot']) is not int or args['slot'] not in slots): raise VMError('Invalid local slot.',pc)
        if op in ('jump','jump_if_false') and (type(args['target']) is not int or not 0<=args['target']<len(code)): raise VMError('Invalid jump target.',pc)
        if op=='binary' and (not isinstance(args['operator'],str) or args['operator'] not in BINARY): raise VMError('Invalid binary operator.',pc)
        if op=='unary' and args['operator'] not in ('not','negate'): raise VMError('Invalid unary operator.',pc)
        if op=='make_list' and (type(args['count']) is not int or not 0<=args['count']<=MAX_ITEMS or not isinstance(args['element_type'],str)
                or not (args['element_type'] in SCALARS or ('object_composition' in features and _composed(args['element_type']) and _type_known(args['element_type'], layouts, interfaces)))):
            raise VMError('Invalid list constructor.',pc)
        if op in ('new_object', 'get_field', 'set_field', 'is_instance'):
            if not objects: raise VMError('Object opcode requires the objects feature.', pc)
            if type(args.get('layout')) is not int or not 0 <= args['layout'] < len(layouts): raise VMError('Unknown layout.', pc)
            layout = layouts[args['layout']]
            flat = _flat_fields(layout, layouts)
            if op in ('get_field', 'set_field'):
                if type(args.get('offset')) is not int or not 0 <= args['offset'] < len(flat): raise VMError('Field offset out of range.', pc)
                if args.get('type') != flat[args['offset']]['type']: raise VMError('Field type mismatch.', pc)
        if op=='call_virtual':
            if 'methods' not in features: raise VMError('Method opcode requires the methods feature.', pc)
            if type(args.get('slot')) is not int or args['slot'] < 0 or not isinstance(args.get('argument_types'), list) or not args['argument_types'] or type(args.get('return_type')) is not str:
                raise VMError('Invalid virtual call.', pc)
            if not _virtual_signature(args, layouts, interfaces, features):
                raise VMError('Invalid virtual call.', pc)
        if op in ('alloc', 'deref_get', 'deref_set', 'release', 'same_object'):
            if 'references' not in features:
                raise VMError('Reference opcode requires the references feature.', pc)
            observed['references'] = True
            if op in ('alloc', 'deref_get', 'deref_set'):
                if not isinstance(args.get('type'), str) or _object_name(args['type']) is None:
                    raise VMError('Invalid reference type.', pc)
                _find_layout(args['type'], layouts)
            if op == 'release' and (type(args.get('slot')) is not int or args['slot'] not in slots or _ref_target(slots[args['slot']]['type']) is None):
                raise VMError('Release requires a reference.', pc)
        if op=='return' and return_type is None: raise VMError('Return outside a function.',pc)
        if op=='halt' and return_type is not None: raise VMError('Functions must return, not halt.',pc)
        if op=='clear' and args['slot'] in parameters: raise VMError('Function parameters cannot be cleared.',pc)
        if op=='call':
            function=signatures.get(args['function']) if type(args['function']) is int else None
            if not function or args['argument_types']!=function['argument_types'] or args['return_type']!=function['return_type']:
                raise VMError('Invalid function call signature.',pc)
        if op=='text_segment':
            signature=TEXT_SEGMENT.get(args['operation']) if isinstance(args['operation'], str) else None
            if (signature is None or not isinstance(args['argument_types'], list)
                    or args['argument_types']!=signature[0] or args['return_type']!=signature[1]):
                raise VMError('Invalid text segment signature.',pc)
        if op=='show' and 'captured_output' not in effects: raise VMError('Captured output effect is undeclared.',pc)
        if op in ('vlc_execute','vlc_query'):
            from .vlc import OPERATIONS
            signature=OPERATIONS.get(args['operation']) if isinstance(args['operation'],str) else None
            if ('vlc' not in capabilities or 'host_media' not in effects or not signature
                    or args['argument_types']!=signature[0] or (op=='vlc_query')!=bool(signature[1])
                    or op=='vlc_query' and args['return_type']!=signature[1]):
                raise VMError('Invalid VLC signature or capability.',pc)
        if op=='vision_query':
            from .vision import OPERATIONS as VISION, MODEL_SHA256
            signature=VISION.get(args['operation']) if isinstance(args['operation'],str) else None
            if ('vision' not in capabilities or 'host_media' not in effects or not signature
                    or args['argument_types']!=signature[0] or args['return_type']!=signature[1]
                    or args['model_sha256']!=MODEL_SHA256):
                raise VMError('Invalid vision signature or capability.',pc)
        if op=='ffmpeg_execute':
            if 'ffmpeg' not in capabilities or 'host_media' not in effects:
                raise VMError('FFmpeg capability and host media effect must be declared.', pc)
            from .ffmpeg import validate_job
            if not isinstance(args['argument_types'], list):
                raise VMError('FFmpeg operand types must be a list.', pc)
            try:
                validate_job(args['job'], args['argument_types'])
            except (ValueError, TypeError, UnicodeError) as error:
                raise VMError(str(error), pc) from error
        if op=='ffmpeg_probe':
            if 'ffmpeg' not in capabilities or 'host_media' not in effects:
                raise VMError('FFmpeg capability and host media effect must be declared.', pc)
            if args['argument_types'] != ['text']:
                raise VMError('Probe requires one text operand.', pc)
    states={0:((),frozenset(parameters),frozenset(parameters))}; pending=deque([0]); visits=0
    while pending:
        visits+=1
        if visits>1000000: raise VMError('Validation complexity limit exceeded.')
        pc=pending.popleft(); types, definite, possible=states[pc]
        stack=list(types); definite=set(definite); possible=set(possible)
        op=code[pc]['opcode']; args=code[pc]['operands']
        def pop(expected=None):
            if not stack: raise VMError('Stack underflow.',pc)
            kind=stack.pop()
            if expected is not None and kind!=expected and not _subtype(kind, expected, layouts, interfaces, features):
                raise VMError('Operand type mismatch.',pc)
            return kind
        if op=='const': stack.append(args['type'])
        elif op=='load':
            if args['slot'] not in definite: raise VMError('Read of an uninitialized local.',pc)
            stack.append(slots[args['slot']]['type'])
        elif op=='store':
            slot=args['slot']; pop(slots[slot]['type'])
            if not slots[slot]['mutable'] and slot in possible: raise VMError('Immutable local may already be initialized.',pc)
            definite.add(slot); possible.add(slot)
        elif op=='clear': definite.discard(args['slot']); possible.discard(args['slot'])
        elif op=='binary':
            right=pop(); left=pop(); operator=args['operator']
            if _ref_target(left) or _ref_target(right) or _contains_object(left) or _contains_object(right):
                if not (_contains_object(left) and left == right and operator in ('equal', 'not_equal') and 'equality' in features):
                    raise VMError('Phase 1 does not support comparing objects.', pc)
                observed['equality'] = True
                result='boolean'
            else:
                if left!=right: raise VMError('Binary operands have different types.',pc)
                if operator in ('and','or'):
                    if left!='boolean': raise VMError('Boolean operands required.',pc)
                    result='boolean'
                elif operator in ('equal','not_equal'): result='boolean'
                elif operator in ('greater','less','greater_equal','less_equal'):
                    if left not in ('integer','text'): raise VMError('Ordered scalar operands required.',pc)
                    result='boolean'
                else:
                    if left!='integer' and not (operator=='add' and left=='text'): raise VMError('Arithmetic operand type mismatch.',pc)
                    result=left
            stack.append(result)
        elif op=='unary': pop('boolean' if args['operator']=='not' else 'integer'); stack.append('boolean' if args['operator']=='not' else 'integer')
        elif op=='make_list':
            for _ in range(args['count']): pop(args['element_type'])
            stack.append('list['+args['element_type']+']')
        elif op=='length':
            kind=pop()
            if kind!='text' and not kind.startswith('list['): raise VMError('Length requires text or a list.',pc)
            stack.append('integer')
        elif op=='index':
            pop('integer'); kind=pop()
            if not kind.startswith('list['): raise VMError('Index requires a list.',pc)
            stack.append(kind[5:-1])
        elif op=='append':
            item=pop(); kind=pop()
            if not kind.startswith('list[') or not (item==kind[5:-1] or _subtype(item, kind[5:-1], layouts, interfaces, features)):
                raise VMError('Append requires a list and a matching element.',pc)
            stack.append(kind)
        elif op=='jump_if_false': pop('boolean')
        elif op=='show': pop()
        elif op in ('vlc_execute','vlc_query','vision_query'):
            for kind in reversed(args['argument_types']): pop(kind)
            if op in ('vlc_query','vision_query'): stack.append(args['return_type'])
        elif op=='ffmpeg_execute':
            for kind in reversed(args['argument_types']): pop(kind)
        elif op=='ffmpeg_probe':
            for kind in reversed(args['argument_types']): pop(kind)
            stack.append('text')
        elif op=='call' or op=='call_virtual':
            for kind in reversed(args['argument_types']): pop(kind)
            stack.append(args['return_type'])
        elif op=='new_object':
            layout = layouts[args['layout']]
            for field in reversed(_flat_fields(layout, layouts)): pop(field['type'])
            stack.append('object[' + layout['name'] + ']')
        elif op=='get_field':
            pop('object[' + layouts[args['layout']]['name'] + ']')
            stack.append(args['type'])
        elif op=='set_field':
            pop(args['type'])
            kind = pop('object[' + layouts[args['layout']]['name'] + ']')
            stack.append(kind)
        elif op=='is_instance':
            kind = pop()
            if _object_name(kind) is None:
                raise VMError('Instance test requires an object.', pc)
            stack.append('boolean')
        elif op=='alloc':
            pop(args['type'])
            stack.append('ref[' + args['type'] + ']')
        elif op=='deref_get':
            pop('ref[' + args['type'] + ']')
            stack.append(args['type'])
        elif op=='deref_set':
            pop('ref[' + args['type'] + ']')
            pop(args['type'])
        elif op=='release':
            pass
        elif op=='same_object':
            right = pop()
            left = pop()
            if _ref_target(left) is None or left != right:
                raise VMError('Same object requires two references.', pc)
            stack.append('boolean')
        elif op=='text_segment':
            for kind in reversed(args['argument_types']): pop(kind)
            stack.append(args['return_type'])
        elif op=='return':
            pop(return_type)
            if stack: raise VMError('Nonempty stack after return value.',pc)
        elif op=='halt' and stack: raise VMError('Nonempty stack at halt.',pc)
        if len(stack)>MAX_ITEMS: raise VMError('Stack limit exceeded.',pc)
        successors=[] if op in ('halt','return') else [args['target']] if op=='jump' else [pc+1,args['target']] if op=='jump_if_false' else [pc+1]
        for successor in successors:
            if successor>=len(code): raise VMError('Control flow falls past bytecode.',pc)
            new=(tuple(stack),frozenset(definite),frozenset(possible))
            if successor in states:
                old=states[successor]
                if old[0]!=new[0]: raise VMError('Inconsistent stack types at branch merge.',successor)
                new=(new[0], old[1]&new[1], old[2]|new[2])
            if states.get(successor)!=new: states[successor]=new; pending.append(successor)
    if len(states)!=len(code): raise VMError('Unreachable bytecode is not permitted.')
    return code,slots


def _hex_frame(item):
    if type(item) is not str or len(item) % 2 or any(char not in '0123456789abcdef' for char in item):
        raise ValueError('frame hex is invalid')
    return bytes.fromhex(item)


def _text_segment(operation, arguments):
    from .textseg import chunk_text, frame_message, graphemes, sentences, unframe_message, words
    if operation == 'graphemes':
        return graphemes(arguments[0])
    if operation == 'words':
        return words(arguments[0], arguments[1])
    if operation == 'sentences':
        return sentences(arguments[0], arguments[1])
    if operation in {'chunks', 'chunks_words'}:
        max_words = None if operation == 'chunks' else arguments[2]
        language = arguments[-1]
        return chunk_text(arguments[0], max_bytes=arguments[1], max_words=max_words, lang=language)
    if operation == 'frames':
        message_id = arguments[1]
        if type(message_id) is not int or not 0 <= message_id <= 0xFFFFFFFF:
            raise ValueError('msg_id must fit in uint32')
        return [frame.hex() for frame in frame_message(message_id, arguments[0])]
    if operation == 'unframe':
        try:
            payload = unframe_message([_hex_frame(item) for item in arguments[0]])
            return payload.decode('utf-8')
        except UnicodeError as error:
            raise ValueError('frame payload is not valid UTF-8') from error
    raise ValueError('Unknown text segment operation.')


def _display(value, layouts=None):
    if isinstance(value, ObjectValue):
        layout = layouts[value.layout]
        flat = _flat_fields(layout, layouts)
        body = ', '.join(f"{field['name']}: {_display(item, layouts)}" for field, item in zip(flat, value.fields))
        return f"{layout['name']}{{{body}}}"
    if type(value) is bool: return 'true' if value else 'false'
    if type(value) is list: return '['+', '.join(_display(item, layouts) for item in value)+']'
    return str(value)


def _export(value):
    if isinstance(value, RefValue):
        return {'ref': value.cell}
    if isinstance(value, ObjectValue):
        return {'layout': value.layout, 'fields': [_export(item) for item in value.fields]}
    if type(value) is list:
        return [_export(item) for item in value]
    return value


def _structurally_equal(left, right):
    if isinstance(left, ObjectValue) or isinstance(right, ObjectValue):
        if not isinstance(left, ObjectValue) or not isinstance(right, ObjectValue):
            return False
        if left.layout != right.layout or len(left.fields) != len(right.fields):
            return False
        return all(_structurally_equal(a, b) for a, b in zip(left.fields, right.fields))
    if type(left) is list or type(right) is list:
        if type(left) is not list or type(right) is not list or len(left) != len(right):
            return False
        return all(_structurally_equal(a, b) for a, b in zip(left, right))
    return left == right


class _Cell:
    __slots__ = ('obj', 'count', 'alive')

    def __init__(self, obj):
        self.obj = obj
        self.count = 1
        self.alive = True


def _cell(ref, heap, pc):
    if not isinstance(ref, RefValue) or type(ref.cell) is not int or not 0 <= ref.cell < len(heap):
        raise VMError('Invalid reference.', pc)
    return heap[ref.cell]


def _drop_owner(ref, heap, pc):
    cell = _cell(ref, heap, pc)
    if cell.count <= 0:
        raise VMError('Invalid reference.', pc)
    cell.count -= 1
    if cell.count == 0:
        cell.alive = False
        cell.obj = None


def _live_ref(ref, heap, pc):
    cell = _cell(ref, heap, pc)
    if ref.stale or not cell.alive:
        raise VMError('Use after release.', pc)
    return cell


def run_general_artifact(artifact, *, max_steps=100000, host=None, ffmpeg_executor=None, vlc_executor=None, vision_executor=None):
    state={'output':[], 'stdout':'', 'events':[], 'variables':{}}
    pc=0
    try:
        if type(max_steps) is not int or not 1<=max_steps<=1000000: raise VMError('Invalid execution fuel limit.')
        code,slots,functions,layouts=_validate(artifact)
        features=_features(artifact.get('runtime_contract',{}))
        if 'vlc' in artifact.get('runtime_contract',{}).get('required_capabilities',[]):
            if vlc_executor is None or not callable(getattr(vlc_executor,'invoke',None)):
                raise VMError('VLC execution requires an explicit VLC executor.')
        if 'ffmpeg' in artifact.get('runtime_contract', {}).get('required_capabilities', []):
            if ffmpeg_executor is None or not callable(getattr(ffmpeg_executor, 'execute', None)):
                raise VMError('Media execution requires an explicit FFmpeg executor.')
        if 'vision' in artifact.get('runtime_contract', {}).get('required_capabilities', []):
            if vision_executor is None:
                from .vision import VisionExecutor
                vision_executor = VisionExecutor()
            elif not callable(getattr(vision_executor, 'invoke', None)):
                raise VMError('Vision execution requires an explicit vision executor.')
        stack=[]; values={}; frames=[]; steps=0; output_bytes=0; allocated_items=0; heap=[]
        while True:
            if steps>=max_steps: raise VMError('Execution fuel exhausted.',pc)
            steps+=1; item=code[pc]; op=item['opcode']; args=item['operands']; next_pc=pc+1
            if op=='halt': break
            if op=='const': stack.append(args['value'])
            elif op=='load':
                loaded = values[args['slot']]
                if isinstance(loaded, RefValue):
                    if loaded.stale or not _cell(loaded, heap, pc).alive:
                        stack.append(RefValue(loaded.cell, False, True))
                    else:
                        _cell(loaded, heap, pc).count += 1
                        stack.append(RefValue(loaded.cell, True, False))
                else:
                    stack.append(loaded)
            elif op=='store':
                stored = stack.pop()
                slot = args['slot']
                if isinstance(stored, RefValue):
                    previous = values.get(slot)
                    if isinstance(previous, RefValue) and not previous.stale:
                        _drop_owner(previous, heap, pc)
                    _live_ref(stored, heap, pc)
                    if not stored.owning:
                        _cell(stored, heap, pc).count += 1
                    values[slot] = RefValue(stored.cell, True, False)
                else:
                    values[slot] = stored
            elif op=='clear':
                slot = args['slot']
                previous = values.get(slot)
                if isinstance(previous, RefValue) and not previous.stale:
                    _drop_owner(previous, heap, pc)
                values.pop(slot, None)
            elif op=='binary':
                b=stack.pop(); a=stack.pop(); operator=args['operator']
                if operator in ('equal', 'not_equal'):
                    same = _structurally_equal(a, b)
                    stack.append(same if operator == 'equal' else not same)
                    pc = next_pc
                    continue
                if operator in ('divide','modulo'):
                    if b==0: raise VMError('Division by zero.',pc)
                    quotient=(abs(a)//abs(b))*(-1 if (a<0)!=(b<0) else 1)
                    result=quotient if operator=='divide' else a-quotient*b
                else:
                    result={'add':lambda:a+b, 'subtract':lambda:a-b, 'multiply':lambda:a*b,
                            'equal':lambda:a==b, 'not_equal':lambda:a!=b, 'greater':lambda:a>b,
                            'less':lambda:a<b, 'greater_equal':lambda:a>=b, 'less_equal':lambda:a<=b,
                            'and':lambda:a and b, 'or':lambda:a or b}[operator]()
                if type(result) is int and result.bit_length()>MAX_BITS: raise VMError('Integer size limit exceeded.',pc)
                if type(result) is str and len(result.encode('utf-8'))>MAX_TEXT: raise VMError('Text size limit exceeded.',pc)
                stack.append(result)
            elif op=='unary':
                value=stack.pop(); stack.append(not value if args['operator']=='not' else -value)
            elif op=='make_list':
                count=args['count']; allocated_items+=count
                if allocated_items>1000000: raise VMError('Collection allocation limit exceeded.',pc)
                result=stack[-count:] if count else []
                if count: del stack[-count:]
                stack.append(result)
            elif op=='length': stack.append(len(stack.pop()))
            elif op=='index':
                index=stack.pop(); sequence=stack.pop()
                if not 0<=index<len(sequence): raise VMError('List index out of bounds.',pc)
                stack.append(sequence[index])
            elif op=='new_object':
                layout=layouts[args['layout']]; flat=_flat_fields(layout, layouts); count=len(flat); allocated_items+=count
                if allocated_items>1000000: raise VMError('Collection allocation limit exceeded.',pc)
                fields=tuple(stack[-count:]) if count else ()
                if count: del stack[-count:]
                for field, item in zip(flat, fields):
                    if not _value(item, field['type'], layouts): raise VMError('Invalid object field.', pc)
                stack.append(ObjectValue(layout['id'], fields))
            elif op=='get_field':
                obj=stack.pop()
                if not _field_layout_ok(obj, args['layout'], layouts, features): raise VMError('Field access requires the declared object.', pc)
                stack.append(obj.fields[args['offset']])
            elif op=='set_field':
                value=stack.pop(); obj=stack.pop()
                if not _field_layout_ok(obj, args['layout'], layouts, features): raise VMError('Field access requires the declared object.', pc)
                flat=_flat_fields(layouts[obj.layout], layouts)
                if not _value(value, flat[args['offset']]['type'], layouts): raise VMError('Invalid object field.', pc)
                updated=list(obj.fields); updated[args['offset']]=value
                allocated_items+=len(updated)
                if allocated_items>1000000: raise VMError('Collection allocation limit exceeded.',pc)
                stack.append(ObjectValue(obj.layout, updated))
            elif op=='is_instance':
                obj=stack.pop()
                stack.append(isinstance(obj, ObjectValue) and _extends(obj.layout, args['layout'], layouts))
            elif op=='alloc':
                obj=stack.pop()
                if not isinstance(obj, ObjectValue):
                    raise VMError('A reference requires an object.', pc)
                dynamic='object[' + layouts[obj.layout]['name'] + ']'
                if not _subtype(dynamic, args['type'], layouts, (), features):
                    raise VMError('Invalid reference type.', pc)
                allocated_items+=1
                if allocated_items>1000000: raise VMError('Collection allocation limit exceeded.', pc)
                heap.append(_Cell(obj))
                stack.append(RefValue(len(heap)-1, True, False))
            elif op=='deref_get':
                ref=stack.pop()
                cell=_live_ref(ref, heap, pc)
                obj=cell.obj
                if ref.owning:
                    _drop_owner(ref, heap, pc)
                stack.append(obj)
            elif op=='deref_set':
                ref=stack.pop(); obj=stack.pop()
                cell=_live_ref(ref, heap, pc)
                if not isinstance(obj, ObjectValue):
                    raise VMError('Invalid reference update.', pc)
                dynamic='object[' + layouts[obj.layout]['name'] + ']'
                if not _subtype(dynamic, args['type'], layouts, (), features):
                    raise VMError('Invalid reference update.', pc)
                cell.obj=obj
                if ref.owning:
                    _drop_owner(ref, heap, pc)
            elif op=='release':
                slot=args['slot']
                previous=values.get(slot)
                if isinstance(previous, RefValue) and not previous.stale:
                    _drop_owner(previous, heap, pc)
                    values[slot]=RefValue(previous.cell, False, True)
            elif op=='same_object':
                right=stack.pop(); left=stack.pop()
                _live_ref(left, heap, pc)
                _live_ref(right, heap, pc)
                same=left.cell==right.cell
                if left.owning:
                    _drop_owner(left, heap, pc)
                if right.owning:
                    _drop_owner(right, heap, pc)
                stack.append(same)
            elif op=='append':
                item=stack.pop(); sequence=stack.pop()
                if len(sequence)>=MAX_ITEMS: raise VMError('List exceeds the 10000-item limit.',pc)
                allocated_items+=1
                if allocated_items>1000000: raise VMError('Collection allocation limit exceeded.',pc)
                stack.append([*sequence, item])
            elif op=='jump': next_pc=args['target']
            elif op=='jump_if_false':
                if not stack.pop(): next_pc=args['target']
            elif op=='show':
                shown=stack.pop()
                if isinstance(shown, RefValue):
                    cell=_live_ref(shown, heap, pc)
                    obj=cell.obj
                    if shown.owning:
                        _drop_owner(shown, heap, pc)
                    shown=obj
                text=_display(shown, layouts); output_bytes+=len(text.encode('utf-8'))+1
                if output_bytes>MAX_TEXT: raise VMError('Output size limit exceeded.',pc)
                state['output'].append(text); state['stdout']+=text+'\n'
            elif op=='vision_query':
                from .vision import validate_arguments
                count=len(args['argument_types']); arguments=stack[-count:] if count else []
                if count: del stack[-count:]
                try:
                    validate_arguments(args['operation'], arguments)
                    if len(state['events'])>=MAX_ITEMS: raise ValueError('Media event limit exceeded.')
                    result=vision_executor.invoke(args['operation'], arguments)
                    if not _value(result, args['return_type']): raise ValueError('Invalid vision result.')
                    stack.append(result)
                    state['events'].append({'kind':'vision','operation':args['operation'],'status':'completed'})
                except (ValueError, OSError) as error:
                    raise VMError(str(error), pc) from error
            elif op in ('vlc_execute','vlc_query'):
                from .vlc import validate_arguments
                count=len(args['argument_types']);arguments=stack[-count:] if count else []
                if count: del stack[-count:]
                try:
                    validate_arguments(args['operation'],arguments)
                    if len(state['events'])>=MAX_ITEMS: raise ValueError('Media event limit exceeded.')
                    result=vlc_executor.invoke(args['operation'],arguments)
                    if op=='vlc_query':
                        if not _value(result,args['return_type']): raise ValueError('Invalid VLC query result.')
                        stack.append(result)
                    state['events'].append({'kind':'vlc','operation':args['operation'],'status':'completed'})
                except (ValueError,OSError) as error:
                    raise VMError(str(error),pc) from error
            elif op=='ffmpeg_execute':
                from .ffmpeg import resolve_job, FFmpegExecutionError
                count = len(args['argument_types'])
                arguments = stack[-count:] if count else []
                if count: del stack[-count:]
                try:
                    if len(state['events']) >= MAX_ITEMS:
                        raise ValueError('Media event limit exceeded.')
                    job = resolve_job(args['job'], arguments, args['argument_types'])
                    event = ffmpeg_executor.execute(job)
                    state['events'].append(event)
                except FFmpegExecutionError as error:
                    state['events'].append(error.result)
                    raise VMError(str(error), pc) from error
                except (ValueError, OSError) as error:
                    raise VMError(str(error), pc) from error
            elif op=='ffmpeg_probe':
                path=stack.pop()
                if not callable(getattr(ffmpeg_executor, 'probe', None)):
                    raise VMError('Media execution requires an explicit FFmpeg executor.', pc)
                try:
                    probed=ffmpeg_executor.probe(path)
                except (ValueError, OSError) as error:
                    raise VMError(str(error), pc) from error
                info=probed.get('format') if isinstance(probed, dict) else None
                duration=info.get('duration') if isinstance(info, dict) else None
                if type(duration) is not str or not _value(duration, 'text'):
                    raise VMError('Probe duration is missing or not text.', pc)
                stack.append(duration)
            elif op=='text_segment':
                count=len(args['argument_types'])
                arguments=stack[-count:] if count else []
                if count: del stack[-count:]
                try:
                    result=_text_segment(args['operation'], arguments)
                except (ValueError, UnicodeError) as error:
                    raise VMError(str(error), pc) from error
                if type(result) is list:
                    allocated_items += len(result)
                    if allocated_items>1000000: raise VMError('Collection allocation limit exceeded.', pc)
                if not _value(result, args['return_type']):
                    raise VMError('Invalid text segment result.', pc)
                stack.append(result)
            elif op=='call_virtual':
                if len(frames)>=63: raise VMError('Call depth limit exceeded.',pc)
                count=len(args['argument_types']); arguments=stack[-count:] if count else []
                if count: del stack[-count:]
                receiver=arguments[0]
                method=_resolve_method(layouts[receiver.layout], args['slot'], layouts) if isinstance(receiver, ObjectValue) else None
                if method is None: raise VMError('Virtual call requires an object.', pc)
                function=functions[method['function']]
                frames.append((code,slots,stack,values,next_pc))
                code=function['bytecode']; slots=function['slots']; stack=[]
                values=dict(zip(function['parameter_slots'],arguments)); next_pc=0
            elif op=='call':
                if len(frames)>=63: raise VMError('Call depth limit exceeded.',pc)
                function=functions[args['function']]
                count=len(args['argument_types']); arguments=stack[-count:] if count else []
                if count: del stack[-count:]
                frames.append((code,slots,stack,values,next_pc))
                code=function['bytecode']; slots=function['slots']; stack=[]
                values=dict(zip(function['parameter_slots'],arguments)); next_pc=0
            elif op=='return':
                result=stack.pop()
                code,slots,stack,values,next_pc=frames.pop()
                stack.append(result)
            pc=next_pc
        state['variables']={item['name']:_export(values[slot]) for slot,item in slots.items() if slot in values and not item['name'].startswith('$')}
        return state,[]
    except (VMError, UnicodeError) as exc:
        fault_pc=getattr(exc,'pc',pc)
        span={}
        fault_code=getattr(exc,'code',locals().get('code',artifact.get('bytecode') if isinstance(artifact,dict) else None))
        if isinstance(fault_code,list) and 0<=fault_pc<len(fault_code):
            item=fault_code[fault_pc]
            if isinstance(item,dict) and isinstance(item.get('source_span'),dict): span=item['source_span']
        start,end=span.get('start',0),span.get('end',0)
        if type(start) is not int or type(end) is not int or not 0<=start<=end: start=end=0
        return state,[Diagnostic('error','SMB6200',str(exc),Span(start,end))]
