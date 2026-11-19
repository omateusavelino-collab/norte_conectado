"""Cards do Power BI por infovia (os mesmos numeros exibidos no painel).

Le scripts/consultas_cards.json (consultas capturadas do proprio painel) e grava,
dentro de data/bi_cards_infovias.json, os campos:

  pontos        -> card "Pontos de Acesso Publico"   (Medidas.Qtd pontos de acesso)
  consorciados  -> card "Consorciados"               (Medidas.Qtd Consorciados)
  localidades   -> card "Localidades Atendidas"      (Medidas.Qtd Municipios Atendidos)
  km            -> card "KM de Fibra"                (Medidas.Quantidade de quilometros de fibra)
  ufs           -> card "UF's Atendidas"             (Medidas.Qtd UF's Atendidas)
  subprograma   -> card "Subprograma"                (Medidas.Programas-Concat)
  atualizacao   -> "Atualizado em: ..."              (Atualizacao.MesAno)

e o bloco "programa_cards" com os totais do programa (consulta sem filtro de infovia).

Rodar DEPOIS de extrair_infovias.py. Se faltar algum card, falha e nao grava nada.
Sem dependencias externas.
"""
import json
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
ALVO = Path(BASE.parent / 'data' / 'bi_cards_infovias.json')
INFOVIAS = ['00', '01', '02', '03', '04', '05', '06', '07', '08']
CAMPO = {
    'Medidas.Qtd pontos de acesso': 'pontos',
    'Medidas.Qtd Consorciados': 'consorciados',
    'Medidas.Qtd Municipios Atendidos': 'localidades',
    'Medidas.Quantidade de quilômetros de fibra': 'km',
    "Medidas.Qtd UF's Atendidas": 'ufs',
    'Medidas.Programas-Concat': 'subprograma',
    'Atualização.MêsAno': 'atualizacao',
}
INTEIROS = {'pontos', 'consorciados', 'localidades', 'ufs'}


def buscar(config):
    corpo = json.dumps(config['payload']).encode('utf-8')
    for tentativa in range(4):
        try:
            req = urllib.request.Request(config['url'], data=corpo, headers=config['headers'], method='POST')
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception:
            if tentativa == 3:
                raise
            time.sleep(3 * (tentativa + 1))


def valor_unico(resposta):
    """Valor de um card (consulta de uma unica medida)."""
    ds = resposta['results'][0]['result']['data']['dsr']['DS'][0]
    linhas = [l for ph in ds.get('PH', []) for k, v in ph.items() if k.startswith('DM') for l in v]
    if len(linhas) != 1:
        raise RuntimeError(f'Card com {len(linhas)} linhas (esperado 1).')
    linha = linhas[0]
    col = linha['S'][0]
    if 'C' in linha:
        v = linha['C'][0]
    elif col['N'] in linha:
        v = linha[col['N']]
    else:
        return None
    if isinstance(v, int) and col.get('DN'):
        v = ds['ValueDicts'][col['DN']][v]
    return v


def infovia_do_filtro(config):
    q = config['payload']['queries'][0]['Query']['Commands'][0]['SemanticQueryDataShapeCommand']['Query']
    for w in q.get('Where', []):
        c = w.get('Condition', {})
        if 'In' in c and c['In']['Expressions'][0].get('Column', {}).get('Property') == 'ID da Infovia':
            texto = str(c['In']['Values'][0][0]['Literal']['Value']).strip("'")
            return texto[-2:]
    return None


def normalizar(campo, v):
    if campo == 'atualizacao':
        return str(v).replace('Atualizado em:', '').strip() if v is not None else None
    if campo == 'subprograma':
        return str(v).strip() if v not in (None, '') else None
    if campo == 'km':
        if isinstance(v, str):
            return v.strip()
        n = float(v)
        return f'{n:,.2f}'.replace(',', '#').replace('.', ',').replace('#', '.')
    if v is None:
        return 0 if campo == 'consorciados' else None  # card vazio no BI = 0 consorciados
    n = float(v)
    return int(round(n)) if campo in INTEIROS else n


def extrair(buscar_fn=buscar):
    configs = json.loads((BASE / 'consultas_cards.json').read_text(encoding='utf-8'))
    cards = {iv: {} for iv in INFOVIAS}
    programa = {}
    for i, config in enumerate(configs, 1):
        campo = CAMPO.get(config['campos'][0])
        if not campo:
            continue
        print(f'Card {i}/{len(configs)}: {campo}', flush=True)
        v = normalizar(campo, valor_unico(buscar_fn(config)))
        iv = infovia_do_filtro(config)
        destino = cards[iv] if iv in cards else programa
        destino[campo] = v
    erros = [f'Infovia {iv}: sem {c}' for iv in INFOVIAS for c in CAMPO.values() if cards[iv].get(c) is None]
    if erros:
        raise RuntimeError('Cards do BI incompletos; nada gravado:\n' + '\n'.join(erros))
    return cards, programa


def main():
    cards, programa = extrair()
    dados = json.loads(ALVO.read_text(encoding='utf-8'))
    for iv in INFOVIAS:
        dados.setdefault(iv, {}).update(cards[iv])
    dados['programa_cards'] = programa
    tmp = ALVO.with_suffix('.tmp')
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(ALVO)
    print('CARDS DO BI GRAVADOS:', {iv: cards[iv]['pontos'] for iv in INFOVIAS})


if __name__ == '__main__':
    main()
