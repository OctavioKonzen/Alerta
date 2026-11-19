# Alerta Roblox – contexto para o Claude

Responda sempre em **português do Brasil**, com linguagem simples. O dono (OctavioKonzen) não é programador experiente: dê passos curtos e diga em qual tela/botão clicar.

## O que é
O PC do jogador lê a tela do Roblox (OCR). Quando aparece uma frase configurada, manda um alerta para a nuvem, e a nuvem envia uma notificação push para o app Android do jogador, com:
- o texto da mensagem;
- o nome do jogador;
- o código do servidor (Job ID) e um link para entrar nele.

O app é público e multiusuário: cada pessoa tem conta própria (e-mail/senha), e cada PC só manda alertas para a conta à qual foi ligado.

```
pc/monitor.py --(x-chave-pc)--> Supabase Edge Function --(FCM HTTP v1)--> app Android
```

## Estrutura
| Caminho | O que é |
|---|---|
| `pc/monitor.py` | Programa do PC (Python, Windows). Janela moderna em CustomTkinter (cores do app) + ícone na bandeja (pystray), sem console (PyInstaller `--windowed`). Login do PC pelo Discord (função `discord-bot`, ações `pc_iniciar`/`pc_resultado`). OCR com RapidOCR, captura com mss. Log em `%APPDATA%\AlertaRoblox\alerta.log`. Pelo Python: `debug`, `imagem`, `conectar` (e-mail), `autoteste` |
| `pc/instalador/` | Inno Setup (`AlertaRoblox.iss`) + `icone.ico` |
| `pc/requirements.txt` | Dependências do PC (usadas no build do .exe) |
| `supabase/migrations/` | SQL do banco (rodado à mão no SQL Editor) |
| `supabase/functions/send-alert/index.ts` | Edge Function (Deno) que recebe o alerta e envia o push pelo Firebase e a mensagem nos canais do Discord |
| `supabase/functions/discord-bot/index.ts` | Edge Function do painel do Discord (aba Discord do app): login com Discord, lista servidores em comum com o bot, admin escolhe o canal |
| `app/` | App Android em React Native/Expo SDK 53 (JS, sem TypeScript, sem react-navigation) |
| `.github/workflows/instalador-pc.yml` | Gera `AlertaRoblox-Setup-x.y.z.exe` (Windows, PyInstaller + Inno Setup) |
| `.github/workflows/app-android.yml` | Gera e assina o APK (expo prebuild + gradle + apksigner) |

## Infra (valores públicos, podem ficar no código)
- **Supabase**: projeto `vtyxkowxnesclwtndbog`, URL `https://vtyxkowxnesclwtndbog.supabase.co`, organização `Alerta_Retribution`, plano Free.
- **Chave pública** (publishable): está em `pc/monitor.py` e `app/app.json`.
- **Edge Function publicada com o nome `smooth-responder`** (não `send-alert`; o nome não pode ser trocado). O PC usa `FUNCAO_ALERTA = "smooth-responder"`. "Verify JWT" está DESLIGADO: o PC se autentica pelo cabeçalho `x-chave-pc`.
- **Firebase**: projeto `alerta-fd83a`; app Android `com.octaviokonzen.alerta`; `app/google-services.json` está no repo (não é secreto).
- **Pacote Android**: `com.octaviokonzen.alerta`. Esquema de link do app: `alertaroblox://` (volta do login com Discord).
- **Discord**: um bot so, de todos. Edge Function `discord-bot` (Verify JWT DESLIGADO). Redirect do OAuth2: `https://vtyxkowxnesclwtndbog.supabase.co/functions/v1/discord-bot`.

- **Repositório público** (o dono escolheu). **Atualização automática**: os builds publicam na Release fixa `ultima` deste repositório (script `.github/publicar.sh`, usa o `github.token`): `AlertaRoblox.apk`, `AlertaRoblox-Setup.exe`, `versao-app.json` e `versao-pc.json`. O PC (`VERSAO`, trocada no build) confere a cada 6 h, baixa e instala sozinho (`/VERYSILENT`, o instalador reabre o programa). O app (`src/Atualizacao.js`) compara `versionCode`, baixa o APK e abre o instalador do Android.

## Segredos (NUNCA colocar no repo nem em mensagens)
- `FIREBASE_SERVICE_ACCOUNT`: segredo da Edge Function no Supabase (JSON da conta de serviço do Firebase).
- `ANDROID_KEYSTORE_PASSWORD`: segredo do GitHub Actions, a senha de `app/release.p12` (alias `alerta`). Sem ela não dá para atualizar o app por cima.
- `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_BOT_TOKEN`: segredos das Edge Functions no Supabase (o token do bot e usado pelas duas funcoes).
- A chave `sb_secret_...` / service_role do Supabase não é usada fora da Edge Function.

## Banco (Supabase)
Tabelas `pc_keys` (hash da chave do PC), `push_tokens` (token FCM do celular), `alerts` (histórico, máx. 200 por conta), `discord_contas` (tokens do Discord, só a Edge Function lê), `discord_estados` (login em andamento) e `discord_canais` (canal escolhido por servidor). Todas com RLS: cada usuário vê só o que é dele.
Funções RPC: `criar_chave_pc(p_nome)` (máx. 5 PCs por conta) e `registrar_token(p_token)` (aceita token FCM).
Mudança no banco = criar um novo `supabase/migrations/000N_*.sql` e pedir para o dono rodar no SQL Editor. Não há CLI do Supabase configurada.

## Como publicar mudanças
- **Edge Function**: o dono copia `index.ts` do GitHub (botão "Copy raw file") e cola em Supabase > Edge Functions > smooth-responder > Code > Deploy.
- **APK / .exe**: GitHub > Actions > "App Android (APK)" / "Instalador do PC (Windows)" > Run workflow. Uma tag `v*` gera os dois e anexa na Release.
- O ambiente do Claude não tem rede para Supabase, npm ou pip: valide sintaxe localmente (py_compile; parser do TypeScript) e deixe os builds de verdade para o GitHub Actions.

## Convenções
- Textos de interface e mensagens em português. No `monitor.py`, a janela pode ter acentos; o que vai para o log/console fica sem acento.
- Commits pequenos, em português, direto na `main` (o dono pediu para enviar direto).
- Antes de mexer no formato do alerta, mantenha compatíveis os três lados: `monitor.py` (payload) ↔ `index.ts` (validação/push) ↔ `app/src/telas/Alertas.js` (exibição).

## Estado atual / pendências
- [ ] Dono rodar o SQL `0002_token_firebase.sql` (se ainda não rodou)
- [x] Criar o segredo `ANDROID_KEYSTORE_PASSWORD` no GitHub
- [x] Primeiro build dos workflows (APK 1.0.1 e .exe) deu certo
- [x] Bot do Discord: `0003_discord.sql`, bot criado (app "Tortilha"), segredos no Supabase, `discord-bot` e `smooth-responder` publicadas, APK novo gerado
- [ ] PC com janela + login pelo Discord: rodar `0004_pc_discord.sql`, publicar a `discord-bot` nova, gerar instalador novo
- [ ] Atualização automática: deixar o repositório público e rodar os dois builds (publicam na Release `ultima`)
- [ ] Teste ponta a ponta: instalar o APK, criar conta, `conectar` no PC, `teste`
- Ideias futuras: repetir o alarme no celular até abrir; tela de "esqueci a senha"; excluir conta no app; iPhone (exige conta Apple paga).
