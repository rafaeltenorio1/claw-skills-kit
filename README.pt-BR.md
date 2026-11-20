# claw-skills-kit

[English](README.md) | **Português**

Um pequeno kit em Python para gerenciar uma biblioteca de skills em gateways OpenClaw, e um host Docker onde tudo o
que ele faz pode ser mostrado só conversando com o agente.

O cenário que eu tinha em mente: um operador roda um gateway OpenClaw por cliente. Todo cliente recebe as mesmas
skills revisadas (Camada 1: `SKILL.md`, scripts), e cada cliente tem as próprias configurações (Camada 2:
`client-config.md`, preenchido a partir de uma entrevista curta). O operador precisa instalar e atualizar skills em
gateways que já estão rodando, sem perder as respostas do cliente, e o cliente deve poder pedir mudanças com palavras
simples.

O que eu construí:

- **Entrevista.** Preenche as configurações de uma skill a partir das respostas do cliente e recusa respostas
  obrigatórias em branco. No chat, o agente encontra as perguntas em branco e as faz em palavras simples.
- **Reconciliador.** Leva um gateway que já está rodando para uma release fixada da biblioteca de skills: mantém as
  respostas do cliente, roda verificações (smoke checks), desfaz tudo se elas falharem e mostra o que mudou.
- **Skill manager.** A skill que o agente lê. O cliente pede algo em palavras simples; o agente propõe, espera um sim
  e só então roda os comandos do kit.

Todo comando roda sem perguntas interativas, imprime um único objeto JSON e sai com um código documentado, porque numa
frota quem roda os comandos é um agente.

## Como rodar

Você precisa de Docker (eu usei Docker Desktop no Windows com WSL2) e de um arquivo de variáveis **fora do
repositório** com `OPENCLAW_GATEWAY_TOKEN` e `ANTHROPIC_API_KEY` (por padrão
`~/.config/claw-skills-kit/openclaw-test.env`). Os valores nunca vão para o repositório, a imagem ou a configuração
gerada; o OpenClaw só recebe referências a eles.

```bash
docker/up.sh                          # build, configura e sobe; depois abra http://127.0.0.1:18790/
CSK_DEMO_ROLLBACK=1 docker/up.sh      # também adiciona uma release que eu quebrei de propósito
CSK_DEMO_DRIFT=1 docker/up.sh         # também edita uma skill instalada à mão, como num host antigo
docker compose -f docker/compose.yml down -v   # descarta a instância
```

Sem Docker: `uv run pytest -q` roda os testes, e `uv run python -m claw_skills_kit --help` lista os comandos.

## O que ele faz, e onde aparece

| Funcionalidade | O que você vê no chat | Comando por trás |
|---|---|---|
| Entrevista | o agente faz as perguntas em branco da skill (no máximo três) | `fill`, `question change` |
| Instalar ou atualizar mantendo as respostas do cliente | "Tem atualização?" -> o que muda, em palavras simples -> sim -> feito, respostas mantidas | `host releases`, `reconcile` |
| Um smoke test que falha deixa o host como estava | uma release quebrada falha nas verificações e tudo volta ao que era | `reconcile` |
| `doctor --lint` e `config validate` passam na versão fixada | fazem parte das verificações de toda atualização | `host doctor` |
| Uma skill que precisa de integração só carrega depois de ativada | "Posso usar o resumo da equipe?" -> conecta o canal -> carrega, a skill não é alterada | `integration` |
| Recusar dois clientes no mesmo gateway | um pedido para outra empresa é recusado | `host check-client` |
| Nenhum segredo na saída | um token colado é recusado e o cliente é orientado a trocá-lo | `secrets audit --check` |
| Aprovações de uma pessoa, registradas | o agente pergunta "Posso?" antes de tudo; "O que mudou?" vem do registro | `--approval`, `history` |
| Nada específico de cliente dentro de uma skill | "uma skill que manda email para joao@..." -> o endereço vira uma configuração | `skill create`, `lint` |
| Corrigir um host que já roda | edições à mão são encontradas, explicadas e revertidas com backup, respostas mantidas | `host releases`, `reconcile` |
| Fixar versões da skill, do gateway e do Node | um host em outra versão é recusado | `reconcile` |
| O diff é o artefato de revisão | a mudança planejada como diff de texto (configurações por chave, nunca por valor) | `reconcile --diff` |

