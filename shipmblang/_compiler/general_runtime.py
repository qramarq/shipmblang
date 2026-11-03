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
          'get_field': {'layout', 'offset', 'type'}}

class ObjectValue:
    """Immutable phase-1 object: layout id plus field values in offset order."""
    __slots__ = ('layout', 'fields')

    def __init__(self, layout, fields):
        self.layout = layout
        self.fields = tuple(fields)


class VMError(ValueError):
    def __init__(self, message, pc=0):
        super().__init__(message)
        self.pc = pc


def _object_name(kind):
    if isinstance(kind, str) and kind.startswith('object[') and kind.endswith(']') and '[' not in kind[7:-1]:
        return kind[7:-1]
    return None


def _value(value, kind, layouts=None):
    if kind == 'integer': return type(value) is int and value.bit_length() <= MAX_BITS
    if kind == 'boolean': return type(value) is bool
    if kind == 'text': return type(value) is str and len(value.encode('utf-8')) <= MAX_TEXT
    name = _object_name(kind)
    if name is not None:
        if not isinstance(value, ObjectValue) or layouts is None:
            return False
        layout = next((item for item in layouts if item['name'] == name and item['id'] == value.layout), None)
        return (layout is not None and len(value.fields) == len(layout['fields'])
                and all(_value(item, field['type'], layouts) for item, field in zip(value.fields, layout['fields'])))
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
        if type(item) is not str or item != 'objects':
            raise VMError('Unknown feature requirement.')
        if item in seen:
            raise VMError('Duplicate feature requirement.')
        seen.add(item)
    return features


def _layouts(artifact, objects):
    layouts = artifact['layouts'] if 'layouts' in artifact else []
    if not isinstance(layouts, list) or len(layouts) > MAX_ITEMS:
        raise VMError('Invalid layout table.')
    if objects != bool(layouts):
        raise VMError('Objects feature and layouts must agree.')
    names = set()
    for index, layout in enumerate(layouts):
        if not isinstance(layout, dict) or set(layout) != {'id', 'name', 'fields'}:
            raise VMError('Invalid layout.')
        if type(layout.get('id')) is not int or layout['id'] != index or type(layout.get('name')) is not str or not layout['name'] or layout['name'] in names:
            raise VMError('Invalid layout.')
        fields = layout.get('fields')
        if not isinstance(fields, list) or not 1 <= len(fields) <= 256:
            raise VMError('Invalid layout fields.')
        seen = set()
        for offset, field in enumerate(fields):
            if (not isinstance(field, dict) or set(field) != {'name', 'type', 'offset'}
                    or type(field.get('name')) is not str or not field['name'] or field['name'] in seen
                    or type(field.get('offset')) is not int or field['offset'] != offset
                    or type(field.get('type')) is not str or field['type'] not in TYPES):
                raise VMError('Invalid layout field.')
            seen.add(field['name'])
        names.add(layout['name'])
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
    layouts = _layouts(artifact, objects)
    functions=artifact.get('functions',[])
    if not isinstance(functions,list) or len(functions)>MAX_ITEMS: raise VMError('Invalid function table.')
    signatures={}; names=set(); instruction_count=len(artifact.get('bytecode',[])) if isinstance(artifact.get('bytecode'),list) else 0
    for function in functions:
        if (not isinstance(function,dict) or type(function.get('id')) is not int or function['id']<0
            or function['id'] in signatures or not isinstance(function.get('name'),str)
            or not function['name'] or function['name'] in names
            or not isinstance(function.get('return_type'),str) or (_object_name(function['return_type']) is None and function['return_type'] not in TYPES)
            or _object_name(function['return_type']) is not None):
            if isinstance(function, dict) and _object_name(function.get('return_type')) is not None:
                raise VMError('Phase 1 does not support objects as parameters or results.')
            raise VMError('Invalid function signature.')
        slots=_local_slots(function.get('locals'), layouts, objects)
        parameters=function.get('parameter_slots')
        if (not isinstance(parameters,list) or any(type(slot) is not int or slot not in slots for slot in parameters)
            or len(set(parameters))!=len(parameters) or any(slots[slot]['mutable'] for slot in parameters)):
            raise VMError('Invalid function parameters.')
        argument_types = [slots[slot]['type'] for slot in parameters]
        if any(_object_name(kind) is not None for kind in argument_types):
            raise VMError('Phase 1 does not support objects as parameters or results.')
        signatures[function['id']]={**function, 'slots':slots, 'argument_types':argument_types}
        names.add(function['name'])
        if isinstance(function.get('bytecode'),list): instruction_count+=len(function['bytecode'])
    if instruction_count>MAX_ITEMS: raise VMError('Total instruction limit exceeded.')
    code,slots=_validate_unit(artifact.get('bytecode'),_local_slots(artifact.get('locals'), layouts, objects),
                             capabilities,effects,signatures,layouts,objects)
    for function in signatures.values():
        try:
            _validate_unit(function.get('bytecode'),function['slots'],capabilities,effects,signatures,
                           layouts,objects,function['parameter_slots'],function['return_type'])
        except VMError as exc:
            exc.code=function.get('bytecode')
            raise
    return code,slots,signatures,layouts


