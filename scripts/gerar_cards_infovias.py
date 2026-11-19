"""Gera data/bi_cards_infovias.json a partir das respostas do Power BI.

Uso pelo extrator:  gerar(configs, output) -> dict
Uso avulso (sobre os arquivos ja existentes):
    python scripts/gerar_cards_infovias.py

Regras:
- Cada valor vem de uma consulta do BI identificada pelos filtros do payload
  (ID da Infovia e Macroprocesso), nao pela posicao na lista.
- A resposta e decodificada direto do formato DSR, respeitando as marcas
  de repeticao (R) e nulo (O) do Power BI.
- Campo sem consulta correspondente fica null; nada e estimado.
- Se faltar um campo obrigatorio ou um valor sair da faixa valida,
  a execucao falha e nada e publicado.
"""
import json
import re
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
INFOVIAS = ['00', '01', '02', '03', '04', '05', '06', '07', '08']
MACRO = {
    'Implantação': 'implantacao',
    'Patrimonialização': 'patrimonializacao',
    'Consórcio Operador Neutro': 'formacao_con',
}
CAMPO_MEDIA = 'Infovias - Pacote de Trabalho.Média % do macroprocesso'
CAMPO_POP = 'Sum(INFOVIAS - Pares e População.População atendida)'
CAMPO_PARES = 'Sum(INFOVIAS - Pares e Capacidade.Pares de Fibra)'
TABELA_RESUMO = 'Infovias - ID Programa.ID da Infovia'
COL_ID = 'Infovias - ID Programa.ID da Infovia'
COL_UFS = 'Infovias - Municipios-UFs.Ufs Atendidas'
COL_MUN = 'Infovias - Municipios-UFs.Municipios Atendidos'
COL_KM = 'Sum(Infovias - Backhaul.Backhaul - Dist.)'
OBRIGATORIOS = ['implantacao', 'patrimonializacao', 'formacao_con', 'populacao',
                'pares', 'km', 'ufs', 'localidades']


def decodificar_dsr(resposta):
    """Decodifica a resposta querydata em lista de dicts {Nome do Select: valor}."""
    descritor = resposta['descriptor']['Select']
    nome_por_valor = {s['Value']: s['Name'] for s in descritor}
    ds = resposta['dsr']['DS'][0]
    dicts = ds.get('ValueDicts', {})
    linhas_brutas = []
    for ph in ds.get('PH', []):
        for chave, linhas in ph.items():
            if chave.startswith('DM'):
                linhas_brutas.extend(linhas)
    colunas = None
    anterior = None
    saida = []
    for linha in linhas_brutas:
        if 'S' in linha:
            colunas = linha['S']
        if colunas is None:
            raise RuntimeError('Resposta DSR sem definicao de colunas (S).')
        repetir = linha.get('R', 0)
        nulos = linha.get('Ø', 0)
        valores = list(linha.get('C', []))
        atual = []
        for i, col in enumerate(colunas):
            if 'C' not in linha and col['N'] in linha:
                # Formato escalar (cards): valor gravado sob o nome da coluna.
                v = linha[col['N']]
                if 'DN' in col and isinstance(v, int):
                    v = dicts[col['DN']][v]
            elif repetir & (1 << i):
                if anterior is None:
                    raise RuntimeError('Marca de repeticao na primeira linha.')
                v = anterior[i]
            elif nulos & (1 << i):
                v = None
            else:
                if not valores:
                    raise RuntimeError('Linha DSR com menos valores que o esperado.')
                v = valores.pop(0)
                if 'DN' in col and isinstance(v, int):
                    v = dicts[col['DN']][v]
            atual.append(v)
        if valores:
            raise RuntimeError('Linha DSR com mais valores que o esperado.')
        anterior = atual
        saida.append({nome_por_valor[c['N']]: atual[i] for i, c in enumerate(colunas)})
    return saida


def _filtros(config):
    query = config['payload']['queries'][0]['Query']['Commands'][0][
        'SemanticQueryDataShapeCommand']['Query']
    filtros = {}
    for w in query.get('Where', []):
        cond = w.get('Condition', {})
        if 'In' not in cond:
            continue
        prop = cond['In']['Expressions'][0].get('Column', {}).get('Property')
        valores = cond['In']['Values']
        if prop and len(valores) == 1:
            filtros[prop] = str(valores[0][0]['Literal']['Value']).strip("'")
    return filtros


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _lista(texto):
    if not isinstance(texto, str):
        return []
    return [p.strip() for p in texto.split(',') if p.strip()]


