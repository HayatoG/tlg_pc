# The Last Guardian — port para PC / PC port

Por HayatoG · YouTube: [@hayatog-dev](https://www.youtube.com/@hayatog-dev) · Discord: [discord.gg/UMkdMYZh9g](https://discord.gg/UMkdMYZh9g) · Código: [github.com/HayatoG/tlg_pc](https://github.com/HayatoG/tlg_pc)

**Nenhum arquivo do jogo vem neste pacote.** Você precisa da sua própria cópia de The Last Guardian para PS4. / **No game files are included.** You need your own copy of The Last Guardian for PS4.

Versão experimental: o jogo roda do início ao gameplay, mas ainda pode travar em áreas não testadas. / Experimental build: the game runs from boot to gameplay, but may still crash in untested areas.

---

## Português

### Arquivos do jogo necessários

Tudo vem do **seu** PS4 (GoldHEN + Itemzflow). Nada disso vai no download. Use **The Last Guardian CUSA03627 (EUA) com o update 01.03**, montado numa pasta só, com o jogo base e o update por cima. São ~25 GB.

| Arquivo | Vem de | Tamanho | Para quê |
|---|---|---|---|
| `eboot.bin` | update 01.03 | 89 MB | o código do jogo (tem que ser o do 1.03) |
| `sce_module/libc.prx`, `sce_module/libSceFios2.prx` | update 01.03 | 1,5 MB | bibliotecas do próprio jogo |
| `sce_sys/` (`param.sfo`, `playgo-chunk.dat`, `icon0.png`, `pic0.png`, `pic1.png`) | jogo base + update | ~5 MB | metadados, instalação e a arte do launcher |
| `trico_boot.psarc`, `trico_001.psarc`, `trico_002.psarc`, `trico_003.psarc` | jogo base | 2,8 + 5,8 + 5,4 + 6,8 GB | conteúdo principal |
| `trico_bootp.psarc`, `trico_001p.psarc`, `trico_002p.psarc`, `trico_003p.psarc` | update 01.03 | ~1,6 GB | correções do update |
| `trico_enu.psarc` / `trico_ptb.psarc` / `trico_esl.psarc` / `trico_frc.psarc` (+ os `…p.psarc` do update) | base + update | ~280 MB cada | vozes e textos: inglês, português, espanhol, francês |
| `sce_discmap.plt`, `sce_discmap_patch.plt` | base, update | pequenos | mapa de arquivos (recomendado) |

**Do firmware do console (opcional, para o áudio nativo):** `libSceNgs2.sprx` (372 KB), de `/system/common/lib/` do seu PS4. Ele vai na pasta `system_lib/` ao lado do executável.

**Como montar a pasta:**
1. No Itemzflow, faça o dump do jogo (`CUSA03627`) e do update (`CUSA03627-patch`) para um pendrive exFAT.
2. No PC, copie a pasta do jogo base e depois copie o conteúdo do update **por cima**, substituindo os arquivos (`eboot.bin`, `sce_module/`, `sce_sys/`).
3. Confira os tamanhos. Arquivos acima de 4 GB vindos pelo FTP do GoldHEN 2.2 chegam cortados, então use o pendrive.

**PC:** Windows 10 (1903+)/11 64 bits ou Linux x86-64 (glibc 2.39+), placa de vídeo com Vulkan 1.3 (6 GB de VRAM recomendados).

### Como jogar

1. Extraia o pacote numa pasta qualquer (no Windows, fora do .zip).
2. Coloque o `libSceNgs2.sprx` na pasta `system_lib/`, ao lado do executável (opcional: sem ele, o port usa o seu próprio mixer de áudio, ainda experimental).
3. Abra **The Last Guardian** (`The Last Guardian.exe` no Windows): é o launcher novo (Qt), com telas de Gráficos, Controles, Correções, Saves, Mods, Suporte e Atualizações. O launcher antigo continua ao lado como **The Last Guardian (classic)**. Por padrão o launcher fecha quando o jogo abre e volta quando o jogo fecha (dá para mudar em Gráficos → Áudio e launcher).
   - No Windows, se aparecer "O Windows protegeu o computador", clique em *Mais informações* e depois em *Executar assim mesmo*. O programa não é assinado digitalmente.
4. Em **Pasta do jogo**, escolha a pasta que tem o `eboot.bin`.
5. Escolha um dos idiomas oferecidos para sua pasta do jogo e clique em **Jogar**. A primeira partida demora um pouco mais.

**Texto japonês experimental (EU 01.03):** com CUSA03745 e a atualização 01.03 aplicada na mesma pasta, escolha **日本語 (EU 1.03 text fallback)**. Não mova nem apague os arquivos franceses: o port os oculta apenas da visão do jogo nesta execução. Para voltar ao francês, escolha Français e inicie novamente. É necessário um launcher e runtime que incluam esse recurso; isso não adiciona suporte ao executável da edição japonesa do disco. Menus e dicas de jogo em japonês foram verificados; áudio/texto do jogo inteiro ainda não foram testados. Os botões de controle não são trocados.

**Dicas de botão na tela (opcional):** no launcher (no novo: **Gráficos → Dicas na tela (ao iniciar)**; no clássico: **Jogo e idioma → Dicas na tela**), ligue **Esconder as dicas de botão** para tirar da tela as caixinhas com o botão a apertar (pular, agarrar, chamar Trico). Vale do próximo start do jogo em diante; as legendas e a mira continuam.

No Linux, `./install_desktop.sh` adiciona o jogo ao menu de aplicativos.

### Durante o jogo

- **F10**: liga e desliga o contador de FPS
- **Insert** (ou R3 + L2 no controle): abre o menu do port (imagem, desempenho, overlay)
- **F8**: alterna entre o DLAA e o anti-aliasing do próprio jogo (Windows, NVIDIA RTX). O DLAA (NVIDIA DLSS na resolução nativa) deixa a folhagem e as bordas finas estáveis; vem ligado e pode ser desligado no launcher ou em Imagem › Anti-aliasing no menu do port. Em outras placas a opção fica desativada.
- Controles de PS4/PS5, Xbox e 8BitDo funcionam via SDL3, por USB ou Bluetooth.

### Teclado e mouse

Com a janela do jogo em foco, o mouse fica preso e gira a câmera. **Esc** solta o mouse; um clique na janela prende de novo. Abrir o menu do port (Insert) também solta o mouse.

| Ação no jogo | Botão do PS4 | Teclado e mouse |
|---|---|---|
| Andar | Analógico esquerdo | W A S D |
| Câmera | Analógico direito | Mouse (ou as setas) |
| Pular | X | Espaço |
| Agarrar, segurar | Triângulo | Clique esquerdo ou Q |
| Chamar o Trico | R1 | Clique direito ou 3 |
| | Quadrado | E ou clique do meio |
| | Círculo | Shift esquerdo |
| | L1 / L2 / R2 | 1 / R / F |
| | L3 / R3 | Z / C |
| | Direcional | I J K L |
| Menu | Options | Enter |
| Modo foto / pausa | Touchpad (esquerda / direita) | Tab / Backspace |

- No launcher, a caixa **Controles** liga o mouse, muda a sensibilidade e inverte o eixo Y. **Teclas e botões do mouse…** remapeia cada botão: clique em *Definir* e aperte a tecla ou o botão do mouse (os botões laterais e a roda também servem). Vale na próxima vez que o jogo abrir.
- No jogo, a aba **Controles** do menu do port (Insert) ajusta sensibilidade, eixo Y, suavização, aceleração e anti-zona morta na hora.

### Onde ficam as coisas

- Saves: `user/savedata/`, ao lado do executável (guarde essa pasta ao atualizar)
- Logs: `out/logs/` (`out/last_run.log` é o da última sessão; mande ele junto se reportar um problema)
- Configurações do launcher: `~/.config/tlg-launcher/` (Linux) ou `%APPDATA%\tlg-launcher` (Windows). Se você escolher outra pasta de dados em **Saves e dados**, o caminho fica em `~/.config/tlg-pc/launcher.json` (`%APPDATA%\TLG-PC` no Windows)

### Problemas

- **Som incompleto ou estranho**: sem o `libSceNgs2.sprx` em `system_lib/`, o port usa o seu próprio mixer, ainda experimental (sem reverb e sem filtros). Com o arquivo, o áudio é o nativo.
- **Não abre ou fecha sozinho**: veja a caixa de log no launcher e mande o `out/last_run.log` no [Discord](https://discord.gg/UMkdMYZh9g) ou numa [issue](https://github.com/HayatoG/tlg_pc/issues).
- **NVIDIA**: use um driver recente.

---

## English

### Required game files

Everything comes from **your own** PS4 (GoldHEN + Itemzflow). None of it is in the download. Use **The Last Guardian CUSA03627 (US) with update 01.03**, merged into one folder, with the base game and the update on top. About 25 GB.

| File | From | Size | Purpose |
|---|---|---|---|
| `eboot.bin` | update 01.03 | 89 MB | the game code (must be the 1.03 one) |
| `sce_module/libc.prx`, `sce_module/libSceFios2.prx` | update 01.03 | 1.5 MB | the game's own libraries |
| `sce_sys/` (`param.sfo`, `playgo-chunk.dat`, `icon0.png`, `pic0.png`, `pic1.png`) | base + update | ~5 MB | metadata, install info and the launcher art |
| `trico_boot.psarc`, `trico_001.psarc`, `trico_002.psarc`, `trico_003.psarc` | base game | 2.8 + 5.8 + 5.4 + 6.8 GB | main content |
| `trico_bootp.psarc`, `trico_001p.psarc`, `trico_002p.psarc`, `trico_003p.psarc` | update 01.03 | ~1.6 GB | update fixes |
| `trico_enu.psarc` / `trico_ptb.psarc` / `trico_esl.psarc` / `trico_frc.psarc` (+ the update's `…p.psarc`) | base + update | ~280 MB each | voices and text: English, Portuguese, Spanish, French |
| `sce_discmap.plt`, `sce_discmap_patch.plt` | base, update | small | file map (recommended) |

**From the console firmware (optional, for native audio):** `libSceNgs2.sprx` (372 KB), from `/system/common/lib/` on your PS4. It goes in the `system_lib/` folder next to the executable.

**How to build the folder:**
1. In Itemzflow, dump the game (`CUSA03627`) and the update (`CUSA03627-patch`) to an exFAT USB drive.
2. On the PC, copy the base game folder, then copy the update's contents **over it**, replacing files (`eboot.bin`, `sce_module/`, `sce_sys/`).
3. Check the sizes. Files over 4 GB sent through GoldHEN 2.2's FTP arrive truncated, so use the USB drive.

**PC:** 64-bit Windows 10 (1903+)/11 or x86-64 Linux (glibc 2.39+), a graphics card with Vulkan 1.3 (6 GB of VRAM recommended).

### How to play

1. Extract the package anywhere (on Windows, outside the .zip).
2. Put `libSceNgs2.sprx` in the `system_lib/` folder next to the executable (optional: without it, the port uses its own audio mixer, still experimental).
3. Open **The Last Guardian** (`The Last Guardian.exe` on Windows): the new (Qt) launcher, with Graphics, Controls, Fixes, Saves, Mods, Support and Updates screens. The old launcher is still next to it as **The Last Guardian (classic)**. By default the launcher closes when the game starts and comes back when the game closes (change it in Graphics → Audio and launcher).
   - On Windows, if "Windows protected your PC" appears, click *More info*, then *Run anyway*. The program is not digitally signed.
4. Under **Game folder**, choose the folder that has `eboot.bin`.
5. Pick one of the languages offered for your game folder and click **Play**. The first start takes a little longer.

**Experimental Japanese text (EU 01.03):** with CUSA03745 and update 01.03 applied to the same folder, select **日本語 (EU 1.03 text fallback)**. Do not move or delete the French archives: the port hides them only from the game's view for that launch. To return to French, select Français and launch again. Both launcher and runtime must contain this feature; it does not add Japanese-region disc executable support. Japanese menus and gameplay prompts were verified, not full-game audio/text coverage. Controller buttons are not swapped.

**On-screen button hints (optional):** in the launcher (new: **Graphics → On-screen hints (at start)**; classic: **Game & language → On-screen hints**), turn on **Hide the button hints** to keep the boxes with the button to press (jump, grab, call Trico) away. It applies from the next game start on; subtitles and the aim reticle stay.

On Linux, `./install_desktop.sh` adds the game to the applications menu.

### While playing

- **F10**: toggles the FPS counter
- **Insert** (or R3 + L2 on a controller): opens the port's menu (image, performance, overlay)
- **F8**: switches between DLAA and the game's own anti-aliasing (Windows, NVIDIA RTX). DLAA (NVIDIA DLSS at native resolution) keeps foliage and thin edges stable; it is on by default and can be turned off in the launcher or under Image › Anti-aliasing in the port's menu. On other graphics cards the setting is greyed out.
- PS4/PS5, Xbox and 8BitDo controllers work through SDL3, over USB or Bluetooth.

### Keyboard and mouse

While the game window has focus, it takes the mouse and the mouse turns the camera. **Esc** releases the mouse; a click in the window takes it back. Opening the port's menu (Insert) also releases it.

| In game | PS4 button | Keyboard and mouse |
|---|---|---|
| Move | Left stick | W A S D |
| Camera | Right stick | Mouse (or the arrow keys) |
| Jump | Cross | Space |
| Grab, hold on | Triangle | Left click or Q |
| Call Trico | R1 | Right click or 3 |
| | Square | E or middle click |
| | Circle | Left Shift |
| | L1 / L2 / R2 | 1 / R / F |
| | L3 / R3 | Z / C |
| | D-pad | I J K L |
| Menu | Options | Enter |
| Photo mode / pause | Touchpad (left / right) | Tab / Backspace |

- In the launcher, the **Controls** box turns the mouse on or off, sets its sensitivity and inverts the Y axis. **Keyboard and mouse buttons…** remaps each button: click *Set* and press the key or mouse button (the side buttons and the wheel work too). It applies at the next start.
- In game, the **Controls** tab of the port's menu (Insert) changes sensitivity, Y axis, smoothing, acceleration and anti-dead zone at once.

### Where things are

- Saves: `user/savedata/` next to the executable (keep this folder when updating)
- Logs: `out/logs/` (`out/last_run.log` is the latest session; attach it to bug reports)
- Launcher settings: `~/.config/tlg-launcher/` (Linux) or `%APPDATA%\tlg-launcher` (Windows). If you pick another data folder in **Saves & data**, its path is kept in `~/.config/tlg-pc/launcher.json` (`%APPDATA%\TLG-PC` on Windows)

### Problems

- **Incomplete or odd sound**: without `libSceNgs2.sprx` in `system_lib/`, the port uses its own mixer, still experimental (no reverb or filters yet). With the file, audio is native.
- **Does not start or closes by itself**: check the log box in the launcher and send `out/last_run.log` on [Discord](https://discord.gg/UMkdMYZh9g) or in an [issue](https://github.com/HayatoG/tlg_pc/issues).
- **NVIDIA**: use a recent driver.

---

This project is not affiliated with Sony Interactive Entertainment, SIE Japan Studio or genDESIGN. The Last Guardian is a trademark of Sony Interactive Entertainment. / Este projeto não tem vínculo com a Sony Interactive Entertainment, SIE Japan Studio ou genDESIGN.

## Apoie o desenvolvimento / Support development

☕ [Apoie com um café / Buy me a coffee](https://buymeacoffee.com/hayatog)

Apoio opcional para continuar desenvolvendo os ports. Os ports continuam gratuitos.
Optional support for continued port development. The ports remain free.

The Windows package contains NVIDIA DLSS (`out/nvngx_dlss.dll`) under NVIDIA's license (`out/NVIDIA-DLSS-LICENSE.txt`). NVIDIA, RTX and DLSS are trademarks of NVIDIA Corporation. / O pacote Windows contém o NVIDIA DLSS (`out/nvngx_dlss.dll`) sob a licença da NVIDIA (`out/NVIDIA-DLSS-LICENSE.txt`). NVIDIA, RTX e DLSS são marcas da NVIDIA Corporation.
