# The Last Guardian PC — detalhes técnicos

Achados de engenharia reversa, decisões e opções do port. Visão geral e como jogar: [README](../README.md).
O que foi feito e o que falta: [PROGRESSO.md](PROGRESSO.md). Planos: [issues](https://github.com/HayatoG/tlg_pc/issues).

## Estratégia

**Runtime nativo, sem decompilação completa.** O PS4 usa CPU x86-64, então o `eboot.bin` original
roda direto no processador do PC. O projeto escreve só o que fica em volta dele:

| Peça | Função | Base de reaproveitamento |
|---|---|---|
| Loader / linker | Carrega o eboot 1.03, liga `libc.prx` e `libSceFios2.prx` do jogo e resolve as imports por NID | bloodborne_pc, gow3_pc (`prepare.py`, `link_modules.py`, `probe.c`) |
| Runtime (HLE) | Reimplementa as libs do sistema PS4 (kernel, pthread, pad, savedata, áudio…) | gow3_pc `src/runtime_*.c`, shadPS4 |
| Vídeo | Traduz Gnm/PM4 e shaders GCN para **Vulkan** | núcleo de vídeo do shadPS4 (+ forks com fixes) |
| Patches | Correções em memória (FPS, resolução), validadas por sha256 do eboot | modelo do gow3_pc |

O Ghidra/REA serve para **investigação pontual** (bugs, patches, contratos de API), e não para
reescrever o jogo.

Projetos de referência:
- [deadinside28/bloodborne_pc](https://github.com/deadinside28/bloodborne_pc), que deu origem à família, nativo no Linux
- [FelipePrado0/gow3_pc](https://github.com/FelipePrado0/gow3_pc)
- [shadPS4](https://github.com/shadps4-emu/shadPS4)

Todos são GPL-2.0.

**Hardware-alvo de teste:** Ryzen 7 5700X3D, 32 GB de RAM, RTX 2060 6 GB (Vulkan 1.3), Nobara Linux.
Pontos de atenção: os 6 GB de VRAM, e o fato de os ports atuais terem sido testados principalmente em AMD.

---

## Status

| Etapa | Estado |
|---|---|
| Dump do eboot/prx (base 1.00 e update 1.03), decriptografados | ✅ ELF verificados |
| Dump dos psarc do update 1.03 | ✅ completos |
| Dump dos psarc do jogo base | ✅ completos: `trico_001/002/003` vieram do dump USB (Itemzflow), verificados contra o FTP |
| Análise Ghidra (GhidraOrbis + REA) do eboot 1.03 | ✅ auto-análise em ~9 min (heap de 16 GB) |
| Mapeamento: loop principal e threads | ✅ [`analysis/01_main_loop_threads.md`](../analysis/01_main_loop_threads.md) |
| Mapeamento: renderização / GNM | ✅ [`analysis/02_rendering_gnm.md`](../analysis/02_rendering_gnm.md) |
| Mapeamento: áudio | ✅ [`analysis/03_audio.md`](../analysis/03_audio.md) |
| Mapeamento: I/O, psarc, controle, saves, sistema | ✅ [`analysis/04_io_input_saves_system.md`](../analysis/04_io_input_saves_system.md) |
| Loader + runtime (base gow3_pc em `port/`) | ✅ compila no Nobara; 391/391 imports resolvidas (`Imports: 0 missing`) |
| **Primeiro boot no PC** | ✅ `trico main() start...` → boot em 0,41 s → engine rodando a ~28,7 fps (trava de 30), 1148 frames em 40 s sem falhas (NGS2 mudo) |
| **Imagem na tela** | ✅ logo da Japan Studio, loading e **menu inicial** renderizados corretamente na RTX 2060 (fundo 3D da caverna, DOF, texto) |
| **New Game → intro** | ✅ a cutscene de abertura roda; ~3 min sem falhas (DualSense via SDL3; som ainda mudo) |
| **Intro → gameplay** | ✅ resolvido com readbacks precisos (ver "Readback GPU→CPU"); ~2 min de teste sem falhas após pular a intro |
| **Qualidade de imagem** | ✅ imagem nativa: o tremor e as piscadas sumiram ao desligar o FSR3, o jitter e os motion vectors do port de GoW3, e ao subir o orçamento de VRAM |
| **Lança do Trico → cutscene** | ✅ corrigida a leitura curta de textura (assert `JsTex.cpp:459`), confirmado jogando |
| **Saves** | ✅ autosave + `Continue` volta ao ponto certo (SaveDataMemory2) |
| **Áudio** | ✅ funcionando na intro e no gameplay: `libSceNgs2.sprx` do firmware do próprio console linkado como módulo nativo (mixer, efeitos e VAG originais) + AJM do runtime (ATRAC9 via LibAtrac9) |
| Desempenho | 30 FPS estáveis; engasgos pontuais (20–70 ms) por falhas de leitura do modo Precise → otimizar com readback direcionado (`AsyncMap`) |

---

## Readback GPU→CPU (resolvido)

O crash acontece no fim da intro, ou ao pulá-la. Dados coletados:

- **Onde:** `0x12719aa` (spinlock), com ponteiro nulo + 0x10, chamado de `0x1c4cdd1` em `FUN_01c4c570` (renderer).
- **O que o código faz:** lê um contador e uma lista de itens via `JsComputeContext::AsyncMap` (`0x2473600`). Os dois
  buffers são **escritos pela GPU** (compute assíncrono) e lidos pela CPU sem espera. Cada item traz um índice
  (`>>16`) para a tabela de objetos em `param_2+0x31e60`.
- **Por que quebra:** no modo `TLG_READBACKS=1` (Relaxed, o padrão do gow3_pc), páginas escritas pela GPU não ficam
  protegidas. A CPU lê dados velhos, e o índice aponta para uma entrada nula.
- **`TLG_READBACKS=2` (Precise):** sincroniza na leitura, mas trava no frame 2 (deadlock no tradutor).
- **Correção (padrão no launcher e no `run_tlg.sh`: `TLG_READBACKS=2`):** o modo Precise travava em dois deadlocks, porque threads
  internas da GPU disparavam o readback que elas mesmas precisavam executar:
  1. `VkRecorder` em `CopySparseMemory`: agora lê pela visão sem proteção do memfd (`runtime_memory_read_backing`);
  2. workers `DrawPrep` em `StageSpecialization`: o handler de falhas testa `runtime_fault_recover` antes do readback,
     e o draw fica com o thread da GPU.

Também foram corrigidos no caminho: o formato de dados reservado (`data_fmt 15`) e o estouro do RecordChunk.

**Brilho estourado (#38, #40):** a exposição automática é calculada pela GPU num alvo pequeno (até 8 px de largura) que a
CPU lê depois. Sem readback desses alvos, a CPU lê um valor velho e a cena ao ar livre fica branca e o bloom exagera.
`TLG_READBACK_LINEAR=1` (padrão no launcher desde 16/10/2026) baixa os alvos lineares ou de até 8 px de largura; no
shadPS4 é o "readback linear images". Testado no cânion (`s03_Canyon`): luzes corretas e 30 FPS estáveis, sem custo
visível. O degamma do color buffer (`color_control.degamma_enable`) **não** é a causa: o TLG nunca liga esse bit.

---

## Inventário do dump (local, fora do git)

O dump foi feito do console do usuário via GoldHEN FTP, de `/mnt/sandbox/pfsmnt/CUSA03627-app0` e
`-patch0`, com o jogo em execução. O GoldHEN decriptografa os executáveis na transferência.

| Arquivo | Versão | Tipo | sha256 |
|---|---|---|---|
| `dump/eboot.bin` | 1.00 | ELF ET_SCE_EXEC (0xFE10) | `f457d7b0fe0c99d2391cac5d63d030b50bd4d4feab9659ece9f11f5604c5d89f` |
| `dump/sce_module/libc.prx` | 1.00 | ELF | `d88f1cc336985bf02fa128e8f7bbfbc21ac6c7fa1a151ba0c40b300750f2b2dd` |
| `dump/sce_module/libSceFios2.prx` | 1.00 | ELF | `ff8c06b194e593f727a1315417a2bd174111d1e2f9961636101c438dc6dfb6c3` |
| **`dump/patch0/eboot.bin`** | **1.03** | ELF ET_SCE_EXEC (0xFE10) | `91dce685be81f8f6bc88097d4fc7a62e97ca08d109621c57fe9371ae125feb3c` |
| `dump/patch0/sce_module/libc.prx` | 1.03 | ELF ET_SCE_DYNAMIC (0xFE18) | `8369c7468717567a072704be2857f5f7fb6f5e819992413b40cda3488bbb64db` |
| `dump/patch0/sce_module/libSceFios2.prx` | 1.03 | ELF ET_SCE_DYNAMIC (0xFE18) | `b8b2d2f71efbab5334e49125a1889e9383ef476757d830eee9715aec4088e20c` |

Conteúdo (psarc, compressão zlib):

- **Base:** `trico_001` 6,2 GB, `trico_002` 5,7 GB, `trico_003` 7,2 GB, `trico_boot` 2,9 GB, e os
  idiomas `enu/esl/frc/ptb` com ~0,29 GB cada.
- **Update 1.03:** `trico_*p.psarc`, 1,7 GB no total. Eles se sobrepõem aos do jogo base por overlay do Fios2.

Os números do eboot 1.03 são 92,9 MB no total. Desses, ~23,7 MB são código e rodata. O segmento de
dados tem ~68 MB, mas é quase todo zeros (buffers estáticos).

### Problema conhecido: FTP do GoldHEN v2.2 e arquivos > 4 GiB
O servidor calcula `SIZE`/`RETR` em 32 bits e entrega apenas `tamanho mod 2^32` bytes, com sucesso
aparente. O `REST` além desse ponto volta ao byte 0. Só o `LIST` mostra o tamanho real.
**Sempre compare o tamanho local com o `LIST`.** Para arquivos acima de 4 GiB, faça o dump via USB em
exFAT (Itemzflow).

---

## Achados principais

### 1. Bibliotecas do sistema importadas (eboot 1.03)
São 23 módulos e 508 funções, todas com NID resolvido.
Listas completas em `analysis/eboot_imports_1.03.json`.

| Biblioteca | Funções | Uso |
|---|---|---|
| libc (prx do próprio jogo) | 144 | C runtime |
| **libSceGnmDriver** | 110 | GPU: submits, flip, shaders, draw/dispatch, compute queues, Razor/validação |
| libkernel | 88 | memória direct/flexible, pthreads, sema/eventflag, equeue, arquivos, TSC |
| libSceFios2 (prx do próprio jogo) | 44 | sistema de arquivos e montagem dos psarc |
| libSceNet | 23 | sockets e epoll |
| libScePosix | 22 | pthread/stat POSIX |
| libSceAudio3d | 12 | importado, mas **não usado** (ver áudio) |
| libScePad | 11 | controle, light bar, vibração, sensores de movimento |
| libSceNgs2 | 10 | mixer/vozes de áudio |
| libSceVideoOut | 10 | saída de vídeo e modo de saída (o 1.03 adicionou `ConfigureOutputMode_` e `ModeSetAny_`) |
| libSceAudioOut | 7 | saída de som |
| SaveData (6), NpTrophy (5), PlayGo (5), PlayGoDialog (5), SystemService (4), AppContent, NetCtl, Sysmodule, UserService (2 cada), CommonDialog, NpManager (1 cada) | | serviços |

O Gnm/Gnmx (SDK 3.50) vêm **linkados estaticamente** dentro do eboot. Só o driver é importado.

### 2. Ponto de entrada e loop principal
No Ghidra, a base da imagem é `0x1000000`. Detalhes em [`analysis/01_main_loop_threads.md`](../analysis/01_main_loop_threads.md).

- `_start` em `0x10000a0` → `main` em `0x1207bb0`, que imprime `"trico main() start..."` e cria o objeto `App`
  (vtable `0x26ebbe0`, singleton `0x69a1b40`).
- `App::Run` em `0x1d169b0`:
  - **init:** heaps System/Object/Permanent/Assets/Temporary/Overflow, `memory.cfg`, args `-copy`/`-reboot`/`-force2k`;
  - **loop:** `while (!quit)`:
    1. GC diferido (`0x1cd5a40`, orçamento de 2 ms);
    2. callbacks;
    3. `UpdateTime` (`0x1dd45c0`);
    4. `UpdateInput` (`0x1d16380`);
    5. troca do frame context;
    6. `Frame` (`0x1dd37e0`), que chama `PS4TaskManager::RunFrame` (`0x1e4a040`).
- **Sem slot de render ou present na App.** O frame vai por mailbox para a thread `ps4render` (`0x1c53fe0`), e o
  Present (`0x1c4dfa0`) chama `sceGnmSubmitAndFlipCommandBuffers` com vsync.
- **Travado em 30 fps:**
  - `sceVideoOutSetFlipRate(h,1)` em `0x1c4f9f0`, com triple buffer;
  - o dt entre 31,7 e 35 ms é ajustado para exatamente 1/30 s, com dt máximo de 0,05 s (`0x1d16480`).
- **Threads:**
  - main;
  - `workerThread0..6` (7 fixos);
  - `ps4render` (core 0);
  - `ps4render_submitDone`;
  - `HavokWorkerThread` ×4;
  - Trophy, PlayGo;
  - ~7 threads de áudio sndx.

  As afinidades são fixas para os 7 cores do PS4.
- No shutdown, o jogo **relança a si mesmo** com `sceSystemServiceLoadExec("-reboot")`.

### 3. Renderização
Detalhes em [`analysis/02_rendering_gnm.md`](../analysis/02_rendering_gnm.md).

- **Arquitetura:** o renderer do engine **"anzu"** (`render/dev`) foi escrito contra **D3D11**: formatos DXGI,
  perfis `vs_5_0`/`ps_5_0`/`cs_5_0` e a mensagem "DirectX call failed". A camada `render/ps4/Js*` é um
  **shim D3D11 → Gnmx** (estático, headers do SDK 4.000) → `libSceGnmDriver`.
  Os setters (`JsDeviceContextInline.h`) estão inlinados no código chamador.
- **Funções-chave:**
  - **Setup:** `CreateDevice`/SwapChain em `0x1c4f9f0`, que também cria as threads `ps4render` e `ps4render_submitDone`.
  - **Recursos:** `CreateBuffer` `0x246ddd0`, `CreateTexture2D` `0x2477370`, `CreateRTV` `0x2491370`, `CreateSRV` `0x2493620`.
  - **Shaders:** `CreateVS/PS/CS` em `0x249b400`/`0x2490440`/`0x2473890`.
  - **Preparação:** `PrepareDraw` `0x2488580`, `PrepareDispatch` `0x2479b70`.
  - **Draws:** `Draw` `0x2488220`, `DrawIndexed` `0x248e080`, `DrawIndexedInstanced` `0x248e1d0`,
    `DrawIndexedInstancedIndirect` `0x248e340`.
  - **Frame:** `Render` `0x1c55690`, `BeginFrame` `0x2495480`, **`Present` `0x1c4dfa0`**.
- **Submissão:**
  - Há um único `sceGnmSubmitAndFlipCommandBuffers` por frame (VSYNC), com 3 contextos em voo.
  - Compute: `ComputeQueue::submit` (`0x249f320`) → `sceGnmDingDong`.
  - O PM4 sai dos builders do Gnm ou é escrito inline.
- **Shaders:**
  - `CreateBlob` (`0x1c53e20`) lê o `.sb` do psarc.
  - O bind passa pelo CUE `setVs/Ps/CsShader` (`0x24a0c30`/`0x24a0fd0`/`0x24a1370`) → `sceGnmSet*Shader`.
  - Há 49 blobs `OrbShdr` embutidos (1 VS, 1 PS, 47 CS), provavelmente clear/copy internos do shim.
- **Resolução:**
  - **1080p** no PS4 base, com alternativas 1760x990 e 1600x900.
  - Na **TV 4K do Pro**: checkerboard de 1680x1890 → 3360x1890.
  - O `-force2k` força 1080p.
  - O **HDR** (BT.2020 PQ) depende da capacidade do display.
  - **30 Hz fixo** (`SetFlipRate(h,1)`), com 3 display buffers.
- **Async compute:** 1 contexto do device, mais 3 por frame, mais 1 fila de dispatch-draw. Skinning, instancing,
  raycast, AABB e tracking rodam em compute, e **os resultados voltam para a CPU** (gameplay/IA). O port precisa
  de sincronização GPU→CPU correta.
- **Para o port:**
  - **(a) shadPS4**, o mesmo caminho do gow3/bloodborne. Precisa de HLE de ~33 imports Gnm + 10 VideoOut,
    parser PM4, GCN→SPIR-V, detiling e filas ACB. Ajustes: flip rate liberado, 1080p (equivalente ao `-force2k`),
    HDR desligado. **Recomendado para começar.**
  - **(b) Reimplementar o Js\* sobre D3D11/12/Vulkan.** Exige hooks em `Create*`/`PrepareDraw`/`Draw*`/`Present`
    e o layout de `JsDeviceContext` (0x130f0 bytes). Os shaders só existem como GCN, então ainda precisariam de
    tradução. O resultado é mais nativo, mas o trabalho é muito maior, ficando como evolução futura.

### 4. Áudio
Detalhes em [`analysis/03_audio.md`](../analysis/03_audio.md).

- **Cadeia:** sndx (SCE) → **NGS2** → **AudioOut**, em 8 canais float32 a 48 kHz.
  A thread `sndx_out_thread` (`0x11f28a0`) faz o render (`0x11b04f0`) e chama `sceAudioOutOutputs`, que é o clock do áudio.
- **Racks NGS2:** mastering, submixer e sampler (256 vozes), mais racks de efeito: reverb, EQ, compressor, upmix,
  delay e chorus.
- **Audio3d e alto-falante do controle não são usados.** O sndx é inicializado sem eles, então basta um stub.
- **Dados:** `game/sounds/**` no `trico_boot.psarc`, com descritores `.bod`, bancos `*_sbuf.data` (SXDF) e
  streams `.scs` (SXDS).
- **Codecs:** VAG/HEVAG ADPCM na maioria dos efeitos; **ATRAC9** em BGM, diálogo e ambiência.

### 5. I/O, psarc, controle, saves, sistema
Detalhes em [`analysis/04_io_input_saves_system.md`](../analysis/04_io_input_saves_system.md).
Esta área **não é gargalo**: partindo do runtime do gow3_pc, a estimativa é de ~4–7 dias-pessoa.

- **Fios2:**
  - `0x1f47900` inicializa o Fios2 com os filtros Cache e PsarcDearchiver.
  - A tabela de archives fica em `0x67d6440` (12 entradas, cada uma ligada a um chunk PlayGo).
  - `0x1f47740` monta **todos** os psarc em `/app0/data_trico`, na ordem base → patch `p`.
  - O overlay de idioma (`0x1f47350`) mapeia `game_<lang>` sobre `game`.
  - **Fallback:** sem `trico_boot.psarc`, o jogo lê de um diretório solto (`/app0/data_trico`).
    Dá para extrair os psarc e dispensar o formato.
- **PSARC:**
  - Versão 1.4, só zlib, blocos de 64 KiB.
  - Nos patches `p`, a TOC é ordenada por MD5 do path em maiúsculas.
  - O `trico_boot` tem 32.567 arquivos. Os maiores grupos:
    - 24.517 shaders `.sb` (111 MB);
    - 1.431 texturas `.gnf` (1,37 GB);
    - 2.246 `.data` (948 MB);
    - 293 streams de áudio `.scs` (535 MB);
    - 620 `.lua`.
  - O `bootp` (1.03) reescreve quase todo o shader cache.
  - Não há arquivos de vídeo; as cutscenes são em tempo real.
- **Lua:** a VM é HavokScript 2013.3.0, com compilador embutido. Os ~790 `.lua` são **texto-fonte**, não
  bytecode, e o ponto de entrada é `system/scripts/startup.lua`. Isso torna a lógica de jogo legível e
  modificável.
- **Controle:**
  - Há um único `scePadReadState`, em `0x1d2e239`.
  - Usa sticks, gatilhos, botões, gyro/acelerômetro, até 2 toques no touchpad, vibração com os dois motores
    separados e light bar.
  - O `runtime_pad.c` do gow3_pc cobre tudo isso.
- **Saves:**
  - API `SaveDataMemory2`, com 1 MiB + ícone. O blob é `[u32 0xffff8][u32 0][payload]`, com magic `0xd0000009`.
  - O gow3_pc só tem a v1, então é trabalho novo (~0,5–1 dia).
- **Serviços:**
  - Troféus: stub.
  - **PlayGo** deve dizer que os 27 chunks estão disponíveis; um chunk com locus 0 faz o archive não ser montado.
  - PlayGoDialog: stub.
  - `LoadExec` (o reboot) vira reexecutar o processo.
- **Rede:** são 23 imports `sceNet*` **sem call sites**, de um servidor de debug/editor da engine
  (`netmsg.lua`), e não telemetria. Basta stub.
- **`sceKernelIsNeoMode`:** escolhe o layout de memória da GPU (Pro: 0xd0000000; base: 0xb0000000). A decisão
  depende do renderer.
- **Idiomas aceitos:** enu, ptb, esl, frc.

---

## Cobertura pelo runtime existente (gow3_pc + shadPS4)

O cruzamento estático é por NIDs presentes no código-fonte e mostra **~400 de 508 imports (79%)** com
implementação. Isso não garante que cada função esteja completa.

| Lacuna | Funções | Observação |
|---|---|---|
| libSceNgs2 | 10 | **Maior buraco**: ninguém implementou ainda |
| libSceAudio3d | 12 | stub (não é usado) |
| libkernel | 16 | event flags, `IsNeoMode`, `Getdents`, alguns `scePthread*` (triviais) |
| libSceSaveData | 5 | variante `SaveDataMemory2` |
| PlayGoDialog, `LoadExec`, `PadSetMotionSensorState`, `AudioOutSetMixLevelPadSpk` | 8 | stubs ou simples |
| Fios2 (26) e libc (31) | — | não são lacuna: resolvem para os prx do próprio jogo |

---

## Estimativa (1 dev experiente, em tempo integral, partindo do gow3_pc/bloodborne_pc)

São ordens de grandeza, não compromissos. Os riscos estão listados abaixo da tabela.

| # | Área | O que fazer | Esforço |
|---|---|---|---|
| 1 | Loader/linker | Adaptar `prepare.py`/`link_modules.py`/`probe.c` para o eboot 1.03 + libc/Fios2 do TLG | 1–2 semanas |
| 2 | Runtime: kernel/sistema | 16 funções do libkernel (event flags etc.), SaveDataMemory2, PlayGo "tudo instalado", stubs (rede, troféus, PlayGoDialog, Audio3d), LoadExec → reexecutar | ~1 semana |
| 3 | Controle | Reaproveitar `runtime_pad.c` (SDL3) e mapear teclado/mouse | 2–3 dias |
| 4 | Threads e timing | Mapear afinidades (7 cores fixos) e prioridades, emular o spin-sleep por equeue, evitar busy-waits no core 0 | 1–2 semanas |
| 5 | **Vídeo até a 1ª imagem** | Ligar o núcleo do shadPS4, HLE Gnm/VideoOut e forçar 1080p | 2–4 semanas |
| 6 | **Vídeo até ficar jogável** | Bugs específicos do anzu (async compute + readback para CPU, checkerboard desligado, formatos GNF), NVIDIA/6 GB de VRAM | 1–3 meses |
| 7 | **Áudio** | AudioOut (1–2 dias) + **NGS2 em software** (mín. 2–3 semanas; +3–5 com efeitos) — _ou_ carregar o `libSceNgs2.sprx` do firmware do próprio console (1–4 semanas, não verificado) | 3–8 semanas |
| 8 | 60 FPS / extras (opcional) | Patch do flip rate + dt fixo em 1/30 + clamp de 0,05 s. Verificar física (Havok), animação e Lua; resolução/ultrawide | 2–6 semanas |

**Total até "jogável do início ao fim a 30 fps": ~4–7 meses de 1 pessoa.** Muito do trabalho em paralelo
(áudio × vídeo) e os fixes que já existem nos ports irmãos podem encurtar isso.

**Maiores riscos:**
1. Bugs gráficos do engine anzu no tradutor do shadPS4, sobretudo o async compute com readback.
2. O NGS2, que ninguém implementou ainda.
3. A NVIDIA, que é pouco testada nesses ports.
4. 60 fps, porque a física e as animações do Trico podem estar presas a 30 Hz.

---

## Opções (variáveis `TLG_*`)

Uso: `TLG_<OPÇÃO>=valor ./run_tlg.sh`. Os padrões abaixo já estão em `port/launcher/tlg_run.py` (launcher e `run_tlg.sh`) e foram validados jogando.

| Opção | Padrão TLG | O que faz |
|---|---|---|
| `TLG_READBACKS` | `2` (Precise) | sincronização GPU→CPU; o TLG precisa do 2 (`AsyncMap`); `1` = Relaxed (crash na entrada do gameplay) |
| `TLG_GC_BUDGET_MB` | `5600` | orçamento do cache de texturas em MB (6 GB de VRAM); ex.: `7000` para 8 GB |
| `TLG_UPSCALER` | `off` | `off`, `fsr3`, `taa`… (os upscalers do port de GoW3 causam tremor no TLG) |
| `TLG_JITTER` / `TLG_OBJECT_MOTION` | `0` / `0` | jitter de câmera e motion vectors para upscalers temporais |
| `TLG_PIPELINE_BINARIES` | `0` | cache `VK_KHR_pipeline_binary` (trava no NVIDIA 595) |
| `TLG_FPS` | `30` | taxa de quadros: `30` (como no PS4), `60` ou `unlocked`; patches só no eboot 1.03, ver [60fps.md](60fps.md) |
| `TLG_FRAME_STATS` | `1` | FPS e diagnóstico de engasgos no log a cada 5 s |
| `TLG_SHOW_FPS` | `0` | overlay de FPS ligado desde o início (F10 alterna em jogo) |
| `TLG_HIDE_BUTTON_HINTS` | `0` | esconde as dicas de botão do jogo (a caixa com o botão a apertar); só pelo launcher, vale do próximo start; legendas e mira ficam |
| `TLG_UI_LANG` | idioma do sistema | idioma do menu do overlay: `pt_BR` ou `en_US` |
| `TLG_PAD_FILE` | — | entrada roteirizada do controle (testes automáticos) |
| `TLG_TOGGLE_FILE` | — | máscara de otimizações desligadas, lida em tempo real |
| `TLG_GAME_DIR` | `game/CUSA03627` | pasta do jogo (visão unificada base + 1.03) |
| `TLG_NGS2` | `native` com o `.sprx`, senão `hle` | áudio: `native` = `libSceNgs2.sprx` do console; `hle` = mixer próprio (`runtime_ngs2.c`, experimental, ver [NGS2_LEVANTAMENTO.md](NGS2_LEVANTAMENTO.md)) |
| `TLG_NGS2_LOG` | `0` | mixer próprio: parâmetros não tratados, erros de decodificação e um resumo a cada 30 s |
| `TLG_NGS2_WAV` | — | mixer próprio: grava a mixagem final (float, 8 canais) para comparar com o nativo (`TLG_NGS2_TRACE_WAV`) via `port/tools/ngs2_compare.py` |
| `TLG_NGS2_USERFX` / `TLG_NGS2_REVERB` / `TLG_NGS2_CUSTOM` / `TLG_NGS2_DELAY_TYPE` | `1` / — / — / `1` | mixer próprio, para depuração: `USERFX=0` não chama os efeitos do jogo (USER_FX); `REVERB=pass` deixa o rack de reverb passar a entrada sem processar; `CUSTOM=mute` cala os racks custom (chorus/delay); `DELAY_TYPE=0` faz o delay usar um downmix mono em vez de um por canal |

Todas as opções do código usam o prefixo `TLG_` (o código herdado do gow3_pc foi renomeado).

### Dicas de botão (`TLG_HIDE_BUTTON_HINTS`)

A caixinha com o botão a apertar (pular, agarrar, chamar Trico) é o **Guide system** da engine, desenhado
pelo módulo `anzu` (função de draw em `0x190fdf0`). O port não mexe no eboot: o shim de Lua
(`port/gpu/shim/tlg_lua.cpp`) reescreve dois trechos dos scripts do jogo antes de a VM carregá-los.

| Script | Âncora | O que a edição faz |
|---|---|---|
| `game/scripts/stages/common/guide/basic_system.lua` | `GuideSystem:Start()` | `GameConfig.guideSystem = 0` (a flag que o próprio jogo usa no caminho E3, `allstages_common_temp.lua`), dentro de `pcall` para o chunk não quebrar se a propriedade sumir |
| `game/scripts/guide/guidesystem.lua` | `CreateObject = function(self)` | `return` imediato: o Guide system não cria nenhum objeto de dica, e aí não há o que desenhar (é a linha que o próprio jogo deixou comentada: "não iniciar o guide system") |

As duas edições são necessárias: `Guide_Basic_Reset()` chama `GuideSystem:Start()` **antes** do
`CommonStageEnter` (onde o caminho E3 liga a flag), então a flag sozinha chegaria tarde demais; e o
`return` sozinho deixaria o Guide system ligado e vazio. As funções do engine que usam a lista de dicas
(`Guide_SetEnable`, `Guide_fadeIn/fadeOut`, `Guide_SaveData`, `Guide_Reset`) conferem lista vazia/nula
antes de usar, então não há crash com o Guide system sem dicas. As edições são aplicadas só quando a
âncora existe: um script de outra build fica intacto.

A opção só existe no launcher (vale do próximo start do jogo); o menu Insert do jogo não tem esse item.
O log diz quais chunks foram editados (`Lua: button hints hidden in ...`); `TLG_LUA_DUMP=<pasta>` grava os
scripts que o jogo carregou, antes da edição.

Diagnóstico com o jogo aberto: `kill -USR1 <pid>` grava a pilha de todas as threads no log, e
`scripts/watch_session.sh` faz isso sozinho quando o jogo fica 20 s sem frames.

---

## Estrutura do repositório

```
tlg_launcher.sh      launcher gráfico (pt_BR/en_US): pasta do jogo, idiomas, vídeo, áudio, Jogar
scripts/install_desktop.sh  atalho no menu de aplicativos, com o ícone do port
run_tlg.sh           roda direto pelo terminal (./run_tlg.sh [segundos]), com as mesmas configurações
port/                loader + runtime + núcleo de vídeo (base gow3_pc, GPL-2.0; ver port/UPSTREAM.md)
README.md            visão geral (pt_BR + en_US)
docs/TECNICO.md      este documento (achados e detalhes técnicos)
docs/PROGRESSO.md    o que foi feito, problemas e correções, o que falta
analysis/            relatórios de engenharia reversa (.md) e listas de imports (.json)
scripts/             utilitários (imports SCE, leitor de TOC PSARC, mirror/verify FTP, progresso do dump USB)
analysis/raw/ (ignorado)  pseudocódigo bruto, manifests dos psarc e snapshot do REA
dump/   (ignorado)   arquivos do jogo, apenas locais
../tools/ (fora do repo) Ghidra 12.1.4, JDK 21, GhidraOrbis, compartilhados entre ports
```

### Ferramentas
- Ghidra 12.1.4 + GhidraOrbis, compilado do fonte com 2 patches de API para o 12.1.x
- [REA](https://github.com/morluto/rea) `rea-agents@6.4.0` como servidor MCP. Para um eboot desse tamanho,
  ajuste `REA_GHIDRA_STARTUP_TIMEOUT_MS=14400000` e `GHIDRA_HEADLESS_MAXMEM=16G`.
- `scripts/sce_imports.py <eboot> <nid_db.xml> <saida.json>` lista as imports por biblioteca, com NIDs resolvidos.
