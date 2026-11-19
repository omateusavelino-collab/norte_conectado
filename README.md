# Norte Conectado: extracao para GitHub Actions

Estrutura: .github/, data/, scripts/, README.md e requirements.txt.

## Correcao desta versao

A completude da tabela e validada pela resposta do BI (IC verdadeiro e ausencia de marcador RT). O indicador do BI e o numero de combinacoes distintas da tabela sao preservados separadamente. Uma divergencia nao e corrigida artificialmente nem interpretada automaticamente como duplicidade.

O JSON inclui total_bi, linhas, total_confere_com_linhas, diferenca_indicador_menos_linhas e aviso_validacao. Uma divergencia gera aviso explicito no log. Nenhuma linha e inventada para igualar os totais.

O aumento de janela permanece limitado a 30000 linhas; se a resposta continuar truncada, a execucao falha. O extrator nao consome o marcador de continuacao.

## Estado

Sintaxe e integridade do pacote verificadas localmente. Execucao online desta correcao ainda pendente. HTMLs nao modificados nem integrados. A divergencia observada de 769 combinacoes para indicador 770 ainda precisa ter a causa investigada.

Agendamento configurado: 10h UTC diariamente. Sem dependencias externas; Python 3.12.

## Correcao v3
Consultas escalares, mapas e matrizes que nao possuem uma linha tabular simples deixam de interromper a execucao. A resposta original do Power BI e preservada no JSON, com aviso_decodificacao. A tabela de pontos de acesso continua validada separadamente.


## IMPORTANTE: existem dois arquivos com o mesmo nome
- `scripts/consultas_infovias.json`: CONFIGURACAO fixa das consultas. Nao substitua pelo resultado do Actions.
- `data/consultas_infovias.json`: SAIDA gerada a cada execucao. Este e o arquivo que muda automaticamente.

A versao v4 valida o formato antes de executar e mostra uma mensagem clara se os arquivos forem trocados.
