"""Typed VLC grammar. No runtime/library loading during parsing."""
import re
from .vlc import OPERATIONS, validate_arguments

def operation_node(op, arguments, span, query=False):
    from .general_english import EnglishError, node
    signature=OPERATIONS.get(op)
    if not signature or bool(signature[1])!=query or [a['type'] for a in arguments]!=signature[0]:
        raise EnglishError('Invalid VLC operation or operand types.',span)
    def constant(a):
        if a['kind']=='Literal': return True,a['value']
        if a['kind']=='Unary' and a['operator']=='negate' and a['operand']['kind']=='Literal':
            return True,-a['operand']['value']
        return False,None
    constants=[constant(a) for a in arguments]
    if all(known for known,value in constants):
        try: validate_arguments(op,[value for known,value in constants])
        except ValueError as e: raise EnglishError(str(e),span) from e
    return node('VLCQuery' if query else 'VLC',span,operation=op,arguments=arguments,type=signature[1])

def parse_vlc(parser,text,span):
    from .general_english import node
    masked=re.sub(r'"(?:\\.|[^"\\])*"',lambda m:'x'*len(m[0]),text)
    def lit(v): return node('Literal',span,value=v,type='text' if type(v) is str else 'integer')
    rules=[
      (r'open vlc player (.+) from (.+)','open'),
      (r'open vlc playlist (.+) from (.+)','playlist'),
      (r'(start|pause|resume|stop|close|next|previous) vlc player (.+)','control'),
      (r'seek vlc player (.+) to (.+) milliseconds','seek'),
      (r'set vlc (volume|mute|rate|fullscreen|repeat|audio track|subtitle track) for (.+) to (.+)','setting'),
      (r'load vlc subtitle for (.+) from (.+)','subtitle'),
      (r'parse vlc media for (.+) within (.+) milliseconds','parse'),
      (r'wait for vlc player (.+) to (finish|be playing|be paused|be stopped)(?: within (.+) milliseconds)?','wait'),
      (r'wait (.+) milliseconds','delay'),
      (r'configure vlc output for (.+) as (file|http|udp) to (.+) using container (.+) video codec (.+) audio codec (.+) video bitrate (.+) audio bitrate (.+)','output')]
    for pattern,op in rules:
        m=re.fullmatch(pattern,masked,re.I)
        if not m: continue
        def raw(i): return text[m.start(i):m.end(i)]
        def expr(i): return parser.expr(raw(i),span['start']+m.start(i))
        if op=='control': op=raw(1).lower();args=[expr(2)]
        elif op=='setting': op=raw(1).lower().replace(' ','_');args=[expr(2),expr(3)]
        elif op=='wait':
            state='ended' if raw(2).lower()=='finish' else raw(2).lower()[3:]
            args=[expr(1),lit(state),expr(3) if m[3] else lit(0 if state=='ended' else 10000)]
        elif op=='output': args=[expr(1),lit(raw(2).lower()),*[expr(i) for i in range(3,9)]]
        else: args=[expr(i) for i in range(1,len(m.groups())+1)]
        return operation_node(op,args,span)
    return None

def parse_query(expr,begin):
    if expr.at>=len(expr.tokens): expr.fail('Name a VLC query.')
    op=expr.tokens[expr.at][0].lower();expr.at+=1
    if op in ('audio','subtitle'):
        if expr.at>=len(expr.tokens): expr.fail('Specify ids or names.')
        op+='_'+expr.tokens[expr.at][0].lower();expr.at+=1
    if op=='metadata':
        field=expr.atom()
        if not expr.take('for'): expr.fail('Specify for player alias.')
        args=[expr.atom(),field]
    else:
        if not (expr.take('of') or expr.take('for')): expr.fail('Specify of player alias.')
        args=[expr.atom()]
    return operation_node(op,args,expr.range(begin),query=True)
