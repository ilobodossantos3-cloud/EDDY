# EDDY — assistente de voz que controla o teu PC

Não é um chatbot. O Eddy **ouve, decide e age**: abre apps, mexe no volume e na música, gere ficheiros, pesquisa, escreve por ti, cria lembretes, corre rotinas — e diz-te o que fez, em voz alta, com sarcasmo q.b. A janela não tem conversa: tem um núcleo holográfico que reage à voz, o briefing do dia (tempo, prioridades, lembretes, novidades, estado do sistema), as ações em curso e um botão de pânico.

```
Voz (Whisper local) → Eddy (matcher local + LLM) → Política de segurança → Ação no PC → Voz (ElevenLabs / Piper)
                                   ↕
                       Memória: vault em Markdown (Obsidian)
```

* **Modelo à tua escolha**: API (Inception Mercury, NVIDIA, OpenRouter…) **ou** modelo local do Hugging Face (GGUF/transformers/Ollama/LM Studio). Troca no `config.yaml` ou por voz: *"muda para o modelo local"*.
* **Voz**: ouvir é 100% local (`faster-whisper`). Falar usa a **ElevenLabs** (cloud, com o ID da tua voz) com **Piper** local de reserva; a Fish Audio continua disponível (`order: [fish, ...]`). O teu áudio nunca sai do PC; só o **texto** das respostas vai para a ElevenLabs (com filtro de segredos e modo privado).
* **Comandos simples não gastam LLM**: "abre o Chrome", "volume a 30", "pausa a música" são resolvidos localmente em milissegundos.

## Instalar (Windows 10/11, Python 3.12)

```powershell
cd eddy-os
.\setup.ps1            # cria .venv e instala (pergunta se queres voz e controlo do PC)
notepad .env           # põe as chaves
.\start.bat            # abre o HUD
```
Sem o `setup.ps1`: `python -m venv .venv`, `.venv\Scripts\pip install -r requirements.txt -r requirements-voice.txt -r requirements-control.txt pynput pyperclip pillow pywebview`.

### Chaves (`.env`, nunca no `config.yaml`)
| Variável | Para quê |
|---|---|
| `INCEPTION_API_KEY` | Mercury (perfil `inception`) |
| `ELEVENLABS_API_KEY` | voz ElevenLabs |
| `FISH_API_KEY` | voz Fish Audio (opcional) |
| `NVIDIA_API_KEY`, `OPENROUTER_API_KEY` | perfis alternativos |
| `HF_TOKEN` | só para modelos privados no Hugging Face |

### Primeiros passos
1. **Modelo**: em `config.yaml → llm.profiles.inception.model` está `mercury-2` (o que a documentação da Inception lista). Se a tua conta tiver o 2.5, troca o nome (no OpenRouter é `inception/mercury-2.5-preview`, perfil `openrouter`).
2. **Voz**: copia o ID da tua voz na ElevenLabs para `voice.tts.elevenlabs.voice_id`. Depois corre `python scripts/test_tts.py` — grava 5 frases em `logs/tts_test/` para ouvires. **Verifica o sotaque (pt-PT)** e se não é só ruído (se for, tenta `output_format: pcm_22050`).
3. **Microfone**: F9 (global) ou **barra de espaço na janela do Eddy** ou o botão do microfone. Depois de responder, o Eddy continua a ouvir 8 s para não teres de voltar a carregar.
4. **Apps**: `config/apps.yaml` é a lista (allowlist) do que o Eddy pode abrir. `python scripts/scan_apps.py` gera-a a partir do Menu Iniciar; **apaga o que não queres**.

### Modelo local (Hugging Face)
```powershell
.venv\Scripts\pip install -r requirements-local.txt
python scripts\download_model.py --repo bartowski/Llama-3.2-3B-Instruct-GGUF --file Llama-3.2-3B-Instruct-Q4_K_M.gguf
# em config.yaml: llm.profiles.local_gguf.model_path: models/Llama-3.2-3B-Instruct-Q4_K_M.gguf
python -m eddy --profile local_gguf
```
Modelos sem *tool-calling* nativo funcionam através de um protocolo JSON em texto (já incluído). Se a instalação do `llama-cpp-python` falhar no Windows, usa **Ollama** ou **LM Studio** (perfis `ollama`/`lmstudio`, só tens de ter o servidor ligado). Se a API falhar, o Eddy passa sozinho ao perfil `llm.fallback`.

## Usar
Exemplos: *"abre o Spotify"*, *"volume a trinta"*, *"mais alto"*, *"pausa"*, *"que horas são"*, *"lembra-me daqui a 20 minutos de ir buscar a roupa"*, *"pesquisa receitas de bacalhau"*, *"procura o relatório nas transferências"*, *"corre a rotina modo estudo"*, *"qual é o estado do PC"*, *"o que fizeste hoje"*, *"modo privado"*, *"menos sarcasmo"*, **"Eddy, para tudo"**.
Comandos de texto na caixa do HUD: `/ajuda /acoes /modelo <perfil> /privado /sarcasmo 0-3 /seguro /metricas /caixa /tendencias /plano /vault /cache`.
Arranque: `python -m eddy [--no-voice] [--profile local_gguf] [--hud window|browser|none] [--safe] [--dry-run]`.

## Segurança (lê isto)
Um assistente que controla o PC é uma superfície de ataque. Por isso:

