---
name: plano-de-hoje
description: Define as 3 prioridades do dia e guarda-as no vault; também lê o plano de hoje.
triggers: plano de hoje, prioridades, top 3, o que tenho para hoje
---
# Plano de hoje

- Se o resultado acima já tiver um plano guardado, lê-o em voz alta de forma curta.
- Se não houver plano, pergunta ao utilizador quais são as 3 prioridades (ou propõe-nas a partir das notas do vault e pede confirmação) e volta a chamar esta habilidade com `input` = as 3 prioridades separadas por ponto e vírgula.
- Só afirmes que guardaste o plano depois de o resultado dizer "PLANO GUARDADO".
