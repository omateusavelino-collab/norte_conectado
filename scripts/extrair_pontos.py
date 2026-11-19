import copy
import json
import time
import uuid
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

BASE = Path(__file__).resolve().parent

def command(payload):
    return payload['queries'][0]['Query']['Commands'][0]['SemanticQueryDataShapeCommand']

def fetch(config, payload):
    headers = dict(config['headers'])
    headers['ActivityId'] = str(uuid.uuid4())
    headers['RequestId'] = str(uuid.uuid4())
    request = urllib.request.Request(config['url'], data=json.dumps(payload).encode(), headers=headers)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.load(response)
            result = body['results'][0]['result']
            if result.get('error') or not result.get('data'):
                raise RuntimeError('BI retornou erro: ' + json.dumps(result)[:600])
            return result['data']
        except Exception:
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))

def decode(data):
    names = [s['Name'] for s in data['descriptor']['Select']]
    rows = []
    for ds in data['dsr']['DS']:
        dictionaries = ds.get('ValueDicts', {})
        for ph in ds.get('PH', []):
            for group, records in ph.items():
                if not isinstance(records, list):
                    continue
                schema = None
                previous = []
                for record in records:
                    schema = record.get('S', schema)
                    if not schema:
                        raise RuntimeError('Resposta sem esquema de colunas')
                    cells = iter(record.get('C', []))
                    values = []
                    for index, column in enumerate(schema):
                        bit = 1 << index
                        if record.get('R', 0) & bit:
                            value = previous[index]
                        elif record.get('\u00d8', 0) & bit:
                            value = None
                        elif column['N'] in record:
                            value = record[column['N']]
                        else:
                            value = next(cells)
                            if isinstance(value, int) and column.get('DN'):
                                value = dictionaries[column['DN']][value]
                        values.append(value)
                    previous = values
                    if len(values) != len(names):
                        raise RuntimeError('Quantidade de colunas inesperada')
                    rows.append(dict(zip(names, values)))
    return rows

def complete(data):
    datasets = data['dsr']['DS']
    return bool(datasets) and all(ds.get('IC') is True and not ds.get('RT') for ds in datasets)

def main():
    config = json.loads((BASE / 'consulta_publica.json').read_text(encoding='utf-8'))
    total_rows = decode(fetch(config, config['total']))
    expected = int(next(iter(total_rows[0].values())))
    final = None
    # Reconsulta a tabela inteira em janelas crescentes. Nao concatena lotes sobrepostos.
    # Se o servidor continuar truncando, falha sem publicar uma lista parcial.
    for size in (1000, 5000, 10000, 30000):
        payload = copy.deepcopy(config['table'])
        reduction = command(payload)['Binding']['DataReduction']
        reduction['Primary']['Window'] = {'Count': size}
        data = fetch(config, payload)
        rows = decode(data)
        print(f'Janela {size}: {len(rows)} linhas; completo={complete(data)}; total BI={expected}')
        if complete(data):
            final = rows
            break
    if final is None:
        raise RuntimeError('BI ainda indica continuacao. Nenhum arquivo publicado.')
    divergence = len(final) != expected
    warning = (f'Tabela completa: {len(final)} combinacoes; indicador BI: {expected}. As granularidades podem diferir; causa nao confirmada.' if divergence else None)
    if warning:
        print('AVISO:', warning, flush=True)
    normalized = []
    for row in final:
        normalized.append({key: row.get(source) for key, source in zip(
            ('infovia', 'localidade', 'uf', 'instituicao', 'tipo'),
            [s['Name'] for s in data['descriptor']['Select']])})
    output = BASE.parent / 'data'
    output.mkdir(exist_ok=True)
    content = {'gerado_em': datetime.now(timezone.utc).isoformat(), 'total_bi': expected,
               'linhas': len(normalized), 'completo': True, 'total_confere_com_linhas': not divergence,
               'diferenca_indicador_menos_linhas': expected - len(normalized),
               'aviso_validacao': warning, 'instituicoes': normalized}
    target = output / 'pontos_acesso.json'
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(target)
    print('Validado e salvo:', target)

if __name__ == '__main__':
    main()