| Nível | O quê | O que acontece |
|---|---|---|
| 0 | hora, estado do PC, listar, pesquisar notas | executa |
| 1 | abrir app, volume, música, abrir URL, lembretes, ler páginas | executa e diz |
| 2 | escrever/atalhos/clicar, mover/copiar/renomear, fechar apps, clipboard, ver ecrã | aviso no HUD; **1.ª vez na sessão pede confirmação**; cancelável |
| 3 | apagar (→ Reciclagem), desligar/reiniciar, shell, guardar rotinas | **confirmação sempre**, com os detalhes todos |

* A política é **código**, não o modelo: o LLM não consegue baixar um nível nem confirmar nada. Argumentos são validados por JSON Schema.
* Confirmações de nível 3: botão/tecla **no HUD** (teu teclado/rato) ou voz **repetindo um código de 2 palavras** (para ninguém conseguir autorizar com áudio de um vídeo). Cada confirmação vale para **uma** ação com argumentos exatos e expira em 30 s.
* Tudo o que vem de fora (páginas, RSS, ficheiros, ecrã, clipboard) é **dado não confiável**: vem delimitado, o modelo é instruído a ignorar ordens lá escondidas e, depois de ler conteúdo externo, as ações de nível 2 voltam a pedir confirmação.
* Ficheiros: só pastas de `security.allowed_folders` + vault; bloqueia `..`, links simbólicos para fora, `.ssh`, `.env`, cofres de passwords, chaves… Nunca substitui ficheiros; nunca abre `.exe/.bat/.ps1…`. Web: bloqueia `file:`/`javascript:` e (na leitura) IPs privados/localhost, também em redirecionamentos.
* Segredos: filtrados do vault, da auditoria (`logs/audit.jsonl`) e do texto enviado à Fish Audio. Não há ações de pagamentos, credenciais, antivírus/firewall, instalação de software.
* **Pânico**: botão "PARAR TUDO", `Ctrl+Alt+Esc` (se a lib `keyboard` estiver ativa) ou *"Eddy, para tudo"* — corta a voz, cancela confirmações e desliga níveis ≥2.
* `--safe` (só níveis 0–1) e `--dry-run` (mostra o que faria). Shell **desligado** por omissão (`security.shell.enabled`) e, se ligares, só comandos exatos da allowlist.
* O HUD só escuta em `127.0.0.1`, exige token aleatório, valida `Host`/`Origin` e usa CSP restrita.

## Estrutura
```
eddy/ app.py (núcleo) · llm/ (providers + fallback) · engine/ (agente, prompts, linhas do Eddy) · intents/ (matcher pt-PT)
      security/ (política, confirmações, auditoria, sanitização) · actions/ (catálogo de ações) · vault/ · skills/
      voice/ (stt, tts Fish/Piper/pyttsx3, áudio) · server/ (FastAPI+WS) · hud_web/ (HUD, temas) · scheduler.py
skills/<nome>/SKILL.md [+ run.py]   config/apps.yaml  config/routines.yaml   plugins/   vault/{raw,wiki,outputs}
```
* **Habilidades** (`skills/`): `briefing-do-dia`, `metricas`, `caixa-de-entrada`, `tendencias`, `plano-de-hoje`, `vault`. O corpo do `SKILL.md` só é lido quando a habilidade é usada.
* **Rotinas** (`config/routines.yaml`): sequências de ações; se algum passo for de nível ≥2 pede **uma** confirmação para o plano todo. Podes pedir *"cria uma rotina…"* (nível 3, confirma).
* **Plugins**: ficheiros em `plugins/` que registam ações com `@action`; só carregam se estiverem em `plugins.enabled` (há um `exemplo.py`).
* **Agenda diária** (`scheduler.jobs`): 06:55 recolher novidades (em silêncio), 07:00 briefing do dia, 09:00 plano, 19:00 encerrar o dia (fuso `Europe/Lisbon`).
* **Briefing**: diz «Eddy, dá-me o briefing». O tempo vem do Open-Meteo (sem chave; só as coordenadas de `briefing.weather` saem da máquina; `enabled: false` desliga). Muda `name`, `lat` e `lon` para a tua cidade.
* **Métricas** (opcional, só pela habilidade `metricas`): ficheiros em `vault/raw/metricas/*.md` com `date: 2026-10-19` e linhas `subscritores: 120`.

## Testes
`pip install pytest` e `pytest` — 164 testes (segurança, ações, agente com injeção simulada, voz Fish com API simulada, servidor WebSocket, habilidades, matcher).

## O que está validado e o que não está
**Validado** em testes automáticos e no HUD real num browser: núcleo, política e confirmações, ações de ficheiros/web/vault/lembretes, matcher, agente (tool-calling nativo e protocolo JSON), providers OpenAI-compatíveis, cliente Fish Audio (formato do pedido, erros, cache, fallback), servidor/HUD.
**Ainda não testado em hardware real** (não havia Windows, microfone nem chaves): captura de microfone + Whisper, reprodução de áudio, Piper, controlo de volume (`pycaw`), teclas multimédia, atalhos globais, janela `pywebview`, e a Fish Audio a sério. Pontos a confirmar contigo: formato PCM da Fish (assumi 16-bit mono; senão usa `wav`), disponibilidade/qualidade de voz **pt-PT**, e nome exato do modelo Mercury 2.5.
**Não incluído**: Gmail/Calendar, loop de "agente de ecrã" (só `screen_describe` com modelo de visão), HUD de terminal, WebSocket em tempo real da Fish (usa HTTP em streaming, mais simples e robusto).


