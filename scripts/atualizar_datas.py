"""Atualiza "Data de referencia" e "Atualizado em" nos HTMLs do Norte Conectado.

REGRAS
- Data de referencia = mes/ano informado pelo proprio Power BI (campo Atualizacao.MesAno).
- Atualizado em      = data (Brasilia) em que os dados publicados mudaram pela ultima vez.
  Se o BI nao trouxe nada novo, a data NAO muda.
- Se o BI nao devolver um mes/ano valido, nada e alterado (mantem a ultima data valida).
- Somente o texto das datas e alterado. Layout, scripts e demais dados ficam intactos.
"""
import copy
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
REPO = BASE.parent
DATA = REPO / 'data'
CONTROLE = DATA / 'datas_atualizacao.json'
PAGINAS = ['norte.html'] + [f'{i:02}.html' for i in range(9)]
MESES = ('janeiro|fevereiro|marco|março|abril|maio|junho|julho|agosto|'
         'setembro|outubro|novembro|dezembro')
RE_MES_ANO = re.compile(rf'^\s*({MESES})\s*(de|/)\s*(\d{{4}})\s*$', re.I)
# Chaves que mudam a cada execucao mesmo sem dado novo (nao entram na comparacao).
VOLATEIS = {'gerado_em', 'timestamp', 'rootActivityId', 'metrics', 'jobIds', 'jobId'}

sys.path.insert(0, str(BASE))
from extrair_pontos import fetch, decode  # noqa: E402


# ---------- 1. Data de referencia vinda do BI ----------
def _consulta_base():
    configs = json.loads((BASE / 'consultas_infovias.json').read_text(encoding='utf-8'))
    if not isinstance(configs, list) or not configs:
        raise RuntimeError('scripts/consultas_infovias.json invalido')
    return configs[0]


def _variantes():
    origem = {'SourceRef': {'Source': 'a'}}
    yield {'Measure': {'Expression': origem, 'Property': 'MêsAno'}}
    yield {'Column': {'Expression': origem, 'Property': 'MêsAno'}}
    yield {'Aggregation': {'Expression': {'Column': {'Expression': origem, 'Property': 'MêsAno'}},
                           'Function': 3}}


def data_referencia_bi():
    base = _consulta_base()
    for expr in _variantes():
        payload = copy.deepcopy(base['payload'])
        cmd = payload['queries'][0]['Query']['Commands'][0]['SemanticQueryDataShapeCommand']
        sel = dict(expr)
        sel['Name'] = 'Atualização.MêsAno'
        cmd['Query'] = {'Version': 2,
                        'From': [{'Name': 'a', 'Entity': 'Atualização', 'Type': 0}],
                        'Select': [sel]}
        cmd['Binding'] = {'Primary': {'Groupings': [{'Projections': [0]}]},
                          'DataReduction': {'DataVolume': 3, 'Primary': {'Top': {}}},
                          'Version': 1}
        try:
            linhas = decode(fetch(base, payload))
            valor = str(next(iter(linhas[0].values()))).strip()
        except Exception as erro:  # tenta a proxima forma de consulta
            print(f'  consulta da data ({next(iter(expr))}) sem resultado: {str(erro)[:120]}')
            continue
        m = RE_MES_ANO.match(valor)
        if m:
            mes = m.group(1).capitalize().replace('Marco', 'Março')
            meses = {'Janeiro':'01','Fevereiro':'02','Março':'03','Abril':'04','Maio':'05','Junho':'06','Julho':'07','Agosto':'08','Setembro':'09','Outubro':'10','Novembro':'11','Dezembro':'12'}
            return f'{meses[mes]}/{m.group(3)}'   # mes/ano informado pelo BI, ex.: 10/2026
        print(f'  valor ignorado (nao e mes/ano): {valor!r}')
    return None


# ---------- 2. Atualizado em: so muda quando os dados mudam ----------
def _limpo(obj):
    if isinstance(obj, dict):
        return {k: _limpo(v) for k, v in obj.items() if k not in VOLATEIS}
    if isinstance(obj, list):
        return [_limpo(v) for v in obj]
    return obj


def assinatura_dados(referencia):
    h = hashlib.sha256()
    for nome in ('pontos_acesso.json', 'consultas_infovias.json', 'bi_cards_infovias.json'):
        arq = DATA / nome
        if arq.exists():
            conteudo = _limpo(json.loads(arq.read_text(encoding='utf-8')))
            h.update(json.dumps(conteudo, sort_keys=True, ensure_ascii=False).encode())
    h.update((referencia or '').encode())
    return h.hexdigest()


# ---------- 3. Aplicacao nos HTMLs (fora de <script>/<style>) ----------
TAG = r'(?:\s|<[^>]+>)*'
RE_DATA_VALOR = re.compile(r'(?:--|\d{1,2})/\d{1,2}/\d{2,4}|' + rf'(?:{MESES})', re.I)


def _trocar_fora_de_codigo(html, func):
    partes = re.split(r'(<script\b.*?</script>|<style\b.*?</style>)', html, flags=re.S | re.I)
    total = 0
    for i in range(0, len(partes), 2):
        partes[i], n = func(partes[i])
        total += n
    return ''.join(partes), total


