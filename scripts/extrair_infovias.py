import copy
import json
from pathlib import Path
from datetime import datetime, timezone
from extrair_pontos import fetch, decode, complete, command, main as pontos

BASE = Path(__file__).resolve().parent

def main():
    # Primeiro valida a tabela que estava truncada. Falhas impedem a publicacao.
    pontos()
    configs = json.loads((BASE / 'consultas_infovias.json').read_text(encoding='utf-8'))
    # Protecao contra substituir por engano o arquivo de CONFIGURACAO pelo arquivo de SAIDA.
    if isinstance(configs, dict) and 'consultas' in configs:
        raise RuntimeError('Arquivo errado em scripts/consultas_infovias.json: foi colocado o JSON gerado em data/. Restaure o arquivo de configuracao deste pacote. O arquivo data/consultas_infovias.json e somente saida.')
    if not isinstance(configs, list):
        raise RuntimeError('scripts/consultas_infovias.json deve ser uma LISTA de configuracoes de consulta.')
    output = []
    for index, config in enumerate(configs, 1):
        print(f"Consulta {index}/{len(configs)}: {config['id']}", flush=True)
        payload = copy.deepcopy(config['payload'])
        data = fetch(config, payload)
        if not complete(data):
            binding = command(payload)['Binding']
            reduction = binding.get('DataReduction', {})
            primary = reduction.get('Primary', {})
            if 'Window' not in primary:
                raise RuntimeError('Consulta incompleta sem janela conhecida: ' + config['id'])
            for size in (1000, 5000, 10000, 30000):
                primary['Window'] = {'Count': size}
                data = fetch(config, payload)
                if complete(data):
                    break
        if not complete(data):
            raise RuntimeError('Consulta ainda truncada: ' + config['id'])
        # Algumas consultas do Power BI sao escalares, mapas ou matrizes e nao cabem
        # no decodificador tabular. Nesses casos, preserva a resposta completa sem
        # interromper as demais consultas.
        decode_warning = None
        try:
            rows = decode(data)
        except (KeyError, IndexError, TypeError, StopIteration, RuntimeError) as error:
            rows = []
            decode_warning = str(error)
            print('AVISO: consulta ' + config['id'] +
                  ' preservada em resposta_original; formato nao tabular: ' +
                  decode_warning, flush=True)
        output.append({
            'id': config['id'],
            'campos': config['campos'],
            'linhas': rows,
            'formato_tabular_decodificado': decode_warning is None,
            'aviso_decodificacao': decode_warning,
            'resposta_original': data
        })
    target = BASE.parent / 'data' / 'consultas_infovias.json'
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps({'gerado_em': datetime.now(timezone.utc).isoformat(), 'consultas': output}, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(target)
    print('EXTRACAO VALIDADA. HTMLs nao foram alterados.')

if __name__ == '__main__':
    main()
