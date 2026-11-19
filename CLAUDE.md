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
| `pc/monitor.py` | Script do PC (Python, Windows). OCR com RapidOCR ou Tesseract, captura com mss. Comandos: `conectar`, `setup`, `teste`, `servidor`, `configurar`, `debug`, `imagem`, `autoteste` |
| `pc/instalador/` | Inno Setup (`AlertaRoblox.iss`) + `icone.ico` |
| `pc/requirements.txt` | Dependências do PC (usadas no build do .exe) |
| `supabase/migrations/` | SQL do banco (rodado à mão no SQL Editor) |
| `supabase/functions/send-alert/index.ts` | Edge Function (Deno) que recebe o alerta e envia o push pelo Firebase |
| `app/` | App Android em React Native/Expo SDK 53 (JS, sem TypeScript, sem react-navigation) |
| `.github/workflows/instalador-pc.yml` | Gera `AlertaRoblox-Setup-x.y.z.exe` (Windows, PyInstaller + Inno Setup) |
| `.github/workflows/app-android.yml` | Gera e assina o APK (expo prebuild + gradle + apksigner) |

## Infra (valores públicos, podem ficar no código)
- **Supabase**: projeto `vtyxkowxnesclwtndbog`, URL `https://vtyxkowxnesclwtndbog.supabase.co`, organização `Alerta_Retribution`, plano Free.
- **Chave pública** (publishable): está em `pc/monitor.py` e `app/app.json`.
- **Edge Function publicada com o nome `smooth-responder`** (não `send-alert`; o nome não pode ser trocado). O PC usa `FUNCAO_ALERTA = "smooth-responder"`. "Verify JWT" está DESLIGADO: o PC se autentica pelo cabeçalho `x-chave-pc`.
- **Firebase**: projeto `alerta-fd83a`; app Android `com.octaviokonzen.alerta`; `app/google-services.json` está no repo (não é secreto).
- **Pacote Android**: `com.octaviokonzen.alerta`.

## Segredos (NUNCA colocar no repo nem em mensagens)
- `FIREBASE_SERVICE_ACCOUNT`: segredo da Edge Function no Supabase (JSON da conta de serviço do Firebase).
- `ANDROID_KEYSTORE_PASSWORD`: segredo do GitHub Actions, a senha de `app/release.p12` (alias `alerta`). Sem ela não dá para atualizar o app por cima.
- A chave `sb_secret_...` / service_role do Supabase não é usada fora da Edge Function.

## Banco (Supabase)
Tabelas `pc_keys` (hash da chave do PC), `push_tokens` (token FCM do celular) e `alerts` (histórico, máx. 200 por conta). Todas com RLS: cada usuário vê só o que é dele.
Funções RPC: `criar_chave_pc(p_nome)` (máx. 5 PCs por conta) e `registrar_token(p_token)` (aceita token FCM).
Mudança no banco = criar um novo `supabase/migrations/000N_*.sql` e pedir para o dono rodar no SQL Editor. Não há CLI do Supabase configurada.

## Como publicar mudanças
- **Edge Function**: o dono copia `index.ts` do GitHub (botão "Copy raw file") e cola em Supabase > Edge Functions > smooth-responder > Code > Deploy.
- **APK / .exe**: GitHub > Actions > "App Android (APK)" / "Instalador do PC (Windows)" > Run workflow. Uma tag `v*` gera os dois e anexa na Release.
- O ambiente do Claude não tem rede para Supabase, npm ou pip: valide sintaxe localmente (py_compile; parser do TypeScript) e deixe os builds de verdade para o GitHub Actions.

## Convenções
- Textos de interface e mensagens em português. No `monitor.py`, sem acentos (console do Windows).
- Commits pequenos, em português, direto na `main` (o dono pediu para enviar direto).
- Antes de mexer no formato do alerta, mantenha compatíveis os três lados: `monitor.py` (payload) ↔ `index.ts` (validação/push) ↔ `app/src/telas/Alertas.js` (exibição).

## Estado atual / pendências
- [ ] Dono rodar o SQL `0002_token_firebase.sql` (se ainda não rodou)
- [ ] Criar o segredo `ANDROID_KEYSTORE_PASSWORD` no GitHub
- [ ] Primeiro build dos workflows (APK e .exe). Ainda não foram testados de verdade.
- [ ] Teste ponta a ponta: instalar o APK, criar conta, `conectar` no PC, `teste`
- Ideias futuras: repetir o alarme no celular até abrir; tela de "esqueci a senha"; excluir conta no app; iPhone (exige conta Apple paga).
