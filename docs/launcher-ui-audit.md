# Auditoria da interface do launcher

Data: 17 de outubro de 2026.

## Resultado e alcance

**100% dos controles inventariados na UI antiga estão presentes na nova UI.**
Nenhuma opção, faixa numérica, alternativa de seletor, ação principal ou ação dos
diálogos foi removida. A nova UI acrescenta cinco botões de navegação e uma barra
horizontal no log. A comparação foi feita instanciando ambas as interfaces com
configurações isoladas e comparando seus widgets, além de comparar o código dos callbacks.

Isso representa paridade do inventário funcional da interface, não uma declaração
de 100% de cobertura de linhas ou de validação do jogo completo. Os testes de
preparação/execução usam serviços e subprocessos simulados; nenhum jogo foi iniciado.
A inspeção visual foi realizada no Windows com Tk/ttk `clam`; Linux não foi inspecionado.

Base anterior ao redesign: `b8d5f412398fae52a444400a9b5131bc1c970cc3`,
`port/launcher/tlg_launcher.py`. O inventário original está congelado em
[`launcher_ui_legacy.json`](../port/tests/data/launcher_ui_legacy.json).

## Paridade dos controles

As linhas abaixo se sobrepõem por função; não devem ser somadas.

| Grupo | UI antiga → nova | Localização atual / evidência |
| --- | --- | --- |
| Pastas do jogo e dos módulos | 2 → 2 campos; 2 → 2 ações Procurar | Jogo e idioma; escolha de pasta e persistência verificadas |
| Idioma do jogo e da interface | 2 → 2 seletores | Jogo e idioma; eventos reais de seleção, idiomas US/EU e reconstrução da interface verificados |
| Modo de exibição e FPS | 2 → 2 seletores, com as mesmas alternativas | Imagem e vídeo; todas as escolhas exercitadas |
| Áudio nativo, VSync, overlay FPS, câmera no mouse, inverter Y, SMAA e ajustes de cor | 7 → 7 checkboxes | As sete opções alternam e persistem pelos callbacks existentes |
| VRAM, sensibilidade e quatro ajustes de cor | 6 → 6 campos numéricos | Mesmas faixas e incrementos; persistência e limites dos filtros verificados |
| Nitidez | 1 → 1 seletor | Desligada, RCAS e CAS; valores correspondentes no INI verificados |
| Ações principais | 9 → 9 botões existentes, mais 5 de navegação | Procurar ×2, remapear, Sair, Jogar, logs, mods, saves e limpar cache |
| Links externos | 3 → 3 | YouTube, Discord e apoio; destinos verificados sem abrir sites |
| Remapeamento | 17 → 17 campos; 19 → 19 botões | Os 17 Definir, Restaurar tudo e Fechar continuam disponíveis; gravação e restauração verificadas |
| Mods | 3 → 3 botões | Abrir pasta, atualizar e fechar; lista e ativação verificadas com mod temporário simulado |
| Registro | Log e atualização preservados | Saída, conclusão, erros e preservação após troca de idioma verificados |
| Estado de execução | Regras preservadas | Pronto, arquivos ausentes, jogo em execução, bloqueio de Jogar/cache, confirmação do cache e Sair verificados |

Os conjuntos de variáveis são idênticos: **9 variáveis de configurações + 6 de
filtros**, além dos cinco seletores. Uma comparação estrutural da AST confirmou
que **17 métodos existentes permanecem idênticos**, incluindo `changed`,
`filters_changed`, `refresh_status`, `play`, `run_game`, `pump`, `clear_cache` e `quit`.
Os sete métodos antigos alterados cuidam da construção/apresentação da UI; as
funções aninhadas de remapeamento e mods mantêm sua lógica.

## Problemas de contraste encontrados e corrigidos

