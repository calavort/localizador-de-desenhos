LOCALIZADOR DE ARQUIVO - v1.0.2
================================

OBJETIVO
Localiza um desenho pela identificacao completa ou apenas pelo numero e abre o
PDF existente na pasta de maior revisao.

PRIMEIRO USO
1. Execute "Instalar Bibliotecas.bat" uma unica vez.
2. Abra "Iniciar Localizador.bat" ou dê dois cliques em "Localizador_Desenhos.pyw".
3. A pasta inicial ja vem definida como:
   C:\Users\joliveira\Documents\DETALHAMENTO\GATO DO MATO
4. Use "Procurar..." para trocar a pasta. O novo endereco fica registrado.

MENU INICIAR E ICONE
Extraia o ZIP completo para a pasta definitiva do programa.
Execute "Instalar no Menu Iniciar.bat". Nao exige administrador.
O atalho abre diretamente pelo pythonw.exe, sem console, com o icone aprovado.
O instalador atualiza o atalho existente. Se mover a pasta, execute-o novamente.
O icone aprovado tambem aparece no cabecalho e na janela/barra de tarefas.
Para atualizar, feche o programa e extraia este ZIP na mesma pasta,
substituindo os arquivos. A pasta de desenhos salva e preservada.

BUSCA
- IME-MC-1-44364 e 44364 encontram o mesmo projeto.
- A revisao e comparada numericamente: Rev.10 e mais nova que Rev.9.
- Revisoes compostas, como Rev.5.1, tambem sao reconhecidas.
- O PDF pode estar diretamente na pasta do desenho ou dentro de uma subpasta de revisao.
- Se houver mais de um projeto correspondente, todos aparecem na lista.
- Cada resultado permite abrir o PDF ou abrir sua pasta no Explorador.

ATUALIZACOES
O sistema usa GitHub Releases no repositorio calavort/localizador-de-desenhos,
com verificacao SHA-256, manifesto por arquivo, instalacao transacional e
rollback. Cada release deve conter:
- Localizador_de_Desenhos-X.Y.Z.zip
- Localizador_de_Desenhos-X.Y.Z.zip.sha256

Consulte GUIA_ATUALIZACAO.md. Para preparar e publicar uma versao:
python ferramentas\publicar_release.py --versao X.Y.Z --publicar --criar-repositorio

REQUISITOS
- Windows 10 ou 11
- Python 3.11 ou superior
- Microsoft Edge WebView2 (normalmente ja instalado no Windows)