def _local_slots(descriptions, layouts=(), objects=False):
    if not isinstance(descriptions,list) or len(descriptions)>MAX_ITEMS: raise VMError('Invalid local descriptors.')
    slots={}
    for item in descriptions:
        if (not isinstance(item,dict) or type(item.get('id')) is not int or item['id']<0
            or not isinstance(item.get('name'),str) or not isinstance(item.get('type'),str)
            or type(item.get('mutable')) is not bool or item['id'] in slots): raise VMError('Invalid local descriptor.')
        if item['type'] not in TYPES:
            if _object_name(item['type']) is None:
                raise VMError('Invalid local descriptor.')
            if not objects:
                raise VMError('Object type requires the objects feature.')
            _find_layout(item['type'], layouts)
        slots[item['id']]=item
    return slots


def _validate_unit(code,slots,capabilities,effects,signatures,layouts=(),objects=False,parameters=(),return_type=None):
    if not isinstance(code,list) or not 0<len(code)<=MAX_ITEMS: raise VMError('Invalid instruction count.')
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
        if op=='make_list' and (type(args['count']) is not int or not 0<=args['count']<=MAX_ITEMS or not isinstance(args['element_type'],str) or args['element_type'] not in SCALARS): raise VMError('Invalid list constructor.',pc)
        if op in ('new_object', 'get_field'):
            if not objects: raise VMError('Object opcode requires the objects feature.', pc)
            if type(args.get('layout')) is not int or not 0 <= args['layout'] < len(layouts): raise VMError('Unknown layout.', pc)
            layout = layouts[args['layout']]
            if op == 'get_field':
                if type(args.get('offset')) is not int or not 0 <= args['offset'] < len(layout['fields']): raise VMError('Field offset out of range.', pc)
                if args.get('type') != layout['fields'][args['offset']]['type']: raise VMError('Field type mismatch.', pc)
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
            if expected is not None and kind!=expected: raise VMError('Operand type mismatch.',pc)
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
            if (isinstance(left, str) and left.startswith('object[')) or (isinstance(right, str) and right.startswith('object[')):
                raise VMError('Phase 1 does not support comparing objects.', pc)
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
            if not kind.startswith('list[') or item!=kind[5:-1]: raise VMError('Append requires a list and a matching element.',pc)
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
        elif op=='call':
            for kind in reversed(args['argument_types']): pop(kind)
            stack.append(args['return_type'])
        elif op=='new_object':
            layout = layouts[args['layout']]
            for field in reversed(layout['fields']): pop(field['type'])
            stack.append('object[' + layout['name'] + ']')
        elif op=='get_field':
            pop('object[' + layouts[args['layout']]['name'] + ']')
            stack.append(args['type'])
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
        body = ', '.join(f"{field['name']}: {_display(item, layouts)}" for field, item in zip(layout['fields'], value.fields))
        return f"{layout['name']}{{{body}}}"
    if type(value) is bool: return 'true' if value else 'false'
    if type(value) is list: return '['+', '.join(_display(item, layouts) for item in value)+']'
    return str(value)


def _export(value):
    if isinstance(value, ObjectValue):
        return {'layout': value.layout, 'fields': [_export(item) for item in value.fields]}
    if type(value) is list:
        return [_export(item) for item in value]
    return value


def run_general_artifact(artifact, *, max_steps=100000, host=None, ffmpeg_executor=None, vlc_executor=None, vision_executor=None):
    state={'output':[], 'stdout':'', 'events':[], 'variables':{}}
    pc=0
    try:
        if type(max_steps) is not int or not 1<=max_steps<=1000000: raise VMError('Invalid execution fuel limit.')
        code,slots,functions,layouts=_validate(artifact)
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
        stack=[]; values={}; frames=[]; steps=0; output_bytes=0; allocated_items=0
        while True:
            if steps>=max_steps: raise VMError('Execution fuel exhausted.',pc)
            steps+=1; item=code[pc]; op=item['opcode']; args=item['operands']; next_pc=pc+1
            if op=='halt': break
            if op=='const': stack.append(args['value'])
            elif op=='load': stack.append(values[args['slot']])
            elif op=='store': values[args['slot']]=stack.pop()
            elif op=='clear': values.pop(args['slot'],None)
            elif op=='binary':
                b=stack.pop(); a=stack.pop(); operator=args['operator']
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
                layout=layouts[args['layout']]; count=len(layout['fields']); allocated_items+=count
                if allocated_items>1000000: raise VMError('Collection allocation limit exceeded.',pc)
                fields=tuple(stack[-count:]) if count else ()
                if count: del stack[-count:]
                for field, item in zip(layout['fields'], fields):
                    if not _value(item, field['type'], layouts): raise VMError('Invalid object field.', pc)
                stack.append(ObjectValue(layout['id'], fields))
            elif op=='get_field':
                obj=stack.pop()
                if not isinstance(obj, ObjectValue) or obj.layout!=args['layout']: raise VMError('Field access requires the declared object.', pc)
                stack.append(obj.fields[args['offset']])
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
                text=_display(stack.pop(), layouts); output_bytes+=len(text.encode('utf-8'))+1
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
