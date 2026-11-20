# Decisões de design

[English](decisions.md) | **Português**

As escolhas que eu fiz, por quê, e o que deixei de lado.

## O kit

1. **Uma CLI Python simples que imprime um objeto JSON e sai com um código documentado.** A frota é operada por
   agentes num shell, então todo resultado precisa ser legível por um programa e nada pode esperar por uma pergunta
   interativa. Só a biblioteca padrão.

2. **Só um módulo conhece o layout Markdown do arquivo de configurações, e ele só escreve na coluna de respostas.**
   Todos os outros bytes do `client-config.md` de um cliente continuam iguais, então um diff desse arquivo mostra
   exatamente o que mudou.

3. **A revisão de uma skill é um hash dos seus arquivos, sem o arquivo de configurações do cliente.** Os clientes
   podem responder perguntas ou adicionar as suas sem que o host pareça desatualizado em relação aos pins.

4. **O reconciliador recusa antes de escrever, faz dry run por padrão e confere o próprio rollback.** Toda recusa
   (dois clientes, pins errados, versões erradas, configurações ilegíveis) acontece antes da primeira escrita. Se uma
   verificação falha depois da escrita, todo arquivo é restaurado e lido de novo; ele só diz "rolled back" se os
   arquivos realmente conferem.

5. **As respostas seguem sua pergunta pela chave, e nada as inventa.** Uma mudança de template mantém as respostas
   cuja chave ainda existe, informa as removidas pela chave e lista as em branco como pendentes. As respostas vêm do
   cliente, nunca do kit ou do agente.

6. **Relatórios nunca contêm valores de respostas ou segredos.** Só caminhos, hashes, chaves e nomes de variáveis. O
   diff de revisão segue a mesma regra: arquivos de skill aparecem como diff normal, o arquivo de configurações só
   pelas chaves que mudaram.

## Mudanças por conversa

7. **O pedido de um cliente muda só o gateway dele.** Uma pergunta da biblioteca pode receber uma nova resposta numa
   instância, mas mudar uma skill da biblioteca para todos é uma nova release da biblioteca.

8. **Perguntas que só um cliente tem são linhas extras na mesma tabela, marcadas `Instance`.** O reconciliador as
   mantém nas atualizações. Deixei de lado um arquivo de sobreposição separado porque seria mais um arquivo para
   manter em sincronia em cada host.

9. **O agente nunca edita Markdown sozinho.** Ele escolhe uma operação e preenche os campos; comandos pequenos e
   determinísticos fazem a escrita, então o formato do arquivo é protegido por código e não pelo modelo.

10. **Criar uma skill recebe as perguntas dela no mesmo comando.** Um dry run verifica a mudança inteira e um apply a
    escreve, com rollback. As instruções entram pelo stdin para que aspas e apóstrofos não quebrem nada.

11. **Nada muda sem um sim a uma pergunta simples, mesmo depois de uma instrução direta.** O agente repete a mudança e
    pergunta "Posso?"; só essa resposta conta. A única exceção é responder uma pergunta de configuração que o agente
    acabou de fazer. Coloquei essa regra no topo do `AGENTS.md` do workspace, porque o agente nem sempre carrega o
    skill manager, e o `AGENTS.md` padrão do OpenClaw diz para ele agir livremente e ser proativo com automações.

12. **Um agendamento tem seu próprio sim, e o agente diz que ele custa dinheiro.** Toda execução automática usa o
    serviço de IA. Um lembrete simples pode ser só uma automação; qualquer coisa com configurações vira uma skill.

13. **Segredos nunca passam pelo chat.** O agente nunca pede uma chave e recusa uma que seja colada, pedindo que ela
    seja trocada. As integrações só guardam referências a chaves.

## Biblioteca e atualizações

14. **Uma biblioteca de exemplo organizada em releases.** Cada release tem as skills, seus pins e notas curtas em
    palavras simples, e cada skill tem os mesmos arquivos (`SKILL.md`, `client-config.template.md`, `interview.md`,
    `lineage.md`). O agente explica uma atualização a partir dessas notas, não a partir de nomes de arquivo.