def _por_rotulo(rotulo, novo):
    padrao = re.compile(rf'({rotulo}\s*:?{TAG})([^<]+?)(\s*<)', re.I)

    def f(trecho):
        n = 0

        def sub(m):
            nonlocal n
            if not RE_DATA_VALOR.search(m.group(2)):   # so troca se o valor atual for data
                return m.group(0)
            n += 1
            return m.group(1) + novo + m.group(3)
        return padrao.sub(sub, trecho), n
    return f


def _por_classe(novo):
    padrao = re.compile(r'(<[^>]*class="[^"]*\bref-date-value\b[^"]*"[^>]*>)([^<]*)(<)', re.I)

    def f(trecho):
        return padrao.subn(lambda m: m.group(1) + novo + m.group(3), trecho)
    return f


# O pacote v3 tinha um trecho que regravava a data com o valor fixo da captura.
RE_DATA_FIXA_V3 = re.compile(r"\s*document\.querySelectorAll\('\.ref-date-value'\)\.forEach\(e=>setText\(e,String\(d\.atualizacao[^\n]*?\)\)\);")


def aplicar(pagina, referencia, atualizado):
    html = pagina.read_text(encoding='utf-8')
    html, removido = RE_DATA_FIXA_V3.subn('', html)
    r1 = r2 = r3 = 0
    if referencia:
        html, r1 = _trocar_fora_de_codigo(html, _por_classe(referencia))
        if r1 == 0:
            html, r2 = _trocar_fora_de_codigo(html, _por_rotulo(r'Data\s+de\s+refer(?:ê|&ecirc;|e)ncia', referencia))
    html, r3 = _trocar_fora_de_codigo(html, _por_rotulo(r'Atualizado\s+em', atualizado))
    pagina.write_text(html, encoding='utf-8')
    return {'data_referencia': r1 + r2, 'atualizado_em': r3, 'trava_v3_removida': bool(removido)}


def main():
    agora = datetime.now(ZoneInfo('America/Sao_Paulo'))
    anterior = json.loads(CONTROLE.read_text(encoding='utf-8')) if CONTROLE.exists() else {}

    print('Buscando data de referencia no BI...')
    mes_ano = data_referencia_bi()                     # ex.: '10/2026'
    mes_ano_anterior = anterior.get('bi_mes_ano')
    if not mes_ano_anterior and anterior.get('data_referencia'):
        # Migracao da versao antiga, que gravava '--/10/26'
        m = re.match(r'^(?:--|\d{2})/(\d{2})/(\d{2,4})$', anterior['data_referencia'])
        if m:
            mes_ano_anterior = f"{m.group(1)}/{m.group(2) if len(m.group(2)) == 4 else '20' + m.group(2)}"
            anterior['data_referencia'] = f'--/{mes_ano_anterior}'

    if not mes_ano:
        mes_ano = mes_ano_anterior
        referencia = anterior.get('data_referencia')
        print('  AVISO: BI nao devolveu mes/ano valido. Mantida a ultima data valida:', referencia)
    elif mes_ano == mes_ano_anterior and anterior.get('data_referencia', '').endswith(mes_ano):
        referencia = anterior['data_referencia']
        print('  BI sem mudanca de mes/ano -> Data de referencia mantida:', referencia)
    elif mes_ano_anterior is None:
        # Primeira execucao: nao se sabe em que dia o BI mudou para este mes.
        referencia = f'--/{mes_ano}'
        print('  Primeira leitura do BI -> dia desconhecido:', referencia)
    else:
        # BI mudou de mes/ano nesta execucao: o dia e o da deteccao,
        # desde que esteja no mesmo mes informado pelo BI. Caso contrario, fica '--'.
        hoje = agora.strftime('%d/%m/%Y')
        referencia = hoje if hoje.endswith(mes_ano) else f'--/{mes_ano}'
        print(f'  BI mudou de {mes_ano_anterior} para {mes_ano} -> Data de referencia:', referencia)

    assinatura = assinatura_dados(mes_ano)
    if assinatura != anterior.get('assinatura_dados'):
        atualizado = agora.strftime('%d/%m/%Y')
        print('  Dados mudaram -> "Atualizado em" =', atualizado)
    else:
        atualizado = anterior.get('atualizado_em') or agora.strftime('%d/%m/%Y')
        print('  Sem dados novos -> "Atualizado em" mantido:', atualizado)

    relatorio = {}
    for nome in PAGINAS:
        # Procura a pagina em qualquer pasta do repositorio (exceto .git).
        achadas = [p for p in REPO.rglob(nome) if '.git' not in p.parts]
        if not achadas:
            print(f'  AVISO: {nome} nao encontrado no repositorio.')
            relatorio[nome] = 'arquivo nao encontrado'
            continue
        for pagina in achadas:
            rel = str(pagina.relative_to(REPO))
            res = aplicar(pagina, referencia, atualizado)
            relatorio[rel] = res
            aviso = '' if (res['data_referencia'] or res['atualizado_em']) else '  <- NENHUM campo de data encontrado'
            print(f"  {rel}: referencia={res['data_referencia']} atualizado_em={res['atualizado_em']}{aviso}")
        continue

    CONTROLE.write_text(json.dumps({
        'data_referencia': referencia,
        'bi_mes_ano': mes_ano,
        'atualizado_em': atualizado,
        'assinatura_dados': assinatura,
        'verificado_em': agora.isoformat(timespec='seconds'),
        'paginas': relatorio,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Concluido. Detalhes em data/datas_atualizacao.json')


if __name__ == '__main__':
    main()
