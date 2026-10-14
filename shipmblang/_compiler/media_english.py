"""Deterministic FFmpeg statements embedded in the general English grammar."""
import re


def parse_media(parser, text, span):
    from .general_english import EnglishError, node
    from .ffmpeg import validate_job, resolve_job

    def expression(value, offset, kind=None):
        result = parser.expr(value, offset)
        if result['type'] not in ({kind} if kind else {'text', 'integer'}):
            raise EnglishError('FFmpeg operands require ' + (kind or 'text or integer') + '.', span)
        return result

    job = {'global_options': [], 'inputs': [], 'outputs': [], 'filtergraphs': [], 'overwrite': False}
    values = []

    def operand(value, offset, kind=None):
        result = expression(value, offset, kind)
        values.append(result)
        return {'operand': len(values) - 1}

    # These shortcuts lower to exactly the same job as an explicit block.
    masked = re.sub(r'"(?:\\.|[^"\\])*"', lambda m: 'x' * len(m[0]), text)
    match = re.fullmatch(r'(?:convert|transcode) (.+?) to (.+)', masked, re.I)
    audio = re.fullmatch(r'extract audio from (.+?) to (.+)', masked, re.I)
    resize = re.fullmatch(r'resize (.+?) to (\d+) by (\d+) and save as (.+)', masked, re.I)
    trim = re.fullmatch(r'trim (.+?) from (.+?) for (.+?) seconds and save as (.+)', masked, re.I)
    shortcut = match or audio or resize or trim
    if shortcut:
        output_group = 4 if resize or trim else 2
        def group(index):
            return text[shortcut.start(index):shortcut.end(index)]
        job['inputs'].append({'name': 'clip', 'url': operand(group(1), span['start'] + shortcut.start(1), 'text'), 'options': []})
        output = {'name': 'result', 'url': operand(group(output_group), span['start'] + shortcut.start(output_group), 'text'), 'options': []}
        job['outputs'].append(output)
        if audio:
            output['options'].append({'name': '-vn', 'value': None})
        if resize:
            if int(resize[2]) <= 0 or int(resize[3]) <= 0:
                raise EnglishError('Resize dimensions must be positive.', span)
            import json
            output['options'].append({'name': '-vf', 'value': operand(json.dumps(f'scale={resize[2]}:{resize[3]}'), span['start'])})
        if trim:
            for option, index in [('-ss', 2), ('-t', 3)]:
                output['options'].append({'name': option, 'value': operand(group(index), span['start'] + trim.start(index))})
    elif text.lower() == 'run ffmpeg':
        scopes = {}
        while parser.at < len(parser.clauses):
            clause, location = parser.clauses[parser.at]
            parser.at += 1
            if clause.lower() == 'end ffmpeg':
                span = {'start': span['start'], 'end': location['end']}
                break
            resource = re.fullmatch(r'(input|output) ([a-z_][a-z_0-9]*) (from|to) (.+)', clause, re.I)
            option = re.fullmatch(r'(global|input|output) option "(-[^"\s]+)"(?: for ([a-z_][a-z_0-9]*))?(?: with (.+))?', clause, re.I)
            mapping = re.fullmatch(r'map (.+?) to ([a-z_][a-z_0-9]*)', clause, re.I)
            graph = re.fullmatch(r'filter graph (.+)', clause, re.I)
            if resource:
                scope, name, prep, value = resource.groups()
                scope, name = scope.lower(), name.lower()
                if prep.lower() != ('from' if scope == 'input' else 'to') or name in scopes:
                    raise EnglishError('Use unique input/output names and input from/output to.', location)
                entry = {'name': name, 'url': operand(value, location['start'] + resource.start(4), 'text'), 'options': []}
                scopes[name] = (scope, entry)
                job[scope + 's'].append(entry)
            elif option:
                scope, name, target, value = option.groups()
                scope = scope.lower()
                if scope == 'global':
                    if target:
                        raise EnglishError('Global options do not name an input or output.', location)
                    options = job['global_options']
                else:
                    target = (target or '').lower()
                    if target not in scopes or scopes[target][0] != scope:
                        raise EnglishError('Declare the matching input/output before setting its options.', location)
                    options = scopes[target][1]['options']
                options.append({'name': name, 'value': operand(value, location['start'] + option.start(4)) if value is not None else None})
            elif mapping:
                target = mapping[2].lower()
                if target not in scopes or scopes[target][0] != 'output':
                    raise EnglishError('Declare the output before mapping a stream to it.', location)
                scopes[target][1]['options'].append({'name': '-map', 'value': operand(mapping[1], location['start'] + mapping.start(1), 'text')})
            elif graph:
                job['filtergraphs'].append(operand(graph[1], location['start'] + graph.start(1), 'text'))
            elif clause.lower() == 'overwrite outputs':
                job['overwrite'] = True
            else:
                raise EnglishError('Expected an FFmpeg input, output, scoped option, map, filter graph, or End FFmpeg.', location)
        else:
            raise EnglishError('Close the FFmpeg block with End FFmpeg.', span, question=True)
    else:
        return None
    try:
        validate_job(job, [value['type'] for value in values])
        if all(value['kind'] == 'Literal' for value in values):
            resolve_job(job, [value['value'] for value in values], [value['type'] for value in values])
    except ValueError as error:
        raise EnglishError(str(error), span) from error
    return node('FFmpeg', span, job=job, arguments=values)
