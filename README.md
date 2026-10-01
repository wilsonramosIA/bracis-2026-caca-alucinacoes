# Caça-Alucinações BRACIS 2026 — 

Esta é a versão de execução da solução determinística. Ela extrai citações por expressões regulares, resolve os vínculos contra **o SQLite recebido na execução** e grava um CSV no formato da submissão. Não usa modelos, GPU, internet, APIs, pesos nem arquivos do conjunto de desenvolvimento.

## Executar

Requisitos locais: Python 3.12, sem pacotes de terceiros.

```bash
bash run.sh /dados/avaliacao.db /dados/txt /dados/submission.csv
```

Equivalente:

```bash
python3 run.py /dados/avaliacao.db /dados/txt /dados/submission.csv
```

O terceiro argumento é o **arquivo CSV**, não uma pasta. Os documentos devem ser arquivos `*.txt` UTF-8 diretamente na pasta indicada. O programa lê o SQLite em modo somente leitura, constrói o índice canônico em memória a partir da tabela `documentos` e gera `documento_id,citacoes`, uma linha por `.txt`, inclusive quando não há citação (`-`). Os offsets são posições de caracteres no texto original. O índice é recriado em toda execução, portanto não há artefato dependente do banco de desenvolvimento.

## Docker

```bash
docker build -t bracis-regex-v4-corrected .
docker run --rm --network none \
  -v /caminho/absoluto/dos/dados:/dados:ro \
  -v /caminho/absoluto/da/saida:/saida \
  bracis-regex-v4-corrected \
  /dados/avaliacao.db /dados/txt /saida/submission.csv
```

A imagem contém apenas Python 3.12 e o código desta solução. A execução dentro do contêiner usa `--network none` e não instala nem baixa nada. O processamento é CPU; nenhuma VRAM é necessária.

## Implementação

- `run.py`: entrada única, filtro de cabeçalho, confiança seletiva e CSV.
- `bracis/extraction.py`: regras V4, incluindo a correção dos limites de frase para abreviações como `Rec. Esp.` e `Ag. Int.`.
- `bracis/normalization.py`, `bracis/canonical.py`, `bracis/resolver.py`, `bracis/models.py`: normalização, índice fechado e classificação.

A confiança `0.999` é atribuída somente à referência mais segura de cada nível, reproduzindo a configuração avaliada. A seleção usa o padrão `_n2_` no identificador do documento para o nível 2, como no conjunto fornecido.

## Evidência e limite

No conjunto de desenvolvimento distribuído (26 documentos), esta versão gerou CSV idêntico a `submission_regex_v4_corrected.csv` e obteve `score_final = 1.0999999` na métrica fornecida, com F1 macro 1,0 nos dois níveis, `tau = 0` e nenhum erro de detecção, classe ou vínculo. O diagnóstico humano informou a correção; esse resultado não é uma estimativa cega do conjunto final. Dois subconjuntos sintéticos independentes por semente também registraram `1.0999999`, mas compartilham o gerador e o formato do banco.

O formato do novo SQLite deve ser o mesmo do original, especialmente a tabela `documentos` com as colunas `documento_id`, `id`, `tribunal`, `ano`, `relator`, `natureza`, `texto` e `texto_len`. IDs canônicos são sempre obtidos desse banco.