1. **Seletor com foco:** o mapa herdado de `clam` em `readonly + focus` aplicava
   texto branco (`#ffffff`) ao fundo claro (`#f8f5ed`): **1,09:1**. Agora o texto
   normal/com foco é `#283d35`; texto selecionado usa marfim sobre verde escuro.
2. **Textos secundários e links:** mediam **4,24:1** e **4,32:1** sobre o fundo
   principal. Os tons foram escurecidos, preservando a paleta verde.
3. **Seleção em campos de texto e numéricos:** removida a dependência das cores
   herdadas do sistema, inclusive quando o campo perde o foco. A lista suspensa
   usa uma paleta explícita e foi inspecionada separadamente da área do campo.
4. **Diálogos:** os padrões do remapeamento e textos dos mods usavam cinzas que
   chegavam a **2,95:1**. Agora usam a cor secundária verificada.
5. **Texto sobre a arte:** o rodapé pequeno da abertura chegava a **2,99:1** no
   tamanho mínimo. Sua cor foi clareada; todos os textos avaliados agora passam
   o limiar aplicável.
6. **Controles:** bordas dos campos e marca de checkbox ganharam contraste.
   A seleção do texto do log também tem cores explícitas.

## Medições após a correção

Referência usada: [WCAG 2.2 — contraste de texto](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html),
**4,5:1 para texto comum** e **3:1 para texto grande**. Para bordas e indicadores,
a referência é [contraste não textual](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html), **3:1**.
Controles desativados são isentos pelo critério, mas também receberam texto legível.
Esta é uma verificação de contraste da UI, não uma certificação integral WCAG.

| Elemento | Cores de texto / fundo | Contraste |
| --- | --- | --- |
| Campos e texto principal nos cartões | `#283d35` / `#f8f5ed` | **10,65:1** |
| Texto secundário no fundo principal | `#536158` / `#eeeae0` | **5,43:1** |
| Links e legendas verdes | `#48644f` / `#eeeae0` | **5,44:1** |
| Seleção de texto nos campos | `#f4f0e4` / `#283d35` | **10,19:1** |
| Item selecionado da lista suspensa | `#f4f0e4` / `#48644f` | **5,74:1** |
| Texto em controle desativado | `#536158` / `#d5d9cc` | **4,54:1** |
| Borda de campo sobre seu fundo | `#7a8477` / `#f8f5ed` | **3,57:1** |
| Menor contraste medido em texto dos diálogos | Cores efetivas dos widgets | **5,41:1** |
| Menor contraste de texto comum sobre a arte | Pixels de fundo sob os limites dos textos | **4,73:1** |
| Menor contraste do título grande sobre a arte | Pixels de fundo sob os limites do título | **3,27:1** |

Os estados normal, foco, readonly, seleção, desativado e suas combinações foram
verificados nos estilos dos campos; botões foram verificados também em hover e
pressionados. A lista suspensa foi consultada em seu próprio widget Tcl.

Na abertura, foi reconstruído o fundo sem texto, usando a arte real e seu
posicionamento no canvas. Foi medida a pior cor de fundo sob cada caixa de texto
em **1040×700, 1240×820 e 1920×1080**, em português e inglês. O título permanece
acima de 18 pontos e foi avaliado com o limiar de 3:1. Os resultados detalhados
estão em [`launcher-ui-audit-results.json`](launcher-ui-audit-results.json).

## Regressão automatizada

**12 testes de UI passaram.** Executar da raiz do repositório:

```powershell
python -m unittest discover -s port/tests -p test_launcher_ui.py -v
```

Os testes usam arquivos temporários em `port/out/`, preservam as configurações do
usuário e não iniciam o jogo, abrem pastas reais nem seguem links externos.
O arquivo de teste registra tanto a paridade histórica quanto o contraste dos
estados que causaram o problema do campo branco.

As alterações de correção limitam-se à apresentação em `tlg_launcher.py`, aos
testes e à documentação desta auditoria. Preparação, execução e persistência
continuam usando a implementação existente.
