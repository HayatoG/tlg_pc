# 60 FPS / FPS livre (issue #5)

Estado em 13/10/2026: **experimental, desligado por padrão.** O modo 30 FPS é o jogo como no PS4,
sem nenhum patch.

## Como ligar

| Onde | Valor |
|---|---|
| Launcher → Vídeo → "Taxa de quadros (experimental)" | `30 FPS (como no PS4)`, `60 FPS`, `Livre (até a taxa do monitor)` |
| Terminal | `TLG_FPS=30\|60\|unlocked ./run_tlg.sh` (o `TLG_FPS` vence o launcher) |

- Os patches só são aplicados no **eboot 1.03** (sha256 `91dce685…5feb3c`). Antes de escrever, cada
  endereço é comparado com os bytes esperados no `eboot.bin`. Se o sha256 ou um byte não bater, o
  jogo roda a 30 FPS sem patch, e o log diz por quê.
- O log da sessão começa com `Frame rate patch …` (um por escrita) e `Frame rate: <modo> FPS mode, N patch writes`;
  o loader confirma com `Patches: N writes, … bytes applied`.
- **Livre:** vblank de 480 Hz (`TLG_VBLANK_HZ=0`), e o quadro sai assim que fica pronto. O teto é o
  "Limite de FPS" do overlay; em "Sem limite", vale a taxa do monitor, até 120 FPS. Com o VSync da
  janela ligado, o monitor (60 Hz aqui) limita a 60.
- `TLG_FPS_PATCHES=a,b` (só para medições) troca a lista de patches do modo.

Código: `port/scripts/tlg_patches.py` (tabela e verificação), `port/launcher/tlg_run.py` (opção,
`--patches`, `TLG_ENGINE_FPS`), `driver.cpp` (limitador), `tlg_overlay.cpp` (texto do limite).

## Como o motor decide o tempo do quadro

Endereços do Ghidra (base `0x1000000`). Offset na imagem = endereço − `0x1000000`; no arquivo,
some `0x4000`.

1. **Flip rate.** Em `JsDevice/JsSwapChain` init (`0x1c4f9f0`), a chamada em `0x1c5151a`
   (`mov esi,1; call sceVideoOutSetFlipRate`, PLT `0x24bdd78`, NID `CBiu4mCE1DA`) pede 1 quadro a
   cada 2 vblanks: 30 Hz sobre o vblank de 60 Hz. No port, o present thread (`driver.cpp`) faz
   `vblank_count % (flip_rate+1)`. **É a única trava de 30 FPS:** só esse patch já dá 60 no menu,
   na intro e no gameplay.
2. **Ritmo.** Não há sleep no loop principal. O ritmo vem do flip com VSYNC, do `Present` (`0x1c4dfa0`)
   esperando a GPU terminar o quadro anterior e da task de render (ver `analysis/01_main_loop_threads.md` §3).
3. **Delta time: tempo real, não passo fixo.** `UpdateTime` (`0x1dd45c0`) mede o TSC.
   `SmoothDeltaTime` (`0x1d16480`):
   - correção por acumulador de erro (`app+0x1a4`, ±1 s) quando `app+0x1b8 > 0.5`, limitada a 0,8–1,25×;
   - `dt = min(dt, app+0x188)` × velocidade do jogo (`app+0x1b0`). `app+0x188` é o `trico minfps N`
     do console (1/N; padrão 0,05 = 20 FPS mínimo);
   - com o objeto da física (`app+0xb0`, o módulo havok): **snap** de 0,031667 < dt < 0,035 para
     exatamente 1/30, depois um filtro de 2ª ordem (0,8333 / 0,02449 / 0,7347) e arredondamento para
     múltiplos de **1/360 s** (`round(dt*360+0.1)/360`). O resultado volta para `app+0x19c`, o dt do jogo.
   - 1/60 = 6/360 e 1/120 = 3/360, então 60 e 120 são exatos. O acumulador corrige taxas que não
     dividem 360 (144 Hz, por exemplo).
   - Diferença 1.00 × 1.03: no 1.00 (`0x1c51940`) a correção pelo acumulador é sempre aplicada; o
     1.03 só aplica com `app+0x1b8 > 0.5`. O snap e o filtro são iguais.
4. **Lua `SetMaxFps(fps)`** (binding `0x12091a0`, ajuda "SetMaxFps( fps ) : 0 = no limitation"):
   grava `1.0/fps` em `game+0x180` (singleton `0x6832568`). Os scripts chamam `SetMaxFps(30)`
   (`game/scripts/states/main.lua:412`, `common/gamesetuptbl.lua:43`). Testado: **não limita o
   FPS** (60 e 240 FPS com e sem o patch). Não achei quem lê `game+0x180`. Os patches
   `max_fps_double` (0,5/fps) e `max_fps_off` (0) existem, mas não fazem parte dos modos.
5. **Constantes de 30 Hz.** No rodata há 56 cópias de 1/30f (95 referências), 153 de 30.0f (128 referências)
   e 67 de 1/60f. A string `"operate value to the frames(30fps) of the animation"` indica que a
   animação é autorada em quadros de 30 FPS e convertida para tempo, o que independe do FPS. As três
   constantes do snap (`0x24f17f8`, `0x24f17fc`, `0x24f1800`) só são lidas pelo `SmoothDeltaTime`.
   Não auditei cada uma das outras: a validação foi empírica.