15. **As atualizações vão uma release por vez.** O kit descobre a release que um host roda comparando o que está
    instalado com os pins de cada release. Pular direto para a mais nova esconderia as notas no meio do caminho e
    tornaria uma release ruim mais difícil de encontrar.

16. **Um host editado à mão só é trazido de volta depois de um sim, com backup.** Ele volta para a release mais
    próxima, mantém as respostas, e os arquivos substituídos são copiados antes. Se a edição à mão era na verdade uma
    regra do cliente, o agente oferece guardá-la como configuração.

17. **Os smoke checks confirmam que as skills realmente carregaram.** Descobri que uma skill que o OpenClaw não
    consegue ler simplesmente some enquanto `config validate` e `skills list` continuam dando sucesso, então só esses
    dois aceitariam uma release quebrada.

18. **`doctor --lint` passa com uma lista revisada de achados aceitos.** No Docker ele sempre avisa que o gateway
    escuta em todas as interfaces, o que o container precisa. Pular a verificação de segurança ou ignorar todos os
    avisos também esconderia problemas novos, então a descrição do host nomeia o único achado que eu aceito e qualquer
    outro falha. Antes de instalar qualquer coisa, o setup roda o reparo do próprio OpenClaw (`doctor --fix`), porque
    um estado novo tem migrações pendentes que o `doctor` aponta.

19. **Os pins também fixam as versões do OpenClaw e do Node.** O reconciliador recusa um host rodando outras versões,
    então um upgrade é sempre uma mudança explícita no arquivo de pins.

20. **A release quebrada da demo de rollback é opcional.** Ela só entra na imagem quando pedida, para que um "tem
    atualização?" comum nunca a ofereça por acidente.

## Integrações, clientes, registros, dados de cliente

21. **As integrações usam os próprios comandos de configuração do OpenClaw.** Ativar uma só define variáveis que a
    skill declara, recusa valores que parecem segredos, aceita uma chave só como referência e restaura a configuração
    se a skill ainda não carregar. Nunca edita o arquivo de configuração à mão nem mexe na skill.

22. **A regra de um cliente por gateway aparece no chat pela própria verificação do reconciliador.** O agente usa a
    mesma verificação que o reconciliador; o reconciliador recusaria de qualquer forma.

23. **Toda mudança aplicada é registrada: a aprovação antes, o resultado depois.** Onde o registro está ligado, um
    apply precisa de um texto de aprovação, que não pode conter a própria resposta, dados de contato ou segredos. O
    agente responde "o que mudou?" a partir desse registro. Não usei o histórico de chat do OpenClaw para isso porque
    ele não é estruturado e guarda a conversa inteira.

24. **Uma verificação de dados de cliente nas skills.** Emails, telefones, canais e IDs de chat, links de documentos e
    segredos são recusados no texto de uma skill e informados só por tipo e linha. A mesma verificação roda sobre uma
    biblioteca inteira.

## O host Docker

25. **A Control UI no navegador é a interface**, servida pelo gateway no loopback do host.

26. **Uma instância nova com o kit dentro da imagem e o OpenClaw fixado.** O script de setup refaz toda a
    configuração e pode ser rodado de novo com segurança. A imagem vem com um navegador; uma imagem menor sem ele está
    a uma configuração de distância.

27. **Padrões que custam chamadas ao modelo ficam desligados:** o skill creator embutido (ele deixaria o agente
    escrever arquivos de skill livremente), o heartbeat de 30 minutos e o memory dreaming.

## O repositório

28. **Pull requests são integrados com merge commits.** Os commits pequenos continuam visíveis como uma sequência.

## Ainda em aberto

- Se aceitar esse único achado do `doctor` está certo, ou se a configuração de rede deveria mudar.
- Pins por hash de conteúdo (hoje) ou também por revisão git.
- Se o reconciliador deveria rodar no host (hoje) ou a partir de um agente de operações pela tailnet.