def _km_br(v):
    # Arredonda como o Power BI exibe (924.59499999... -> 924,60).
    d = Decimal(repr(round(v, 9))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    s = f'{d:,.2f}'
    return s.replace(',', '#').replace('.', ',').replace('#', '.')


def _infovia(texto):
    m = re.fullmatch(r'(?i)infovia\s*(\d{2})', (texto or '').strip())
    return m.group(1) if m else None


def gerar(configs, output):
    respostas = {item['id']: item['resposta_original'] for item in output}
    cards = {iv: {} for iv in INFOVIAS}
    origem = {iv: {} for iv in INFOVIAS}

    def gravar(iv, campo, valor, consulta):
        if campo in cards[iv]:
            raise RuntimeError(f'Infovia {iv}: mais de uma consulta para {campo}.')
        cards[iv][campo] = valor
        origem[iv][campo] = consulta

    for config in configs:
        campos = config['campos']
        filtros = _filtros(config)
        iv = _infovia(filtros.get('ID da Infovia'))
        if campos == [TABELA_RESUMO] or (campos and campos[0] == TABELA_RESUMO and COL_KM in campos):
            for linha in decodificar_dsr(respostas[config['id']]):
                ivt = _infovia(linha.get(COL_ID))
                if ivt not in cards:
                    continue
                km = _num(linha.get(COL_KM))
                if km is not None:
                    gravar(ivt, 'km', _km_br(km), config['id'])
                ufs = _lista(linha.get(COL_UFS))
                if ufs:
                    gravar(ivt, 'ufs', len(ufs), config['id'])
                mun = _lista(linha.get(COL_MUN))
                if mun:
                    gravar(ivt, 'localidades', len(mun), config['id'])
            continue
        if iv is None or len(campos) != 1:
            continue
        linhas = decodificar_dsr(respostas[config['id']])
        if len(linhas) != 1:
            raise RuntimeError(f'Consulta {config["id"]}: esperado 1 valor, veio {len(linhas)}.')
        valor = _num(linhas[0].get(campos[0]))
        if campos[0] == CAMPO_MEDIA and filtros.get('Macroprocesso') in MACRO:
            gravar(iv, MACRO[filtros['Macroprocesso']], valor, config['id'])
        elif campos[0] == CAMPO_POP:
            gravar(iv, 'populacao', None if valor is None else int(round(valor)), config['id'])
        elif campos[0] == CAMPO_PARES:
            gravar(iv, 'pares', None if valor is None else int(round(valor)), config['id'])

    erros = []
    for iv in INFOVIAS:
        c = cards[iv]
        for campo in OBRIGATORIOS:
            if c.get(campo) is None:
                erros.append(f'Infovia {iv}: sem valor para {campo}.')
        for campo in ('implantacao', 'patrimonializacao', 'formacao_con'):
            v = c.get(campo)
            if v is not None and not 0 <= v <= 1:
                erros.append(f'Infovia {iv}: {campo} fora de 0-1 ({v}).')
        for campo in ('populacao', 'pares', 'ufs', 'localidades'):
            v = c.get(campo)
            if v is not None and v <= 0:
                erros.append(f'Infovia {iv}: {campo} invalido ({v}).')
        # Sem consulta individual por infovia no BI capturado: nao estimar.
        c.setdefault('pontos', None)
        c.setdefault('consorciados', None)
        c.setdefault('subprograma', None)
        c.setdefault('atualizacao', None)
    if erros:
        raise RuntimeError('bi_cards_infovias.json NAO gerado:\n' + '\n'.join(erros))

    agora = datetime.now(timezone(timedelta(hours=-3)))
    return {
        'gerado_em': agora.isoformat(timespec='seconds'),
        'extraido_em': agora.strftime('%d/%m/%Y'),
        **{iv: cards[iv] for iv in INFOVIAS},
        '_origem': origem,
    }


def gravar_arquivo(cards, destino):
    tmp = destino.with_suffix('.tmp')
    tmp.write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(destino)


if __name__ == '__main__':
    configs = json.loads((BASE / 'consultas_infovias.json').read_text(encoding='utf-8'))
    dados = json.loads((BASE.parent / 'data' / 'consultas_infovias.json').read_text(encoding='utf-8'))
    cards = gerar(configs, dados['consultas'])
    gravar_arquivo(cards, BASE.parent / 'data' / 'bi_cards_infovias.json')
    print('bi_cards_infovias.json gerado.')
