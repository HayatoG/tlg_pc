# Windows: deadlock entre recuperação especulativa e readback da GPU

## Evidência

O log local `run-20261017-202612.log` parou após 2.427 frames. O relatório
`FREEZE` mostrou `tlg:DrawPrep1` e `workerThread1` dentro do handler de page fault,
aguardando `GPU thread (command)`. O thread principal e os demais workers ficaram
aguardando a renderização. O contador de frames permaneceu parado enquanto os
vblanks continuavam avançando.

## Causa

`PipelineCache::GetProgram` mantém `programs_mutex` compartilhado enquanto um
worker especulativo executa `RefreshFlatBuf`/`StageSpecialization`. Esses acessos
à memória guest têm um ponto de recuperação (`runtime_fault_recover`), pois os
dados podem estar protegidos pela GPU ou ter sido reutilizados.

No Windows, `vectored_fault` chamava `tlggpu_handle_fault` antes de consultar
esse ponto. O readback podia enfileirar um comando e aguardar a thread da GPU;
essa thread, ao precisar publicar/atualizar shaders, precisava adquirir
`programs_mutex` exclusivamente, ainda retido pelo worker. A espera era circular.
O handler POSIX já recuperava a leitura especulativa antes do readback.

## Correção

O handler Windows agora recupera o acesso especulativo primeiro, usando o
trampolim `tlg_longjmp` existente. O worker abandona o preparo daquele draw e
libera o lock. Apenas acessos sem ponto de recuperação entram no rastreamento e
readback da GPU. Os readbacks precisos e os workers permanecem habilitados.

## Regressão

`test_windows_fault_recovery.py` extrai o handler de produção e o compila com
`compat_win.c`. Usa páginas Windows realmente protegidas e verifica:

- 100 falhas especulativas recuperadas sem chamar o callback da GPU;
- limpeza do ponto de recuperação em TLS;
- falhas normais de leitura e escrita ainda encaminhadas ao rastreamento da GPU.

O mesmo teste **falha com o handler anterior**, código 99, e **passa com a
correção**. O callback simulado falha imediatamente no caminho proibido para não
deixar o teste preso no deadlock. A etapa foi incluída no CI Windows.

```powershell
python -m unittest discover -s port/tests -p test_windows_fault_recovery.py -v
```

É necessário um compilador MSYS2 CLANG64 no PATH ou em `TLG_TEST_CLANG`.
Os 12 testes da interface também passaram. O motor completo foi recompilado com
Clang/MSYS2 e suas DLLs foram empacotadas a partir da árvore de imports.
A instalação original e os saves do usuário foram preservados.

## Validação em execução

Na sessão local `run-20261017-203640.log`, a build recompilada ultrapassou três
minutos na tela inicial/menu, com estatísticas recentes de 30 FPS e sem relatório
`FREEZE`. O menu respondeu à entrada e abriu a opção New Game. O teste preservou
os 8 workers DrawPrep e o readback preciso; não desativou a otimização nem ocultou
o detector de congelamento. Isso valida a inicialização e a continuidade da
renderização; a campanha completa não foi testada.

Em 18 de outubro de 2026, o usuário executou novamente o launcher com a build
corrigida e confirmou que o jogo funciona. Essa confirmação complementa o teste
local de inicialização/menu; não representa validação da campanha completa.

Artefatos locais: `port/dist/tlg-ui-test-windows-fixed.zip` e a cópia de teste
existente atualizada em `port/dist/tlg-ui-test-windows/`.
