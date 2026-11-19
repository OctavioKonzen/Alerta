# Alerta Roblox

O PC lê a tela do Roblox. Quando aparece uma mensagem configurada, o app **Alerta Roblox** no celular recebe uma notificação com:

- o texto da mensagem;
- o nome do jogador;
- o código do servidor (Job ID), com um botão **Entrar no servidor**.

Cada pessoa tem a própria conta. O PC só manda alertas para a conta à qual foi ligado.

```
PC (monitor.py) --chave do PC--> Supabase (função send-alert) --push--> app no celular
```

| Pasta | O que é |
|---|---|
| `pc/` | Script do PC (Windows + Python) |
| `supabase/` | Banco de dados e a função que dispara as notificações |
| `app/` | App Android (Expo / React Native) |

---

## Parte 1 – Você (dono do projeto), uma vez só

### 1. Supabase (contas + banco + função)
1. Crie um projeto em https://supabase.com (plano grátis).
2. Abra **SQL Editor**, cole o arquivo `supabase/migrations/0001_inicio.sql` e clique em **Run**.
3. Em **Authentication > Sign In / Providers > Email**, deixe *Confirm email* ligado.
4. Publique a função (precisa do [Supabase CLI](https://supabase.com/docs/guides/cli)):
   ```
   supabase login
   supabase link --project-ref SEU_PROJECT_REF
   supabase functions deploy send-alert --no-verify-jwt
   ```
5. Em **Project Settings > API**, copie a **Project URL** e a chave **anon public**.
   Ela é pública por natureza: a segurança fica nas regras do banco (RLS).

### 2. Firebase (só para o Android receber push)
O Android entrega notificações pelo Firebase Cloud Messaging. É grátis.
1. Em https://console.firebase.google.com, crie um projeto e adicione um **app Android** com o pacote `com.seunome.alertaroblox`. Use o mesmo pacote do `app/app.json` e troque `seunome`.
2. Baixe o `google-services.json` e coloque em `app/`.
3. Vá em **Configurações do projeto > Contas de serviço > Gerar nova chave privada** e guarde esse JSON. Ele é **secreto**: não suba para o GitHub.

### 3. Expo / EAS (gera o APK)
```
cd app
npm install
npx expo install --fix        # ajusta as versões das bibliotecas
npm install -g eas-cli
eas login
eas init                      # cria o projeto e mostra o projectId
eas credentials               # Android > Google Service Account > envie o JSON secreto do passo 2.3
```
Edite `app/app.json`:
- `supabaseUrl` e `supabaseAnonKey` → valores do passo 1.5;
- `eas.projectId` → o que o `eas init` mostrou;
- `android.package` → o mesmo pacote do Firebase.

Gere o APK:
```
npm run apk
```
No fim, o EAS mostra um link para baixar o `.apk`.

### 4. GitHub
1. Edite `pc/monitor.py` e preencha `SUPABASE_URL` e `SUPABASE_ANON_KEY`.
2. Suba o repositório.
3. Em **Releases > Draft a new release**, anexe o `.apk` e o `pc/monitor.py`.

---

## Parte 2 – Jogadores

### No celular (Android)
1. Baixe o `.apk` em **Releases**. Se o Android pedir, permita "instalar apps desconhecidos".
2. Abra o app, toque em **Criar conta**, confirme o e-mail e entre.
3. Permita as notificações.

### No PC (Windows)
1. Instale o [Python](https://www.python.org/downloads/) marcando **Add Python to PATH**.
2. No cmd, dentro da pasta do `monitor.py`:
   ```
   pip install opencv-python mss numpy rapidocr onnxruntime
   python monitor.py conectar     (mesmo e-mail e senha do app)
   python monitor.py setup        (arraste sobre a área das mensagens no jogo)
   python monitor.py teste        (deve chegar uma notificação no celular)
   python monitor.py              (começa a monitorar)
   ```
3. Com o Roblox aberto, `python monitor.py servidor` mostra o jogador e o servidor que foram detectados.

### Opções no topo do `monitor.py`
- `MENSAGENS`: as frases procuradas.
- `NOME_JOGADOR`: preencha se o nome não for detectado sozinho.
- `LINK_SERVIDOR_PRIVADO`: se você joga em servidor privado, cole o link aqui. O link de Job ID não funciona para servidor privado.
- `ALERTA_TELA = True`: também pisca a tela do PC (F8 para parar).

---

## Segurança
- A senha **não** fica salva no PC. O `conectar` cria uma chave só para aquele PC, e o banco guarda apenas o hash dela.
- Se remover o PC em **Meus PCs** no app, a chave dele deixa de funcionar na hora.
- Limites: 5 PCs por conta, 6 alertas por minuto, histórico dos últimos 200 alertas.
- Nunca suba para o GitHub: o JSON da conta de serviço do Firebase e o `pc/config.json`, que guarda a chave do PC.