6. **Lua:** 620 scripts do `trico_boot` mais 170 do `bootp`. As lógicas de tempo usam `dt` (`TickSoldiers(deltaTime)`,
   `LT_SumDeltaTime + dt`, `GetGameDeltaTime()`). Há contadores por tick, como `autorun_campause_countdown`
   (só no autorun de debug) e `animWaitFrame` (s13_firstflight), que podem rodar 2× mais rápido a 60. **A verificar.**

## Patches (eboot 1.03)

| Nome | Endereço | Esperado → novo | Modo |
|---|---|---|---|
| `flip_rate_60` | `0x1c5151a` | `be01000000` → `be00000000` (`SetFlipRate(h,0)`) | 60, livre |
| `dt_snap_60` | `0x24f17f8` / `0x24f17fc` / `0x24f1800` | 0,035 / 1/30 / 0,031667 → 0,0175 / 1/60 / 0,015833 | 60 |
| `cloth_null_guard` | `0x128c161` | 67 B (guarda contra `[r12+0x28]==NULL` em `0x28c193` e `[rcx+rax*8]==NULL` em `0x28c197`) | 60, livre |
| `max_fps_double` | `0x12091db` | `vmovss xmm1,[1.0]` → `[0.5]` (`0x24f17e8`) | nenhum (teste) |
| `max_fps_off` | `0x12091e3` | `vdivss` → `vxorps xmm1,xmm1,xmm1` | nenhum (teste) |

O `TLG_ENGINE_FPS` (30/60/240) fica sendo o teto do "Limite de FPS" do overlay. Assim, o menu nunca
promete mais do que o modo entrega.

## Validação (RTX 2060, Ryzen 5700X3D, `uptime` < 4, janela 1265×712)

| Cena | 30 | 60 | Livre (VSync desligado, limite 240) |
|---|---|---|---|
| Boot/logo | 30,0 | 60,0 | 240 |
| Menu inicial | 30,0 | 59,6–60,2 (pior quadro 16,7–33,3 ms) | ~104 |
| Intro do New Game | 30,0 | 44–49 | — |
| Gameplay (Continue, caverna perto do Trico) | 30,0 | 40–50 | 38–45 (limite de desempenho, não de trava) |

- **Velocidade da intro:** com screenshots a cada 10 s depois do New Game, nos modos 30 e 60, as
  cenas batem nos mesmos instantes de relógio do +40 s ao +120 s. A diferença é de ~1 s, por causa
  do carregamento; o jogo não ficou 2× mais rápido. Os quadros variaram entre 44 e 49 FPS, então o
  dt variável também foi exercitado.
- **Gameplay:** Continue, 4 s andando para frente (`ly=0`), giro de câmera de 2 s (`rx=255`) e um
  pulo. A distância percorrida e o ângulo da câmera ficaram iguais nos modos 30 e 60. As legendas
  da narração aparecem no mesmo ponto.
- **Observação do usuário** (assistindo à janela): a 240 FPS no boot, ~100 no menu e ~50 depois,
  música e animações pareciam estar na velocidade normal, sem aceleração visível.
- **Piores quadros de 33 ms a 60:** é a quantização do vblank de 60 Hz. Um quadro atrasado espera
  o vblank seguinte, e abaixo de 60 FPS os quadros alternam 16,7/33,3 ms (judder). O modo livre
  apresenta assim que o quadro fica pronto (vblank de 480 Hz) e evita isso, mas o monitor de 60 Hz
  com VSync volta a quantizar.
- **Crash corrigido no caminho:** `Host fault … libnvidia-glcore … address 0x130` na
  `Scheduler::RecorderThread`, logo depois de `scheduler used on the GPU command thread … Runtime::CopyBuffer`,
  no começo da intro. Aconteceu 3 de 3 vezes a 60 e 1 de 2 vezes a 30. Causa: o `EndRendering()` lia `is_rendering` (estado do
  stage B) antes do owner hook drenar o draw pipe. Um "não está renderizando" velho deixava o
  `vkCmdCopyBuffer` ser gravado dentro do render pass que o stage B abriu. Correção: `CheckOwner`
  no início do `EndRendering` (`vk_scheduler.cpp`). Depois dela, a intro e o gameplay a 60 rodaram
  sem crash (2 sessões de ~3 min).

## O que falta (testar à mão)

1. **Física e Trico:** pulos, escaladas no pelo do Trico, o Trico pulando entre plataformas, barris,
   correntes e tecidos (Havok). O dt chega ao Havok pelo objeto em `app+0xb0`. Não confirmei se o
   passo interno é fixo.
2. **Cutscenes longas e sincronia de áudio:** fala, música e lábios, por exemplo na lança e na
   primeira comida do Trico.
3. **Contadores por quadro nos scripts** (`animWaitFrame`, contadores `RegisterTick` sem `dt`): pontes que
   caem no s13_firstflight, timers de puzzle.
4. **Câmera e input:** sensibilidade e inércia da câmera em 30 × 60 × livre.
5. **Desempenho:** o gameplay a 60 fica em 40–50 FPS nesta GPU. Pode valer usar o limite de 30
   no overlay, ou o modo livre com VRR.
6. **Livre acima de 120 FPS:** não testado no gameplay. O GoW3 quebrava acima de ~120; aqui o
   limite padrão também é 120.
7. Achar quem lê `game+0x180` (`SetMaxFps`). Se for um dt mínimo em algum sistema, este é o primeiro
   suspeito para qualquer aceleração.
