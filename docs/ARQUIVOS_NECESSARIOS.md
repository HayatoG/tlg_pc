# Arquivos do jogo necessários / Required game files

[Português](#arquivos-do-jogo-necessários) · [English](#required-game-files)

## Arquivos do jogo necessários

Tudo vem do **seu** PS4 (GoldHEN + Itemzflow). Nada disso vai no download. Use **The Last Guardian CUSA03627 (EUA) ou CUSA03745 (UE), com o update 01.03**, montado numa pasta só, com o jogo base e o update por cima. São ~25 GB.

| Arquivo | Vem de | Tamanho | Para quê |
|---|---|---|---|
| `eboot.bin` | update 01.03 | 89 MB | o código do jogo (tem que ser o do 1.03) |
| `sce_module/libc.prx`, `sce_module/libSceFios2.prx` | update 01.03 | 1,5 MB | bibliotecas do próprio jogo |
| `sce_sys/` (`param.sfo`, `playgo-chunk.dat`, `icon0.png`, `pic0.png`, `pic1.png`) | jogo base + update | ~5 MB | metadados, instalação e a arte do launcher |
| `trico_boot.psarc`, `trico_001.psarc`, `trico_002.psarc`, `trico_003.psarc` | jogo base | 2,8 + 5,8 + 5,4 + 6,8 GB | conteúdo principal |
| `trico_bootp.psarc`, `trico_001p.psarc`, `trico_002p.psarc`, `trico_003p.psarc` | update 01.03 | ~1,6 GB | correções do update |
| `trico_enu.psarc` / `trico_ptb.psarc` / `trico_esl.psarc` / `trico_frc.psarc` (+ os `…p.psarc` do update) | base + update | ~280 MB cada | vozes e textos: inglês, português, espanhol, francês |
| `sce_discmap.plt`, `sce_discmap_patch.plt` | base, update | pequenos | mapa de arquivos (recomendado) |

O **CUSA03745 (UE)** traz 15 idiomas, no lugar dos quatro do CUSA03627: inglês, francês, espanhol (Espanha), alemão, italiano, holandês, português (Portugal), russo, finlandês, sueco, dinamarquês, norueguês, polonês, turco e árabe. O launcher lista os idiomas do CUSA que estiver carregado.

**Do firmware do console (opcional, para ter som):** `libSceNgs2.sprx` (372 KB), de `/system/common/lib/` do seu PS4. Ele vai na pasta `system_lib/` ao lado do executável.

**Como montar a pasta:**
1. No Itemzflow, faça o dump do jogo (`CUSA03627` ou `CUSA03745`) e do update (`CUSA03627-patch` ou `CUSA03745-patch`) para um pendrive exFAT.
2. No PC, copie a pasta do jogo base e depois copie o conteúdo do update **por cima**, substituindo os arquivos (`eboot.bin`, `sce_module/`, `sce_sys/`).
3. Confira os tamanhos. Arquivos acima de 4 GB vindos pelo FTP do GoldHEN 2.2 chegam cortados, então use o pendrive.

## Required game files

Everything comes from **your own** PS4 (GoldHEN + Itemzflow). None of it is in the download. Use **The Last Guardian CUSA03627 (US) or CUSA03745 (EU), with update 01.03**, merged into one folder, with the base game and the update on top. About 25 GB.

| File | From | Size | Purpose |
|---|---|---|---|
| `eboot.bin` | update 01.03 | 89 MB | the game code (must be the 1.03 one) |
| `sce_module/libc.prx`, `sce_module/libSceFios2.prx` | update 01.03 | 1.5 MB | the game's own libraries |
| `sce_sys/` (`param.sfo`, `playgo-chunk.dat`, `icon0.png`, `pic0.png`, `pic1.png`) | base + update | ~5 MB | metadata, install info and the launcher art |
| `trico_boot.psarc`, `trico_001.psarc`, `trico_002.psarc`, `trico_003.psarc` | base game | 2.8 + 5.8 + 5.4 + 6.8 GB | main content |
| `trico_bootp.psarc`, `trico_001p.psarc`, `trico_002p.psarc`, `trico_003p.psarc` | update 01.03 | ~1.6 GB | update fixes |
| `trico_enu.psarc` / `trico_ptb.psarc` / `trico_esl.psarc` / `trico_frc.psarc` (+ the update's `…p.psarc`) | base + update | ~280 MB each | voices and text: English, Portuguese, Spanish, French |
| `sce_discmap.plt`, `sce_discmap_patch.plt` | base, update | small | file map (recommended) |

**CUSA03745 (EU)** ships 15 languages instead of CUSA03627's four: English, French, Spanish (Spain), German, Italian, Dutch, Portuguese (Portugal), Russian, Finnish, Swedish, Danish, Norwegian, Polish, Turkish and Arabic. The launcher lists the languages of the loaded CUSA.

**From the console firmware (optional, for audio):** `libSceNgs2.sprx` (372 KB), from `/system/common/lib/` on your PS4. It goes in the `system_lib/` folder next to the executable.

**How to build the folder:**
1. In Itemzflow, dump the game (`CUSA03627` or `CUSA03745`) and the update (`CUSA03627-patch` or `CUSA03745-patch`) to an exFAT USB drive.
2. On the PC, copy the base game folder, then copy the update's contents **over it**, replacing files (`eboot.bin`, `sce_module/`, `sce_sys/`).
3. Check the sizes. Files over 4 GB sent through GoldHEN 2.2's FTP arrive truncated, so use the USB drive.