## O que funciona, e como eu verifiquei

Testei no OpenClaw 2026.11.3 em Docker. Para cada fluxo eu conversei com o agente na Control UI e depois conferi a
transcrição do agente e os arquivos no host, para não depender do que o agente diz que fez.

- **Testes:** `uv run pytest -q` passa (407 testes). Um pequeno simulador da CLI do OpenClaw cobre os comandos que o
  kit chama.
- **Entrevista:** as respostas em branco foram encontradas e perguntadas; só as células de resposta do arquivo de
  configurações mudaram.
- **Atualização:** da primeira release para a segunda, depois de um sim: aplicada com todas as verificações passando,
  respostas do cliente mantidas, a pergunta nova feita. Rodar a mesma release de novo não muda nada (verificado por
  comando).
- **Rollback:** a atualização para a release que eu quebrei de propósito falhou nas verificações; os arquivos das
  skills ficaram idênticos byte a byte e o host continuou na release anterior.
- **doctor:** `doctor --lint` passa no host, com uma exceção revisada (abaixo). Uma descrição de host sem essa exceção
  fez a verificação falhar e a atualização ser desfeita.
- **Versões:** pins pedindo outra versão do Node foram recusados antes de qualquer escrita.
- **Integração:** a skill de resumo da equipe ficou desligada até o canal ser conectado; aí carregou, e o arquivo da
  skill nunca mudou.
- **Clientes:** um pedido para outra empresa foi recusado e nada mudou.
- **Aprovações:** o agente perguntou "Posso?" mesmo depois de instruções diretas; "não" não mudou nada; "O que mudou?"
  foi respondido a partir do registro de aprovações.
- **Dados de cliente:** uma skill pedida com um endereço de email foi criada com o endereço só como configuração; a
  verificação da biblioteca passa na minha biblioteca e falha na release quebrada, como um CI faria.
- **Drift:** uma regra adicionada à mão numa skill foi encontrada, mostrada como diff, explicada e revertida depois de
  um sim, com a versão feita à mão guardada num backup.
- **Segredos:** um token (falso) colado foi recusado sem nenhuma chamada de ferramenta e não está em nenhum arquivo
  fora do histórico do chat.
- **Setup:** `docker/up.sh` duas vezes seguidas funciona e a segunda execução não muda nada novo; os valores da chave e
  do token não estão em nenhum arquivo do estado do gateway.

## O que não funciona, ou não verifiquei

- **Um aviso do `doctor` é aceito de propósito.** Dentro de um container o gateway precisa escutar em todas as
  interfaces para o Docker publicar a porta (eu publico só no loopback do host), e o `doctor` avisa sobre isso. A
  descrição do host lista esse único achado como aceito; qualquer outro faz a verificação falhar.
- **A regra do "Posso?" é garantida por instruções**, não pelo OpenClaw. Nesta configuração o agente consegue rodar
  comandos de shell sem pedido de aprovação. O que o kit garante é que um apply precisa de um texto de aprovação e o
  registra.
- **Agendamentos são automações do OpenClaw**: o kit não faz dry run nem rollback deles.
- **Nenhum canal de chat ou caixa de email real está conectado**, então skills que postam ou leem email estão
  configuradas, mas não foram executadas.
- **Um segredo colado no chat fica no histórico de conversa do OpenClaw.** Por isso o agente pede para trocá-lo em vez
  de só ignorá-lo.
- **O smoke check confirma que as minhas skills carregaram**, não que são as únicas: as skills do próprio OpenClaw
  também estão lá.
- **O rollback cobre a pasta de skills** (e o único bloco de configuração que uma integração mexe). Ele fica em
  memória, então matar o processo no meio de um apply não desfaz nada.
