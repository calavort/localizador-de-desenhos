# Atualização pelo GitHub Releases

O canal do programa é `calavort/localizador-de-desenhos`. O repositório ainda
precisa ser criado/publicado na primeira versão.

## Preparar uma versão

1. Confirme que o programa e os testes estão funcionando.
2. Escolha uma versão maior no formato `X.Y.Z`.
3. Gere o pacote sem publicar:

   `python ferramentas\publicar_release.py --versao 1.0.3`

O comando cria em `release` o ZIP e seu arquivo `.sha256`. O ZIP contém um
manifesto com o hash de cada arquivo.

## Primeira publicação

Com o GitHub autenticado neste computador, execute:

`python ferramentas\publicar_release.py --versao 1.0.3 --publicar --criar-repositorio`

Nas publicações seguintes, omita `--criar-repositorio`. Para incluir notas:

`python ferramentas\publicar_release.py --versao 1.0.4 --notas NOTAS.md --publicar`

O publicador mantém o release como rascunho até conferir os dois arquivos.

## Proteções

- download somente por HTTPS;
- SHA-256 do ZIP e hashes individuais do manifesto;
- bloqueio de caminhos inseguros, links e arquivos não autorizados;
- limite de quantidade e tamanho dos arquivos;
- recusa de atualização automática dentro de uma pasta `.git`;
- recusa automática quando `requirements.txt` mudar;
- backup e rollback se a substituição falhar;
- o endereço dos desenhos fica em `%LOCALAPPDATA%` e não entra no pacote.
