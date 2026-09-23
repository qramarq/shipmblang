"""Bounded, preflight-validated stack VM for general English bytecode."""
from collections import deque
from .models import Diagnostic, Span

MAX_ITEMS = 10000
MAX_TEXT = 1000000
MAX_BITS = 4096
SCALARS = {'integer', 'boolean', 'text'}
TYPES = SCALARS | {f'list[{kind}]' for kind in SCALARS}
BINARY = {'add', 'subtract', 'multiply', 'divide', 'modulo', 'equal', 'not_equal', 'greater', 'less', 'greater_equal', 'less_equal', 'and', 'or'}
FIELDS = {'const': {'value','type'}, 'load': {'slot'}, 'store': {'slot'}, 'clear': {'slot'},
          'binary': {'operator'}, 'unary': {'operator'}, 'make_list': {'count','element_type'},
          'length': set(), 'index': set(), 'jump': {'target'}, 'jump_if_false': {'target'},
          'show': set(), 'halt': set(), 'return': set(),
          'call': {'function','argument_types','return_type'}}

class VMError(ValueError):
    def __init__(self, message, pc=0):
        super().__init__(message)
        self.pc = pc


def _value(value, kind):
    if kind == 'integer': return type(value) is int and value.bit_length() <= MAX_BITS
    if kind == 'boolean': return type(value) is bool
    if kind == 'text': return type(value) is str and len(value.encode('utf-8')) <= MAX_TEXT
    return (isinstance(kind, str) and kind.startswith('list[') and type(value) is list
            and len(value) <= MAX_ITEMS and all(_value(item, kind[5:-1]) for item in value))


def _validate(artifact):
    if not isinstance(artifact, dict): raise VMError('Artifact must be an object.')
    for field, value in [('producer','shipmbcompiler'), ('target','shipmblang-bytecode'), ('version','0.3'), ('profile','general')]:
        if artifact.get(field) != value: raise VMError(f'Invalid artifact {field}.')
    if artifact.get('native_machine_code') is not False: raise VMError('Native code is not accepted.')
    if not isinstance(artifact.get('debug'),dict) or artifact['debug'].get('producer')!='shipmbcompiler': raise VMError('Invalid producer metadata.')
    contract=artifact.get('runtime_contract',{})
    if not isinstance(contract,dict) or not isinstance(contract.get('required_capabilities',[]),list): raise VMError('Invalid runtime contract.')
    capabilities=contract.get('required_capabilities',[])
    effects=contract.get('effects',[])
    allowed_capabilities=set()
    allowed_effects={'captured_output'}
    if not isinstance(effects,list) or any(type(effect) is not str or effect not in allowed_effects for effect in effects): raise VMError('Invalid effect requirement.')
    if any(type(capability) is not str or capability not in allowed_capabilities for capability in capabilities): raise VMError('Unknown capability requirement.')
    if any(type(c) is not str for c in capabilities): raise VMError('Invalid capability requirement.')
    functions=artifact.get('functions',[])
    if not isinstance(functions,list) or len(functions)>MAX_ITEMS: raise VMError('Invalid function table.')
    signatures={}; names=set(); instruction_count=len(artifact.get('bytecode',[])) if isinstance(artifact.get('bytecode'),list) else 0
    for function in functions:
        if (not isinstance(function,dict) or type(function.get('id')) is not int or function['id']<0
            or function['id'] in signatures or not isinstance(function.get('name'),str)
            or not function['name'] or function['name'] in names
            or not isinstance(function.get('return_type'),str) or function['return_type'] not in TYPES):
            raise VMError('Invalid function signature.')
        slots=_local_slots(function.get('locals'))
        parameters=function.get('parameter_slots')
        if (not isinstance(parameters,list) or any(type(slot) is not int or slot not in slots for slot in parameters)
            or len(set(parameters))!=len(parameters) or any(slots[slot]['mutable'] for slot in parameters)):
            raise VMError('Invalid function parameters.')
        signatures[function['id']]={**function, 'slots':slots,
            'argument_types':[slots[slot]['type'] for slot in parameters]}
        names.add(function['name'])
        if isinstance(function.get('bytecode'),list): instruction_count+=len(function['bytecode'])
    if instruction_count>MAX_ITEMS: raise VMError('Total instruction limit exceeded.')
    code,slots=_validate_unit(artifact.get('bytecode'),_local_slots(artifact.get('locals')),
                             capabilities,effects,signatures)
    for function in signatures.values():
        try:
            _validate_unit(function.get('bytecode'),function['slots'],capabilities,effects,signatures,
                           function['parameter_slots'],function['return_type'])
        except VMError as exc:
            exc.code=function.get('bytecode')
            raise
    return code,slots,signatures


def _local_slots(descriptions):
    if not isinstance(descriptions,list) or len(descriptions)>MAX_ITEMS: raise VMError('Invalid local descriptors.')
    slots={}
    for item in descriptions:
        if (not isinstance(item,dict) or type(item.get('id')) is not int or item['id']<0
            or not isinstance(item.get('name'),str) or not isinstance(item.get('type'),str)
            or item['type'] not in TYPES or type(item.get('mutable')) is not bool or item['id'] in slots): raise VMError('Invalid local descriptor.')
        slots[item['id']]=item
    return slots


def _validate_unit(code,slots,capabilities,effects,signatures,parameters=(),return_type=None):
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
        if op=='return' and return_type is None: raise VMError('Return outside a function.',pc)
        if op=='halt' and return_type is not None: raise VMError('Functions must return, not halt.',pc)
        if op=='clear' and args['slot'] in parameters: raise VMError('Function parameters cannot be cleared.',pc)
        if op=='call':
            function=signatures.get(args['function']) if type(args['function']) is int else None
            if not function or args['argument_types']!=function['argument_types'] or args['return_type']!=function['return_type']:
                raise VMError('Invalid function call signature.',pc)
        if op=='show' and 'captured_output' not in effects: raise VMError('Captured output effect is undeclared.',pc)
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
        elif op=='jump_if_false': pop('boolean')
        elif op=='show': pop()
        elif op=='call':
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


def _display(value):
    if type(value) is bool: return 'true' if value else 'false'
    if type(value) is list: return '['+', '.join(_display(item) for item in value)+']'
    return str(value)


def run_general_artifact(artifact, *, max_steps=100000, host=None):
    state={'output':[], 'stdout':'', 'events':[], 'variables':{}}
    pc=0
    try:
        if type(max_steps) is not int or not 1<=max_steps<=1000000: raise VMError('Invalid execution fuel limit.')
        code,slots,functions=_validate(artifact)
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
            elif op=='jump': next_pc=args['target']
            elif op=='jump_if_false':
                if not stack.pop(): next_pc=args['target']
            elif op=='show':
                text=_display(stack.pop()); output_bytes+=len(text.encode('utf-8'))+1
                if output_bytes>MAX_TEXT: raise VMError('Output size limit exceeded.',pc)
                state['output'].append(text); state['stdout']+=text+'\n'
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
        state['variables']={item['name']:values[slot] for slot,item in slots.items() if slot in values and not item['name'].startswith('$')}
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