- **Um host, só Docker Desktop no WSL2.** Sem hosts remotos, sem tailnet.
- **Os formatos de `client-config.md`, `interview.md` e `lineage.md` são convenções deste kit**, não um padrão do
  OpenClaw.
- **A regra de nome de skill** (`^[a-z0-9][a-z0-9-]{0,63}$`) é minha; não verifiquei a regra do próprio OpenClaw.

## O que eu faria a seguir

1. Um monitor por host que não depende do modelo, com seu próprio caminho de alerta, para notar um gateway que parou
   de responder.
2. CI no repositório: os testes, a verificação da biblioteca e uma busca por padrões de chaves.
3. Hosts remotos pela tailnet, e um snapshot em disco para que um apply interrompido ainda possa ser desfeito.
4. Pins por revisão git além do hash de conteúdo.

## Comandos

```bash
csk fill SKILL_DIR --answers ANSWERS.json --out OUT.md
csk lock LIBRARY --skills NAME... --out skills.lock.json [--openclaw VERSION] [--node VERSION]
csk reconcile --host HOST.json --library LIBRARY --target SKILLS_DIR --pins skills.lock.json [--diff] \
    [--apply [--approval TEXT] [--backup-dir DIR]]
csk question {add|change|remove} SKILL_DIR --key K [--suggested S] [--answer A] [--apply]
csk skill create SKILLS_DIR --name N --description D [--question KEY SUGGESTED [ANSWER]]... \
    (--instructions T | --instructions-file F|-) [--apply]
csk skill remove SKILLS_DIR --name N [--discard-answers] [--apply]
csk integration {status|enable|disable} SKILLS_DIR --name N [--env VAR=VALUE]... [--api-key-env VAR] [--apply]
csk host {show | check-client --name C | releases --releases DIR | verify-skills | doctor} --host HOST.json
csk lint [--library] SKILL_DIR...
csk history [--limit N]
```

`csk` é `uv run python -m claw_skills_kit` (ou `skills/skill-manager/scripts/csk`). Tudo o que escreve é dry run, a
não ser que `--apply` seja passado. Onde as aprovações são registradas, `--apply` também precisa de `--approval`. Os
relatórios trazem caminhos, hashes, chaves e nomes de variáveis, nunca valores de respostas ou segredos.

| Código | Significado |
|---|---|
| 0 | ok (leia `status`: planned, applied, unchanged, ...) |
| 1 | erro inesperado |
| 2 | erro de uso |
| 3 | template inválido |
| 4 | arquivo de respostas inválido |
| 5 | faltam respostas obrigatórias |
| 6 | uma verificação falhou, o host foi restaurado e conferido |
| 7 | a restauração falhou (`unrestored` lista os caminhos) |
| 8 | mais de um cliente no mesmo gateway |
| 9 | um pin falta ou não confere (skills, versão do OpenClaw ou do Node) |
| 10 | entrada inválida, incluindo aprovação ausente ou insegura |
| 11 | skill ausente ou inválida, incluindo dados de cliente numa skill e skills não carregadas |
| 12 | o arquivo de configurações existente não pode ser lido (deixado como está) |
| 13 | pergunta recusada |
| 14 | uma resposta seria perdida (o cliente precisa concordar antes) |
| 15 | integração recusada |
| 16 | uma verificação do host falhou (achados do `doctor`) |

## Estrutura

```
src/claw_skills_kit/   o kit (cli.py tem os comandos e os códigos de saída)
skills/skill-manager/  a skill que o agente lê, e o wrapper csk
library/releases/      minha biblioteca de skills de exemplo, uma pasta por release
library/demo-releases/ uma release quebrada de propósito, só adicionada quando pedida
host/AGENTS.csk.md     as regras colocadas no topo do AGENTS.md do workspace
docker/                imagem, arquivo compose, up.sh, bootstrap
docs/                  decisions.md (decisões de design, em inglês e português)
tests/
```
