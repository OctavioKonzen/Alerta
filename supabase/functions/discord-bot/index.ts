// Alerta Roblox - painel do bot do Discord (usado pelo app, aba "Discord").
// - Login com Discord: o app abre o Discord, a pessoa autoriza e volta para o app.
// - Lista os servidores onde a pessoa E o bot estao. Quem e administrador
//   (ou tem "Gerenciar servidor") escolhe o canal que recebe os alertas.
//
// Publicar: Supabase > Edge Functions > Deploy a new function > Via Editor >
//   nome "discord-bot" > cole este arquivo > Deploy.
//   Em Settings da funcao, deixe "Verify JWT" DESLIGADO (o retorno do login vem
//   do navegador, sem login do Supabase; os pedidos do app sao conferidos aqui).
//   Se o Supabase der outro nome para a funcao, troque NOME_FUNCAO abaixo e
//   "funcaoDiscord" em app/app.json.
// Segredos necessarios (Edge Functions > Secrets), do Discord Developer Portal:
//   DISCORD_CLIENT_ID     = OAuth2 > Client ID
//   DISCORD_CLIENT_SECRET = OAuth2 > Client Secret (Reset Secret)
//   DISCORD_BOT_TOKEN     = Bot > Reset Token
//   DISCORD_PUBLIC_KEY    = General Information > Public Key (para o comando /info)
// No Developer Portal > OAuth2 > Redirects, adicione:
//   https://vtyxkowxnesclwtndbog.supabase.co/functions/v1/discord-bot
//
// O site do painel (pasta site/, GitHub Pages) entra com o Discord (web_iniciar) e usa
// o cabecalho "x-sessao-web". O programa do PC tambem usa esta funcao: entra com o Discord (pc_iniciar /
// pc_resultado) e depois usa o painel com o cabecalho "x-chave-pc".

import { createClient } from "jsr:@supabase/supabase-js@2";

const NOME_FUNCAO = "discord-bot";
const VERSAO_BOT = "2026-11-20.8";   // muda a cada publicacao (para saber qual versao esta no ar)
const VOLTAR_APP = "alertaroblox://discord";
const SITE = "https://octaviokonzen.github.io/Alerta/";   // painel do bot (GitHub Pages)
const DIAS_SESSAO_WEB = 30;
const API = "https://discord.com/api/v10";
// Ver canais (1024) + Enviar mensagens (2048) + Inserir links (16384)
const PERMISSOES_BOT = "19456";

function chaveServico(): string {
  const antiga = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (antiga) return antiga;
  try {
    const novas = JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS") ?? "{}");
    return (novas.default ?? Object.values(novas)[0]) as string;
  } catch {
    throw new Error("chave de servico do Supabase nao encontrada");
  }
}
const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const supa = createClient(SUPABASE_URL, chaveServico());
const REDIRECT = `${SUPABASE_URL}/functions/v1/${NOME_FUNCAO}`;

function segredo(nome: string) {
  const v = Deno.env.get(nome);
  if (!v) throw new Error(`segredo ${nome} nao configurado no Supabase`);
  return v.trim();
}
const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type, x-chave-pc, x-sessao-web",
};
function json(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), {
    status, headers: { ...cors, "Content-Type": "application/json" },
  });
}
function voltar(params: Record<string, string>) {
  return new Response(null, {
    status: 302, headers: { Location: `${VOLTAR_APP}?${new URLSearchParams(params)}` },
  });
}
function aleatorio(bytes = 24) {
  return [...crypto.getRandomValues(new Uint8Array(bytes))]
    .map((b) => b.toString(16).padStart(2, "0")).join("");
}
function textoPc(msg: string) {
  return new Response(msg + "\n", { headers: { "Content-Type": "text/plain; charset=utf-8" } });
}
async function sha256(texto: string) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(texto));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
async function donoDoPc(chave: string): Promise<string | null> {
  if (!/^rbx_[0-9a-f]{48}$/.test(chave)) return null;
  const { data } = await supa.from("pc_keys").select("user_id").eq("key_hash", await sha256(chave)).maybeSingle();
  return data?.user_id ?? null;
}
function urlLogin(estado: string, escopo: string) {
  return "https://discord.com/oauth2/authorize?" + new URLSearchParams({
    client_id: segredo("DISCORD_CLIENT_ID"), response_type: "code",
    scope: escopo, redirect_uri: REDIRECT, state: estado,
  });
}
function linkConvite() {
  return `https://discord.com/oauth2/authorize?client_id=${segredo("DISCORD_CLIENT_ID")}` +
    `&scope=bot+applications.commands&permissions=${PERMISSOES_BOT}`;
}

// ---------- Chamadas ao Discord ----------
async function discord(caminho: string, auth: string, opcoes: RequestInit = {}) {
  const r = await fetch(API + caminho, {
    ...opcoes,
    headers: { Authorization: auth, "Content-Type": "application/json", ...(opcoes.headers ?? {}) },
  });
  const corpo = r.status === 204 ? null : await r.json().catch(() => null);
  return { ok: r.ok, status: r.status, corpo };
}
const comoBot = () => `Bot ${segredo("DISCORD_BOT_TOKEN")}`;

async function trocarToken(params: Record<string, string>) {
  const r = await fetch(API + "/oauth2/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: segredo("DISCORD_CLIENT_ID"),
      client_secret: segredo("DISCORD_CLIENT_SECRET"),
      ...params,
    }),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error("Discord recusou o login: " + JSON.stringify(j));
  return j as { access_token: string; refresh_token: string; expires_in: number };
}

// Token do Discord da pessoa (renova sozinho). null = precisa entrar de novo.
async function tokenDaPessoa(userId: string): Promise<{ token: string; nome: string } | null> {
  const { data: c } = await supa.from("discord_contas").select("*").eq("user_id", userId).maybeSingle();
  if (!c) return null;
  if (new Date(c.expira_em).getTime() > Date.now() + 60_000) return { token: c.access_token, nome: c.nome };
  try {
    const t = await trocarToken({ grant_type: "refresh_token", refresh_token: c.refresh_token });
    await supa.from("discord_contas").update({
      access_token: t.access_token, refresh_token: t.refresh_token,
      expira_em: new Date(Date.now() + t.expires_in * 1000).toISOString(),
      updated_at: new Date().toISOString(),
    }).eq("user_id", userId);
    return { token: t.access_token, nome: c.nome };
  } catch (e) {
    console.error(e);
    await supa.from("discord_contas").delete().eq("user_id", userId);
    return null;
  }
}

type Servidor = { id: string; name: string; icon: string | null; owner?: boolean; permissions?: string };
function ehAdmin(g: Servidor) {
  const p = BigInt(g.permissions ?? "0");
  return !!g.owner || (p & 0x8n) !== 0n || (p & 0x20n) !== 0n; // Administrador ou Gerenciar servidor
}
async function servidoresEmComum(tokenPessoa: string) {
  const [daPessoa, doBot] = await Promise.all([
    discord("/users/@me/guilds", `Bearer ${tokenPessoa}`),
    discord("/users/@me/guilds", comoBot()),
  ]);
  if (!daPessoa.ok) throw new Error("nao consegui ler seus servidores do Discord");
  if (!doBot.ok) throw new Error("token do bot invalido (DISCORD_BOT_TOKEN)");
  const ids = new Set((doBot.corpo as Servidor[]).map((g) => g.id));
  return (daPessoa.corpo as Servidor[]).filter((g) => ids.has(g.id));
}
async function servidorComoAdmin(tokenPessoa: string, guildId: string) {
  const g = (await servidoresEmComum(tokenPessoa)).find((x) => x.id === guildId);
  if (!g) throw new Error("o bot nao esta nesse servidor (ou voce nao esta)");
  if (!ehAdmin(g)) throw new Error("so administradores do servidor podem configurar o bot");
  return g;
}
async function canaisDeTexto(guildId: string) {
  const r = await discord(`/guilds/${guildId}/channels`, comoBot());
  if (!r.ok) throw new Error("o bot nao consegue ver os canais desse servidor");
  return (r.corpo as { id: string; name: string; type: number; position: number }[])
    .filter((c) => c.type === 0 || c.type === 5)
    .sort((a, b) => a.position - b.position)
    .map((c) => ({ id: c.id, nome: c.name }));
}

// Bots novos precisam se conectar ao Gateway uma vez antes de mandar mensagens.
let gatewayFeito = false;
function conectarGatewayUmaVez(): Promise<void> {
  if (gatewayFeito) return Promise.resolve();
  return new Promise((ok) => {
    const ws = new WebSocket("wss://gateway.discord.gg/?v=10&encoding=json");
    const fim = () => { try { ws.close(); } catch { /* */ } ok(); };
    const limite = setTimeout(fim, 6000);
    ws.onmessage = (ev) => {
      const m = JSON.parse(String(ev.data));
      if (m.op === 10) {
        ws.send(JSON.stringify({
          op: 2,
          d: {
            token: segredo("DISCORD_BOT_TOKEN"), intents: 0,
            properties: { os: "linux", browser: "alerta-roblox", device: "alerta-roblox" },
          },
        }));
      } else if (m.op === 0 && m.t === "READY") {
        gatewayFeito = true; clearTimeout(limite); fim();
      }
    };
    ws.onerror = () => { clearTimeout(limite); fim(); };
  });
}

// ---------- Acoes do app ----------
async function acao(userId: string, corpo: Record<string, unknown>) {
  const qual = String(corpo.acao ?? "");

  if (qual === "iniciar") {
    const estado = aleatorio();
    await supa.from("discord_estados").delete().lt("expira_em", new Date().toISOString());
    await supa.from("discord_estados").insert({
      estado, user_id: userId, expira_em: new Date(Date.now() + 10 * 60_000).toISOString(),
    });
    return { url: urlLogin(estado, "identify guilds") };
  }

  // Frases procuradas pelo PC (ficam na conta)
  if (qual === "frases") {
    // Os PCs pedem as frases a cada 1 minuto: aproveita para manter o Trello do /info em dia
    // (so baixa de novo se a copia tiver mais de 30 minutos).
    await atualizarTrello().catch((e) => console.error("trello:", e));
    await supa.rpc("garantir_frases", { p_user: userId });
    const { data } = await supa.from("frases").select("id, texto")
      .eq("user_id", userId).order("created_at").order("id");
    return { frases: data ?? [] };
  }
  if (qual === "frase_add") {
    const texto = String(corpo.texto ?? "").trim();
    if (texto.length < 3 || texto.length > 120) throw new Error("a frase precisa ter de 3 a 120 letras");
    const { error } = await supa.from("frases").insert({ user_id: userId, texto });
    if (error) throw new Error(error.message.includes("limite") ? "limite de 30 frases por conta" : "nao consegui salvar a frase");
    return { ok: true };
  }
  if (qual === "frase_del") {
    await supa.from("frases").delete().eq("user_id", userId).eq("id", String(corpo.id));
    return { ok: true };
  }

  if (qual === "sair") {
    await supa.from("discord_participantes").delete().eq("user_id", userId);
    await supa.from("discord_canais").delete().eq("user_id", userId);
    await supa.from("discord_contas").delete().eq("user_id", userId);
    return { ok: true };
  }

  // Parar de mandar os MEUS alertas neste servidor (qualquer membro)
  if (qual === "remover") {
    await supa.from("discord_participantes").delete().eq("user_id", userId).eq("guild_id", String(corpo.guild_id));
    await supa.from("discord_canais").delete().eq("user_id", userId).eq("guild_id", String(corpo.guild_id));
    return { ok: true };
  }

  const pessoa = await tokenDaPessoa(userId);
  if (!pessoa) return { conectado: false, convite: linkConvite() };

  if (qual === "painel") {
    const servidores = await servidoresEmComum(pessoa.token);
    const ids = servidores.map((g) => g.id);
    const [{ data: configs }, { data: meus }, { data: infos }] = await Promise.all([
      supa.from("discord_servidores").select("guild_id, channel_id, canal_nome").in("guild_id", ids.length ? ids : ["-"]),
      supa.from("discord_participantes").select("guild_id").eq("user_id", userId),
      supa.from("discord_info_canal").select("guild_id, channel_id, canal_nome").in("guild_id", ids.length ? ids : ["-"]),
    ]);
    const infoDe = new Map((infos ?? []).map((c) => [c.guild_id, c]));
    const canalDe = new Map((configs ?? []).map((c) => [c.guild_id, c]));
    const participo = new Set((meus ?? []).map((m) => m.guild_id));
    return {
      conectado: true, nome: pessoa.nome, convite: linkConvite(),
      servidores: servidores.map((g) => {
        const c = canalDe.get(g.id);
        return {
          id: g.id, nome: g.name, admin: ehAdmin(g),
          icone: g.icon ? `https://cdn.discordapp.com/icons/${g.id}/${g.icon}.png?size=64` : null,
          canal: c ? { id: c.channel_id, nome: c.canal_nome } : null,   // canal do servidor (do admin)
          participando: participo.has(g.id),                            // meus alertas vao para la?
          info_canal: infoDe.has(g.id)                                  // canal do /info (null = qualquer canal)
            ? { id: infoDe.get(g.id)!.channel_id, nome: infoDe.get(g.id)!.canal_nome } : null,
        };
      }),
    };
  }

  // Mandar os MEUS alertas para o canal deste servidor (qualquer membro; o admin escolhe o canal)
  if (qual === "participar") {
    const guildId = String(corpo.guild_id);
    const g = (await servidoresEmComum(pessoa.token)).find((x) => x.id === guildId);
    if (!g) throw new Error("o bot nao esta nesse servidor (ou voce nao esta)");
    const { data: cfg } = await supa.from("discord_servidores").select("canal_nome").eq("guild_id", guildId).maybeSingle();
    if (!cfg) throw new Error("um administrador deste servidor ainda nao escolheu o canal dos alertas");
    await supa.from("discord_participantes").upsert({ user_id: userId, guild_id: guildId }, { onConflict: "user_id,guild_id" });
    return { ok: true, canal: cfg.canal_nome };
  }

  // Mandar os MEUS alertas em todos os servidores que ja tem canal
  if (qual === "participar_todos") {
    const ids = (await servidoresEmComum(pessoa.token)).map((g) => g.id);
    const { data: cfgs } = await supa.from("discord_servidores").select("guild_id").in("guild_id", ids.length ? ids : ["-"]);
    const linhas = (cfgs ?? []).map((c) => ({ user_id: userId, guild_id: c.guild_id }));
    if (linhas.length) await supa.from("discord_participantes").upsert(linhas, { onConflict: "user_id,guild_id" });
    return { ok: true, total: linhas.length };
  }

  // Diagnostico do /info (botao do site): mede cada etapa
  if (qual === "info_diagnostico") {
    const linhas: string[] = [];
    const medir = async (nome: string, f: () => Promise<string>) => {
      const t0 = performance.now();
      try { linhas.push(`${nome}: ${await f()} (${Math.round(performance.now() - t0)} ms)`); }
      catch (e) { linhas.push(`${nome}: ERRO ${e instanceof Error ? e.message : String(e)} (${Math.round(performance.now() - t0)} ms)`); }
    };
    await medir("chave publica", async () => {
      const b = hexBytes(segredo("DISCORD_PUBLIC_KEY"));
      return b ? `ok (${b.length} bytes)` : "INVALIDA";
    });
    await medir("Ed25519 nativo", async () => {
      const b = hexBytes(segredo("DISCORD_PUBLIC_KEY"))!;
      const k = await crypto.subtle.importKey("raw", b, { name: "Ed25519" }, false, ["verify"]);
      await crypto.subtle.verify({ name: "Ed25519" }, k, new Uint8Array(64), new Uint8Array(1));
      return "funciona";
    });
    await medir("secoes no banco", async () => {
      const { count, error } = await supa.from("trello_listas").select("id", { count: "exact", head: true });
      if (error) throw new Error(error.message);
      return String(count);
    });
    await medir("menu de secoes", async () => `${(await menuSecoes()).components.length} menus`);
    await medir("sugestoes", async () => {
      const r = await sugestoes({ data: { options: [{ name: "secao", value: "Ma", focused: true }] } });
      const j = await r.json();
      return `${j.data?.choices?.length ?? 0} opcoes`;
    });
    return { ok: true, texto: linhas.join(" | ") };
  }

  // Carregar o Trello agora (botao do site): mostra o resultado ou o erro exato
  if (qual === "trello_atualizar") {
    await supa.from("trello_estado").upsert({ id: 1, atualizando_desde: null });
    await atualizarTrello(true);
    const [{ count: secoes }, { count: itens }] = await Promise.all([
      supa.from("trello_listas").select("id", { count: "exact", head: true }),
      supa.from("trello_cartoes").select("id", { count: "exact", head: true }),
    ]);
    return { ok: true, secoes: secoes ?? 0, itens: itens ?? 0 };
  }

  // Canal onde o comando /info funciona (so administrador; channel_id vazio = qualquer canal)
  if (qual === "info_canal") {
    const guildId = String(corpo.guild_id);
    await servidorComoAdmin(pessoa.token, guildId);
    if (!corpo.channel_id) {
      await supa.from("discord_info_canal").delete().eq("guild_id", guildId);
      return { ok: true };
    }
    const canal = (await canaisDeTexto(guildId)).find((c) => c.id === String(corpo.channel_id));
    if (!canal) throw new Error("canal nao encontrado");
    await supa.from("discord_info_canal").upsert({
      guild_id: guildId, channel_id: canal.id, canal_nome: canal.nome.slice(0, 100), updated_at: new Date().toISOString(),
    });
    return { ok: true };
  }

  // Desligar o canal do servidor: para os alertas de TODOS (so administrador)
  if (qual === "desligar") {
    const guildId = String(corpo.guild_id);
    await servidorComoAdmin(pessoa.token, guildId);
    await supa.from("discord_servidores").delete().eq("guild_id", guildId);   // participantes saem junto
    await supa.from("discord_canais").delete().eq("guild_id", guildId);
    return { ok: true };
  }

  if (qual === "canais") {
    await servidorComoAdmin(pessoa.token, String(corpo.guild_id));
    return { canais: await canaisDeTexto(String(corpo.guild_id)) };
  }

  if (qual === "escolher") {
    const guildId = String(corpo.guild_id), channelId = String(corpo.channel_id);
    const g = await servidorComoAdmin(pessoa.token, guildId);
    const canal = (await canaisDeTexto(guildId)).find((c) => c.id === channelId);
    if (!canal) throw new Error("canal nao encontrado");

    await conectarGatewayUmaVez();
    const teste = await discord(`/channels/${channelId}/messages`, comoBot(), {
      method: "POST",
      body: JSON.stringify({
        content: `✅ Este canal vai receber os alertas do **Alerta Roblox** deste servidor ` +
          `(escolhido por ${pessoa.nome ?? "um administrador"}). Cada membro pode mandar os seus pelo painel.`,
        allowed_mentions: { parse: [] },
      }),
    });
    if (!teste.ok) {
      console.error("teste falhou", teste.status, JSON.stringify(teste.corpo));
      throw new Error("o bot nao consegue mandar mensagem em #" + canal.nome +
        ". Nas permissoes do canal, deixe o bot Ver canal, Enviar mensagens e Inserir links.");
    }
    const { error: erroSalvar } = await supa.from("discord_servidores").upsert({
      guild_id: guildId, guild_nome: g.name.slice(0, 100), channel_id: channelId,
      canal_nome: canal.nome.slice(0, 100), configurado_por: userId, updated_at: new Date().toISOString(),
    }, { onConflict: "guild_id" });
    if (erroSalvar) {
      console.error(erroSalvar);
      throw new Error("nao consegui salvar o canal (o SQL 0009 ja foi rodado no Supabase?)");
    }
    await supa.from("discord_participantes").upsert({ user_id: userId, guild_id: guildId }, { onConflict: "user_id,guild_id" });
    return { ok: true };
  }

  return { erro: "acao desconhecida" };
}

// ---------- Login do programa do PC ----------
// pcUserId: dono do PC, quando o PC ja tem chave (so renova o login do Discord).
async function pcIniciar(corpo: Record<string, unknown>, pcUserId: string | null) {
  const estado = aleatorio();
  await supa.from("discord_estados").delete().lt("expira_em", new Date().toISOString());
  const nome = typeof corpo.nome_pc === "string" && corpo.nome_pc.trim()
    ? corpo.nome_pc.trim().slice(0, 40) : "PC";
  await supa.from("discord_estados").insert({
    estado, user_id: pcUserId, tipo: pcUserId ? "pc_renovar" : "pc", nome_pc: nome,
    expira_em: new Date(Date.now() + 10 * 60_000).toISOString(),
  });
  return { url: urlLogin(estado, "identify guilds"), estado };
}

async function pcResultado(estado: string) {
  const { data: p } = await supa.from("discord_estados").select("*")
    .eq("estado", estado).like("tipo", "pc%").maybeSingle();
  if (!p || new Date(p.expira_em) < new Date()) return { pronto: true, erro: "tempo esgotado, tente de novo" };
  if (!p.pronto) return { pronto: false };
  await supa.from("discord_estados").delete().eq("estado", estado);
  return p.erro ? { pronto: true, erro: p.erro } : { pronto: true, chave: p.chave_pc };
}

async function retornoLoginPc(pedido: Record<string, any>, u: { id: string; nome: string }, t: TokensDiscord) {
  const falhar = async (erro: string) => {
    await supa.from("discord_estados").update({ pronto: true, erro }).eq("estado", pedido.estado);
    return textoPc("Nao deu certo: " + erro);
  };
  const userId: string = pedido.tipo === "pc" ? await usuarioDoDiscord(u) : pedido.user_id;
  await salvarTokens(userId, u, t);

  let chave: string | null = null;
  if (pedido.tipo === "pc") {
    const { count } = await supa.from("pc_keys").select("id", { count: "exact", head: true }).eq("user_id", userId);
    if ((count ?? 0) >= 5) return await falhar("limite de 5 PCs por conta. Remova um PC no app (aba Meus PCs).");
    chave = "rbx_" + aleatorio(24);
    const { error } = await supa.from("pc_keys").insert({
      user_id: userId, nome: pedido.nome_pc || "PC", key_hash: await sha256(chave), prefixo: chave.slice(0, 10),
    });
    if (error) { console.error(error); return await falhar("erro ao criar a chave do PC"); }
  }
  await supa.from("discord_estados").update({ pronto: true, chave_pc: chave }).eq("estado", pedido.estado);
  return textoPc("Pronto! Pode fechar esta aba e voltar para o Alerta Roblox.");
}

type TokensDiscord = { access_token: string; refresh_token: string; expires_in: number };

// Conta do sistema para este Discord. Se ainda nao existe, cria na hora
// (entrar com Discord = ter conta, igual aos paineis de bots).
async function usuarioDoDiscord(u: { id: string; nome: string }): Promise<string> {
  const { data: conta } = await supa.from("discord_contas").select("user_id")
    .eq("discord_id", u.id).order("updated_at", { ascending: false }).limit(1).maybeSingle();
  if (conta) return conta.user_id;
  const email = `discord_${u.id}@discord.alertaroblox`;
  const { data, error } = await supa.auth.admin.createUser({
    email, email_confirm: true, user_metadata: { discord_id: u.id, nome: u.nome, via: "discord" },
  });
  if (data?.user) return data.user.id;
  const { data: id } = await supa.rpc("usuario_por_email", { p_email: email });   // ja criada antes
  if (id) return id as string;
  throw new Error("nao consegui criar a conta: " + (error?.message ?? "erro desconhecido"));
}
async function salvarTokens(userId: string, u: { id: string; nome: string }, t: TokensDiscord) {
  await supa.from("discord_contas").upsert({
    user_id: userId, discord_id: u.id, nome: u.nome,
    access_token: t.access_token, refresh_token: t.refresh_token,
    expira_em: new Date(Date.now() + t.expires_in * 1000).toISOString(),
    updated_at: new Date().toISOString(),
  });
}

// ---------- Site do painel (login com Discord) ----------
function voltarSite(params: Record<string, string>) {
  return new Response(null, { status: 302, headers: { Location: `${SITE}#${new URLSearchParams(params)}` } });
}
async function webIniciar() {
  const estado = aleatorio();
  await supa.from("discord_estados").delete().lt("expira_em", new Date().toISOString());
  await supa.from("discord_estados").insert({
    estado, user_id: null, tipo: "web", expira_em: new Date(Date.now() + 10 * 60_000).toISOString(),
  });
  return { url: urlLogin(estado, "identify guilds") };
}
async function donoDaSessao(token: string): Promise<string | null> {
  if (!/^web_[0-9a-f]{64}$/.test(token)) return null;
  const { data } = await supa.from("sessoes_web").select("user_id, expira_em")
    .eq("token_hash", await sha256(token)).maybeSingle();
  if (!data || new Date(data.expira_em) < new Date()) return null;
  return data.user_id;
}
async function retornoLoginWeb(u: { id: string; nome: string }, t: TokensDiscord) {
  const userId = await usuarioDoDiscord(u);
  await salvarTokens(userId, u, t);
  const token = "web_" + aleatorio(32);
  await supa.from("sessoes_web").delete().lt("expira_em", new Date().toISOString());
  await supa.from("sessoes_web").insert({
    token_hash: await sha256(token), user_id: userId,
    expira_em: new Date(Date.now() + DIAS_SESSAO_WEB * 86_400_000).toISOString(),
  });
  return voltarSite({ sessao: token });
}

// ---------- Login do app do celular com Discord ----------
const VOLTAR_LOGIN_APP = "alertaroblox://login";
function voltarLoginApp(params: Record<string, string>) {
  return new Response(null, { status: 302, headers: { Location: `${VOLTAR_LOGIN_APP}?${new URLSearchParams(params)}` } });
}
async function appLoginIniciar() {
  const estado = aleatorio();
  await supa.from("discord_estados").delete().lt("expira_em", new Date().toISOString());
  await supa.from("discord_estados").insert({
    estado, user_id: null, tipo: "app_login", expira_em: new Date(Date.now() + 10 * 60_000).toISOString(),
  });
  return { url: urlLogin(estado, "identify guilds") };
}
// Entra (ou cria a conta) e devolve ao app um codigo de uso unico para abrir a sessao.
async function retornoLoginApp(u: { id: string; nome: string }, t: TokensDiscord) {
  const userId = await usuarioDoDiscord(u);
  await salvarTokens(userId, u, t);
  const { data: quem } = await supa.auth.admin.getUserById(userId);
  const email = quem?.user?.email;
  if (!email) throw new Error("conta sem e-mail");
  const { data: link, error } = await supa.auth.admin.generateLink({ type: "magiclink", email });
  const hash = link?.properties?.hashed_token;
  if (!hash) throw new Error("nao consegui abrir a sessao: " + (error?.message ?? ""));
  return voltarLoginApp({ token_hash: hash });
}

// ---------- Retorno do login com Discord (vem do navegador) ----------
async function retornoLogin(url: URL) {
  const estado = url.searchParams.get("state") ?? "";
  const code = url.searchParams.get("code");
  if (!code) {
    const { data: p } = await supa.from("discord_estados").select("tipo").eq("estado", estado).maybeSingle();
    if (String(p?.tipo ?? "").startsWith("pc")) {
      await supa.from("discord_estados").update({ pronto: true, erro: "login cancelado" }).eq("estado", estado);
      return textoPc("Login cancelado. Pode fechar esta aba.");
    }
    if (p?.tipo === "web") return voltarSite({ erro: "Login cancelado." });
    if (p?.tipo === "app_login") return voltarLoginApp({ erro: "Login cancelado." });
    return voltar({ erro: "login cancelado" });
  }

  const { data: pedido } = await supa.from("discord_estados").select("*")
    .eq("estado", estado).maybeSingle();
  const doPc = String(pedido?.tipo ?? "").startsWith("pc");
  const doSite = pedido?.tipo === "web";
  const doLoginApp = pedido?.tipo === "app_login";
  if (!pedido || new Date(pedido.expira_em) < new Date()) {
    if (doSite) return voltarSite({ erro: "Pedido expirado, tente de novo." });
    if (doLoginApp) return voltarLoginApp({ erro: "Pedido expirado, tente de novo." });
    return doPc ? textoPc("Pedido expirado. Tente de novo no PC.") : voltar({ erro: "pedido expirado, tente de novo" });
  }
  if (!doPc) await supa.from("discord_estados").delete().eq("estado", estado);

  try {
    const t = await trocarToken({ grant_type: "authorization_code", code, redirect_uri: REDIRECT });
    const eu = await discord("/users/@me", `Bearer ${t.access_token}`);
    if (!eu.ok) throw new Error("nao consegui ler sua conta do Discord");
    const bruto = eu.corpo as { id: string; username: string; global_name?: string };
    const u = { id: bruto.id, nome: (bruto.global_name || bruto.username).slice(0, 60) };
    if (doPc) return await retornoLoginPc(pedido, u, t);
    if (doSite) return await retornoLoginWeb(u, t);
    if (doLoginApp) return await retornoLoginApp(u, t);
    await salvarTokens(pedido.user_id, u, t);
    return voltar({ ok: "1" });
  } catch (e) {
    console.error(e);
    if (doPc) {
      await supa.from("discord_estados").update({ pronto: true, erro: "falha no login com Discord" }).eq("estado", estado);
      return textoPc("Falha no login com Discord. Tente de novo no PC.");
    }
    if (doSite) return voltarSite({ erro: "Falha no login com Discord. Tente de novo." });
    if (doLoginApp) return voltarLoginApp({ erro: "Falha no login com Discord. Tente de novo." });
    return voltar({ erro: "falha no login com Discord" });
  }
}

// ======================================================================
// Comando /info no Discord: informacoes do Trello do Clover Retribution
// ======================================================================
// O Discord manda os comandos para esta funcao (Developer Portal > General
// Information > "Interactions Endpoint URL" = endereco desta funcao).
// Precisa do segredo DISCORD_PUBLIC_KEY (General Information > Public Key).
// Os dados do Trello ficam copiados no banco (trello_listas / trello_cartoes)
// e sao atualizados sozinhos a cada 30 minutos. Nenhum link do Trello e mostrado.

const TRELLO_QUADRO = "xKxR061L";
const TRELLO_ATUALIZAR_MIN = 30;
const COR_INFO = 0x2ecc71;

// deno-lint-ignore no-explicit-any
const EdgeRT = (globalThis as any).EdgeRuntime as { waitUntil?: (p: Promise<unknown>) => void } | undefined;
function emSegundoPlano(p: Promise<unknown>) {
  const seguro = p.catch((e) => console.error("segundo plano:", e));
  if (EdgeRT?.waitUntil) EdgeRT.waitUntil(seguro);
}

const COMANDOS = [{
  name: "info",
  description: "Informacoes do Clover Retribution: digite /info e aperte Enter",
  contexts: [0], integration_types: [0],
  options: [
    { type: 3, name: "secao", description: "Opcional: secao (ex.: Weapons, Races, Magics)", required: false, autocomplete: true },
    { type: 3, name: "item", description: "Opcional: o item (se escolher, ja mostra no chat)", required: false, autocomplete: true },
  ],
}];

async function registrarComandos(appId: string) {
  const r = await fetch(`${API}/applications/${appId}/commands`, {
    method: "PUT",
    headers: { Authorization: comoBot(), "Content-Type": "application/json" },
    body: JSON.stringify(COMANDOS),
  });
  if (!r.ok) console.error("falha ao registrar comandos", r.status, await r.text());
}

// ---------- assinatura dos pedidos do Discord (Ed25519) ----------
function hexBytes(hex: string) {
  const h = hex.trim();
  if (!/^([0-9a-f]{2})+$/i.test(h)) return null;
  return Uint8Array.from(h.match(/../g)!.map((x) => parseInt(x, 16)));
}
let chavePublicaDiscord: CryptoKey | null = null;
async function assinaturaDiscordValida(req: Request, corpo: string) {
  const assinatura = hexBytes(req.headers.get("x-signature-ed25519") ?? "");
  const hora = req.headers.get("x-signature-timestamp") ?? "";
  if (!assinatura || !hora) return false;
  const bytes = hexBytes(segredo("DISCORD_PUBLIC_KEY"));
  if (!bytes) throw new Error("DISCORD_PUBLIC_KEY invalida");
  const mensagem = new TextEncoder().encode(hora + corpo);
  try {
    if (!chavePublicaDiscord) {
      chavePublicaDiscord = await crypto.subtle.importKey("raw", bytes, { name: "Ed25519" }, false, ["verify"]);
    }
    return await crypto.subtle.verify({ name: "Ed25519" }, chavePublicaDiscord, assinatura, mensagem);
  } catch {
    // plano B, se o ambiente nao tiver Ed25519 no WebCrypto
    // deno-lint-ignore no-explicit-any
    const nacl: any = (await import("npm:tweetnacl@1.0.3")).default;
    return nacl.sign.detached.verify(mensagem, assinatura, bytes);
  }
}

// ---------- copia do Trello ----------
type CartaoTrello = {
  id: string; name: string; desc?: string; idList: string; pos?: number; shortLink?: string;
  labels?: { name?: string; color?: string }[];
  attachments?: { url?: string; mimeType?: string; pos?: number }[];
};

// Deixa o texto do Trello do jeito do Discord e tira todos os links do Trello.
function converterTexto(desc: string, nomePorLink: Map<string, string>) {
  let t = desc ?? "";
  // [qualquer](https://trello.com/c/ABC/...) -> **Nome do cartao**
  t = t.replace(/\[([^\]]*)\]\((https?:\/\/trello\.com\/c\/([A-Za-z0-9]+)[^)\s]*)(?:\s+"[^"]*")?\)/g,
    (_m, texto: string, _url: string, curto: string) => {
      const nome = nomePorLink.get(curto);
      const visivel = texto && !/^https?:\/\//.test(texto) ? texto : (nome ?? "");
      return visivel ? `**${visivel.replace(/\*/g, "")}**` : "";
    });
  // imagens embutidas do Trello e outros links do Trello: some o link, fica o texto
  t = t.replace(/!\[[^\]]*\]\(https?:\/\/[^)]*trello[^)]*\)/g, "");
  t = t.replace(/\[([^\]]*)\]\(https?:\/\/[^)]*trello\.com[^)]*\)/g, "$1");
  t = t.replace(/https?:\/\/(?:[a-z0-9-]+\.)*trello\.com\/c\/([A-Za-z0-9]+)\S*/g,
    (_m, curto: string) => (nomePorLink.has(curto) ? `**${nomePorLink.get(curto)}**` : ""));
  t = t.replace(/https?:\/\/(?:[a-z0-9-]+\.)*trello\.com\S*/g, "");
  // escapes do Trello que o Discord mostraria com barra (\+5 CON -> +5 CON)
  t = t.replace(/\\([+\-.!#()\[\]>=])/g, "$1");
  // linha "---" do Trello vira um separador visivel
  t = t.replace(/^\s*-{3,}\s*$/gm, "──────────");
  t = t.replace(/\n{3,}/g, "\n\n").trim();
  return t;
}

// Raridade marcada como etiqueta colorida no Trello (ex.: "Mythic", "Unobtainable")
const RARIDADES = ["Common", "Uncommon", "Rare", "Epic", "Legendary", "Mythic", "Divine", "Secret", "Exotic", "Unobtainable"];
function raridadeDaEtiqueta(labels: { name?: string }[]) {
  for (const r of RARIDADES) {
    if (labels.some((l) => (l.name ?? "").trim().toLowerCase() === r.toLowerCase())) return r;
  }
  return null;
}

async function atualizarTrello(forcar = false) {
  const { data: est } = await supa.from("trello_estado").select("*").eq("id", 1).maybeSingle();
  const agora = Date.now();
  if (!forcar && est?.atualizado_em && agora - new Date(est.atualizado_em).getTime() < TRELLO_ATUALIZAR_MIN * 60_000) return;
  if (est?.atualizando_desde && agora - new Date(est.atualizando_desde).getTime() < 3 * 60_000) return;   // ja tem outra
  const { error: erroEstado } = await supa.from("trello_estado").upsert({ id: 1, atualizando_desde: new Date().toISOString() });
  if (erroEstado) throw new Error("tabela trello_estado: " + erroEstado.message + " (o SQL 0012 foi rodado?)");
  try {
    const url = `https://api.trello.com/1/boards/${TRELLO_QUADRO}?fields=name&lists=open&list_fields=name,pos` +
      `&cards=open&card_fields=name,desc,idList,pos,shortLink,labels&card_attachments=true&card_attachment_fields=url,mimeType,pos`;
    const r = await fetch(url);
    if (!r.ok) throw new Error(`Trello respondeu ${r.status}`);
    const quadro = await r.json() as { lists: { id: string; name: string; pos: number }[]; cards: CartaoTrello[] };
    const nomePorLink = new Map(quadro.cards.filter((c) => c.shortLink).map((c) => [c.shortLink!, c.name]));
    const listas = quadro.lists.map((l) => ({ id: l.id, nome: l.name.trim(), pos: l.pos }));
    const cartoes = quadro.cards.map((c) => ({
      id: c.id, id_lista: c.idList, nome: c.name.trim(), pos: c.pos ?? 0, short_link: c.shortLink ?? null,
      raridade: raridadeDaEtiqueta(c.labels ?? []),
      texto: converterTexto(c.desc ?? "", nomePorLink),
      imagens: (c.attachments ?? [])
        .filter((a) => (a.mimeType ?? "").startsWith("image/") && a.url)
        .sort((a, b) => (a.pos ?? 0) - (b.pos ?? 0)).slice(0, 4).map((a) => a.url),
    }));
    const { error: erroListas } = await supa.from("trello_listas").upsert(listas);
    if (erroListas) throw new Error("salvar secoes: " + erroListas.message);
    let semRaridade = false;
    for (let i = 0; i < cartoes.length; i += 200) {
      let lote: Record<string, unknown>[] = cartoes.slice(i, i + 200);
      if (semRaridade) lote = lote.map(({ raridade: _r, ...resto }) => resto);
      let { error } = await supa.from("trello_cartoes").upsert(lote);
      if (error && /raridade/.test(error.message) && !semRaridade) {   // SQL 0013 ainda nao rodado
        semRaridade = true;
        ({ error } = await supa.from("trello_cartoes").upsert(lote.map(({ raridade: _r, ...resto }) => resto)));
      }
      if (error) throw new Error("salvar cartoes: " + error.message);
    }
    // tira o que saiu do Trello
    const idsListas = listas.map((l) => l.id), idsCartoes = new Set(cartoes.map((c) => c.id));
    await supa.from("trello_listas").delete().not("id", "in", `(${idsListas.map((x) => `"${x}"`).join(",") || '""'})`);
    const antigos: string[] = [];
    for (let de = 0; de < 20000; de += 1000) {
      const { data } = await supa.from("trello_cartoes").select("id").order("id").range(de, de + 999);
      for (const a of data ?? []) antigos.push(a.id);
      if (!data || data.length < 1000) break;
    }
    const sobra = antigos.filter((id) => !idsCartoes.has(id));
    for (let i = 0; i < sobra.length; i += 200) await supa.from("trello_cartoes").delete().in("id", sobra.slice(i, i + 200));
    await supa.from("trello_estado").upsert({ id: 1, atualizado_em: new Date().toISOString(), atualizando_desde: null });
    console.log(`Trello atualizado: ${listas.length} secoes, ${cartoes.length} cartoes`);
  } catch (e) {
    await supa.from("trello_estado").upsert({ id: 1, atualizando_desde: null });
    throw e;
  }
}

// ---------- respostas do comando ----------
function opcoes(i: Record<string, any>) {
  const lista = (i.data?.options ?? []) as { name: string; value?: string; focused?: boolean }[];
  const o: Record<string, string> = {};
  let foco = "";
  for (const x of lista) { o[x.name] = String(x.value ?? ""); if (x.focused) foco = x.name; }
  return { o, foco };
}
const limpa = (s: string) => s.replace(/[%_,()"\\]/g, " ").trim();

async function sugestoes(i: Record<string, any>) {
  const { o, foco } = opcoes(i);
  let escolhas: { name: string; value: string }[] = [];
  if (foco === "secao") {
    let q = supa.from("trello_listas").select("id, nome").order("pos").limit(25);
    if (limpa(o.secao)) q = q.ilike("nome", `%${limpa(o.secao)}%`);
    const { data } = await q;
    escolhas = (data ?? []).map((l) => ({ name: l.nome.slice(0, 100), value: l.id }));
  } else {
    let q = supa.from("trello_cartoes").select("id, nome").order("pos").limit(25);
    if (/^[0-9a-f]{24}$/.test(o.secao ?? "")) q = q.eq("id_lista", o.secao);
    else if (limpa(o.secao ?? "")) {
      const { data: ls } = await supa.from("trello_listas").select("id").ilike("nome", `%${limpa(o.secao)}%`).limit(5);
      if (ls?.length) q = q.in("id_lista", ls.map((l) => l.id));
    }
    if (limpa(o.item ?? "")) q = q.ilike("nome", `%${limpa(o.item)}%`);
    const { data } = await q;
    escolhas = (data ?? []).map((c) => ({ name: c.nome.slice(0, 100), value: c.id }));
  }
  return json({ type: 8, data: { choices: escolhas } });
}

function partes(texto: string, max = 3900) {
  const saida: string[] = [];
  let resto = texto;
  while (resto.length > max) {
    let corte = resto.lastIndexOf("\n", max);
    if (corte < max * 0.5) corte = max;
    saida.push(resto.slice(0, corte));
    resto = resto.slice(corte).trimStart();
  }
  if (resto) saida.push(resto);
  return saida;
}

// O banco entrega no maximo 1000 linhas por consulta: le em partes.
async function todosOsIdsDeLista(): Promise<string[]> {
  const ids: string[] = [];
  for (let de = 0; de < 20000; de += 1000) {
    const { data, error } = await supa.from("trello_cartoes").select("id_lista").order("id").range(de, de + 999);
    if (error) throw new Error(error.message);
    for (const c of data ?? []) ids.push(c.id_lista);
    if (!data || data.length < 1000) break;
  }
  return ids;
}

// ---------- mensagens do /info ----------
function webhookDe(i: Record<string, any>) {
  return `${API}/webhooks/${i.application_id}/${i.token}`;
}
async function editarOriginal(i: Record<string, any>, corpo: unknown) {
  const r = await fetch(`${webhookDe(i)}/messages/@original`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo),
  });
  if (!r.ok) console.error("editar original", r.status, await r.text());
}
async function novaMensagem(i: Record<string, any>, corpo: Record<string, unknown>) {
  const r = await fetch(webhookDe(i), {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo),
  });
  if (!r.ok) console.error("mensagem nova", r.status, await r.text());
}

// Monta as mensagens de um cartao (texto completo + imagens), sem links do Trello.
async function mensagensDoCartao(idOuNome: string) {
  let { data: c } = /^[0-9a-f]{24}$/.test(idOuNome)
    ? await supa.from("trello_cartoes").select("*").eq("id", idOuNome).maybeSingle()
    : { data: null };
  if (!c && limpa(idOuNome)) {
    const { data } = await supa.from("trello_cartoes").select("*").ilike("nome", `%${limpa(idOuNome)}%`).order("pos").limit(1);
    c = data?.[0] ?? null;
  }
  if (!c) return null;
  const { data: lista } = await supa.from("trello_listas").select("nome").eq("id", c.id_lista).maybeSingle();
  const pedacos = partes(c.texto || "_(sem descricao)_").slice(0, 5);
  const imagens: string[] = Array.isArray(c.imagens) ? c.imagens : [];
  const rodape = { text: `${lista?.nome ?? "Clover Retribution"} · Clover Retribution` };
  return pedacos.map((texto, k) => {
    const ultimo = k === pedacos.length - 1;
    return {
      allowed_mentions: { parse: [] },
      embeds: [
        {
          title: k === 0 ? String(c.nome).slice(0, 256) : undefined, description: texto, color: COR_INFO,
          footer: ultimo ? rodape : undefined,
          image: k === 0 && imagens[0] ? { url: imagens[0] } : undefined,
        },
        ...(ultimo ? imagens.slice(1, 4).map((u) => ({ color: COR_INFO, image: { url: u } })) : []),
      ],
    };
  });
}

// ---------- organizacao dos menus ----------
const norm = (t: string) => t.toLowerCase().replace(/[^a-z0-9]/g, "");
const CATEGORIAS: { nome: string; emoji: string; listas: string[] }[] = [
  { nome: "Informacoes gerais", emoji: "📘", listas: ["General Information", "Game Mechanics", "New Player Assistance", "Magic Knights", "Credits"] },
  { nome: "Personagem e magia", emoji: "✨", listas: ["Grimoires", "Magics", "Races", "Traits", "Families", "Skill Tree System", "Mana Skin", "Face Markings", "Titles", "Arcane Spells", "Spirits", "Devils"] },
  { nome: "Equipamentos e itens", emoji: "⚔️", listas: ["Weapon Classes", "Weapons", "Armors", "Accessories", "Enchantments", "Misc Items", "Professions"] },
  { nome: "Mundo e combate", emoji: "🗺️", listas: ["Quests", "NPCs", "Elites / Mini Bosses", "Raids", "Dungeons", "Grimoire Gauntlet"] },
  { nome: "Eventos e atualizacoes", emoji: "🎉", listas: [] },   // + qualquer secao de evento/atualizacao
];
const ICONES: Record<string, string> = {
  generalinformation: "ℹ️", gamemechanics: "⚙️", newplayerassistance: "🆕", magicknights: "🛡️", credits: "👥",
  grimoires: "📖", magics: "🔮", races: "🧬", traits: "🧠", families: "👪", skilltreesystem: "🌳", manaskin: "💠",
  facemarkings: "🎭", titles: "🏷️", arcanespells: "🪄", spirits: "👻", devils: "😈",
  weaponclasses: "🎯", weapons: "🗡️", armors: "🦺", accessories: "💍", enchantments: "✨", miscitems: "🎒", professions: "⛏️",
  quests: "📜", npcs: "🧑", elitesminibosses: "👹", raids: "🐉", dungeons: "🏰", grimoiregauntlet: "🥊",
};
function categoriaDe(nomeLista: string) {
  const n = norm(nomeLista);
  const k = CATEGORIAS.findIndex((c) => c.listas.some((l) => norm(l) === n));
  if (k >= 0) return k;
  if (/event|update|halloween|valentine|christmas|xmas|easter|anniversary|tribute|season|summer|winter/i.test(nomeLista)) return 4;
  return 0;
}
// Cartoes que sao "cabecalho" de grupo dentro da secao (ex.: "Common - 49%", "Legendary")
const CABECALHO = /^(common|uncommon|rare|epic|legendary|mythic|mythical|secret|exotic|divine|unique|limited|special)\b/i;

// Menu das secoes: um menu por categoria (o Discord deixa ate 5 menus por mensagem)
async function menuSecoes() {
  const [{ data: listas }, idsLista] = await Promise.all([
    supa.from("trello_listas").select("id, nome").order("pos"),
    todosOsIdsDeLista(),
  ]);
  const qtd = new Map<string, number>();
  for (const id of idsLista) qtd.set(id, (qtd.get(id) ?? 0) + 1);
  const grupos: { id: string; nome: string }[][] = CATEGORIAS.map(() => []);
  for (const l of listas ?? []) if ((qtd.get(l.id) ?? 0) > 0) grupos[categoriaDe(l.nome)].push(l);
  const linhas = [];
  for (let k = 0; k < CATEGORIAS.length; k++) {
    const g = grupos[k].slice(0, 25);
    if (!g.length) continue;
    const cat = CATEGORIAS[k];
    linhas.push({
      type: 1,
      components: [{
        type: 3, custom_id: `info_sec:${k}`, placeholder: `${cat.emoji}  ${cat.nome}`,
        options: g.map((l) => ({
          label: l.nome.slice(0, 100), value: l.id, description: `${qtd.get(l.id)} item(ns)`,
          emoji: { name: ICONES[norm(l.nome)] ?? cat.emoji },
        })),
      }],
    });
  }
  return {
    content: "📚 **Clover Retribution** · abra uma categoria e escolha a secao:",
    embeds: [], components: linhas,
  };
}

// Cor de cada raridade (igual ao jeito do Trello de separar por raridade)
function emojiRaridade(nome: string) {
  const n = nome.toLowerCase();
  if (n.startsWith("uncommon")) return "🟢";
  if (n.startsWith("common")) return "⚪";
  if (n.startsWith("rare")) return "🔵";
  if (n.startsWith("epic")) return "🟣";
  if (n.startsWith("legendary")) return "🟡";
  if (n.startsWith("mythic")) return "🔴";
  if (n.startsWith("secret")) return "⚫";
  if (n.startsWith("exotic")) return "🌈";
  if (n.startsWith("divine")) return "✨";
  if (n.startsWith("unobtainable")) return "🚫";
  return "📊";
}

// Menu dos itens de uma secao.
// Se a secao tem raridades (cartoes "Common - 46%", "Rare - ..."), cada raridade vira um menu,
// na mesma ordem do Trello. Sem raridades: menus de 25 em 25. Ate 4 menus por pagina.
async function menuItens(idLista: string, pagina: number) {
  const [{ data: lista }, { data: cards }] = await Promise.all([
    supa.from("trello_listas").select("nome").eq("id", idLista).maybeSingle(),
    supa.from("trello_cartoes").select("*").eq("id_lista", idLista).order("pos"),
  ]);
  const todos = (cards ?? []) as { id: string; nome: string; raridade?: string | null }[];
  type Bloco = { titulo: string; emoji?: string; itens: { id: string; nome: string; cab?: boolean }[] };
  const blocos: Bloco[] = [];
  // So separa por raridade quando a secao comeca com um cabecalho de raridade com %
  // (ex.: "Common - 46%"), como no Trello. Evita confundir itens como "Divine Nullifier".
  const porRaridade = todos.length > 0 && CABECALHO.test(todos[0].nome) && /\d\s*%/.test(todos[0].nome);
  if (porRaridade) {
    let atual: Bloco | null = null;
    for (const c of todos) {
      if (CABECALHO.test(c.nome)) {
        atual = { titulo: c.nome, emoji: emojiRaridade(c.nome), itens: [{ ...c, cab: true }] };
        blocos.push(atual);
      } else {
        if (!atual) { atual = { titulo: "Geral", emoji: "📄", itens: [] }; blocos.push(atual); }
        atual.itens.push(c);
      }
    }
  } else if (todos.some((c) => c.raridade)) {
    // raridade pela etiqueta colorida do Trello, na ordem Common > ... > Unobtainable, e "Outros" no fim
    const ordem = [...RARIDADES, ""];
    for (const r of ordem) {
      const itens = todos.filter((c) => (c.raridade ?? "") === r);
      if (itens.length) blocos.push({ titulo: r || "Outros", emoji: r ? emojiRaridade(r) : "📄", itens });
    }
  } else {
    blocos.push({ titulo: "", itens: todos });
  }
  // cada menu do Discord aceita ate 25 opcoes: raridades grandes viram (1/2), (2/2)...
  const menus: { titulo: string; emoji?: string; itens: Bloco["itens"] }[] = [];
  for (const b of blocos) {
    const partes = Math.ceil(b.itens.length / 25) || 1;
    for (let k = 0; k < partes; k++) {
      const itens = b.itens.slice(k * 25, (k + 1) * 25);
      if (!itens.length) continue;
      let titulo = b.titulo;
      if (!titulo) {
        titulo = todos.length > 25 ? `${itens[0].nome.slice(0, 22)} … ${itens[itens.length - 1].nome.slice(0, 22)}` : "Escolha o item";
      } else if (partes > 1) titulo += ` (${k + 1}/${partes})`;
      menus.push({ titulo, emoji: b.emoji, itens });
    }
  }
  const POR_PAGINA = 4;
  const paginas = Math.max(1, Math.ceil(menus.length / POR_PAGINA));
  const p = Math.min(Math.max(0, pagina), paginas - 1);
  const daPagina = menus.slice(p * POR_PAGINA, (p + 1) * POR_PAGINA);
  const icone = lista ? (ICONES[norm(lista.nome)] ?? CATEGORIAS[categoriaDe(lista.nome)].emoji) : "📄";
  const linhas: unknown[] = daPagina.map((m, k) => ({
    type: 1,
    components: [{
      type: 3, custom_id: `info_item:${idLista}:${p}:${k}`,
      placeholder: `${m.emoji ? m.emoji + "  " : ""}${m.titulo}`.slice(0, 150),
      options: m.itens.map((c) => ({
        label: (c.cab ? "Sobre esta raridade" : c.nome).slice(0, 100), value: c.id,
        description: c.cab ? c.nome.slice(0, 100) : undefined,
        emoji: c.cab ? { name: "📊" } : (m.emoji ? { name: m.emoji } : undefined),
      })),
    }],
  }));
  const botoes = [{ type: 2, style: 2, label: "Categorias", emoji: { name: "↩️" }, custom_id: "info_voltar" }];
  if (paginas > 1) {
    botoes.push({ type: 2, style: 1, label: "Anterior", emoji: { name: "◀️" }, custom_id: `info_pag:${idLista}:${p - 1}`, disabled: p === 0 } as never);
    botoes.push({ type: 2, style: 1, label: "Proxima", emoji: { name: "▶️" }, custom_id: `info_pag:${idLista}:${p + 1}`, disabled: p >= paginas - 1 } as never);
  }
  linhas.push({ type: 1, components: botoes });
  return {
    content: `${icone} **${lista?.nome ?? "Secao"}** · ${todos.length} item(ns)` + (paginas > 1 ? ` · pagina ${p + 1} de ${paginas}` : "") +
      "\nEscolha o item para mostrar no chat:",
    embeds: [], components: linhas,
  };
}

// Mostra o cartao no chat (para todos) em mensagens novas
async function postarCartao(i: Record<string, any>, idOuNome: string) {
  const msgs = await mensagensDoCartao(idOuNome);
  if (!msgs) return false;
  for (const m of msgs) await novaMensagem(i, m);
  return true;
}

let comandosEnviados = false;

async function anotar(texto: string) {
  try {
    await supa.from("discord_estados").insert({
      estado: `diario-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`, tipo: "diario", erro: texto.slice(0, 900),
      pronto: true, expira_em: new Date(Date.now() + 2 * 86_400_000).toISOString(),
    });
  } catch { /* */ }
}

async function interacaoDiscord(req: Request) {
  const inicio = performance.now();
  const resposta = await interacaoDiscordReal(req);
  const ms = Math.round(performance.now() - inicio);
  let resumo = "";
  try { resumo = (await resposta.clone().text()).slice(0, 300); } catch { /* */ }
  await anotar(`${new Date().toISOString()} | ${resposta.status} | ${ms} ms | ${ultimoTipo} | ${resumo}`);
  return resposta;
}
let ultimoTipo = "";

async function interacaoDiscordReal(req: Request) {
  const corpo = await req.text();
  if (!(await assinaturaDiscordValida(req, corpo))) return new Response("assinatura invalida", { status: 401 });
  const i = JSON.parse(corpo);
  ultimoTipo = `tipo ${i.type} ${i.data?.name ?? i.data?.custom_id ?? ""}`;
  if (i.type === 1) {                                   // PING: ao salvar o endereco no Developer Portal
    emSegundoPlano(registrarComandos(String(i.application_id)));
    return json({ type: 1 });
  }
  if (!comandosEnviados && i.application_id) {          // garante a definicao mais nova do /info no Discord
    comandosEnviados = true;
    emSegundoPlano(registrarComandos(String(i.application_id)));
  }
  if (i.type === 4) return await sugestoes(i);          // sugestoes enquanto digita (atalho /info secao item)

  // Tudo e respondido DIRETO (sem trabalho em segundo plano): o Discord espera ate 3 s.
  const soParaMim = (content: string) => json({ type: 4, data: { content, flags: 64 } });
  const cartaoNoChat = async (idOuNome: string) => {
    const msgs = await mensagensDoCartao(idOuNome);
    if (!msgs) return soParaMim("Nao encontrei esse item. Use /info e escolha pelos menus.");
    for (const m of msgs.slice(1)) emSegundoPlano(novaMensagem(i, m));   // continuacao de textos muito longos
    return json({ type: 4, data: msgs[0] });                             // aparece no chat para todos
  };
  try {
    if (i.type === 2 && i.data?.name === "info") {
      if (!i.guild_id) return soParaMim("Use o /info dentro de um servidor.");
      const { data: restrito } = await supa.from("discord_info_canal").select("channel_id")
        .eq("guild_id", String(i.guild_id)).maybeSingle();
      if (restrito && restrito.channel_id !== String(i.channel_id ?? i.channel?.id)) {
        return soParaMim(`Neste servidor o /info funciona so em <#${restrito.channel_id}>.`);
      }
      const { o } = opcoes(i);
      if (limpa(o.item ?? "")) return await cartaoNoChat(o.item);
      const menu = /^[0-9a-f]{24}$/.test(o.secao ?? "") ? await menuItens(o.secao, 0) : await menuSecoes();
      if (!menu.components.length) {
        return soParaMim("As informacoes do Trello ainda nao foram carregadas. No site, clique em \"Carregar o Trello agora\".");
      }
      return json({ type: 4, data: { ...menu, flags: 64 } });              // menus so para quem digitou
    }
    if (i.type === 3) {                                                   // cliques nos menus/botoes
      const id = String(i.data?.custom_id ?? "");
      const valor = String(i.data?.values?.[0] ?? "");
      if (id.startsWith("info_sec:")) return json({ type: 7, data: await menuItens(valor, 0) });
      if (id.startsWith("info_pag:")) {
        const [, idLista, pag] = id.split(":");
        return json({ type: 7, data: await menuItens(idLista, Number(pag) || 0) });
      }
      if (id === "info_voltar") return json({ type: 7, data: await menuSecoes() });
      if (id.startsWith("info_item:")) return await cartaoNoChat(valor);
    }
    return soParaMim("Comando desconhecido.");
  } catch (e) {
    console.error("/info:", e);
    return soParaMim("Deu um erro no /info: " + (e instanceof Error ? e.message : String(e)));
  }
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  const url = new URL(req.url);
  // Diagnostico publico do /info (sem segredos): .../discord-bot?diag=info
  if (req.method === "GET" && url.searchParams.get("diag") === "info") {
    const r: Record<string, unknown> = { versao: VERSAO_BOT };
    const medir = async (nome: string, f: () => Promise<unknown>) => {
      const t0 = performance.now();
      try { r[nome] = await f(); } catch (e) { r[nome] = "ERRO " + (e instanceof Error ? e.message : String(e)); }
      r[nome + "_ms"] = Math.round(performance.now() - t0);
    };
    await medir("chave_publica", async () => (hexBytes(Deno.env.get("DISCORD_PUBLIC_KEY") ?? "")?.length ?? 0) + " bytes");
    await medir("ed25519_nativo", async () => {
      const b = hexBytes(Deno.env.get("DISCORD_PUBLIC_KEY") ?? "");
      if (!b) return "sem chave";
      const k = await crypto.subtle.importKey("raw", b, { name: "Ed25519" }, false, ["verify"]);
      return await crypto.subtle.verify({ name: "Ed25519" }, k, new Uint8Array(64), new Uint8Array(1)) ? "?" : "funciona";
    });
    await medir("menu_secoes", async () => {
      const m = await menuSecoes();
      return { menus: m.components.length, bytes: JSON.stringify(m).length, exemplo: (m.components[0] as any)?.components?.[0]?.options?.slice(0, 2) };
    });
    await medir("sugestoes_Ma", async () => (await (await sugestoes({ data: { options: [{ name: "secao", value: "Ma", focused: true }] } })).json()));
    await medir("menu_itens_magics", async () => {
      const { data } = await supa.from("trello_listas").select("id").ilike("nome", "Magics").maybeSingle();
      const m = await menuItens(data?.id ?? "", 0);
      return { linhas: m.components.length, bytes: JSON.stringify(m).length };
    });
    if (url.searchParams.get("registrar") === "1") {
      await medir("registrar_agora", async () => {
        const appId = Deno.env.get("DISCORD_CLIENT_ID");
        const rr = await fetch(`${API}/applications/${appId}/commands`, {
          method: "PUT", headers: { Authorization: comoBot(), "Content-Type": "application/json" }, body: JSON.stringify(COMANDOS),
        });
        return `${rr.status} ${rr.ok ? "ok" : (await rr.text()).slice(0, 300)}`;
      });
    }
    await medir("diario", async () => {
      const { data } = await supa.from("discord_estados").select("estado, erro").eq("tipo", "diario")
        .order("estado", { ascending: false }).limit(15);
      return (data ?? []).map((d) => d.erro);
    });
    await medir("comandos_registrados", async () => {
      const appId = Deno.env.get("DISCORD_CLIENT_ID");
      const rr = await fetch(`${API}/applications/${appId}/commands`, { headers: { Authorization: comoBot() } });
      const lista = await rr.json();
      return Array.isArray(lista) ? lista.map((c: any) => ({ nome: c.name, opcoes: (c.options ?? []).map((o: any) => `${o.name}${o.required ? "*" : ""}`) })) : lista;
    });
    return json(r);
  }
  // Teste/forcar a copia do Trello pelo navegador: .../discord-bot?trello=atualizar
  if (req.method === "GET" && url.searchParams.get("trello") === "atualizar") {
    try {
      await supa.from("trello_estado").upsert({ id: 1, atualizando_desde: null });   // destrava
      await atualizarTrello(true);
      const [{ count: secoes }, { count: itens }] = await Promise.all([
        supa.from("trello_listas").select("id", { count: "exact", head: true }),
        supa.from("trello_cartoes").select("id", { count: "exact", head: true }),
      ]);
      return textoPc(`OK! Trello carregado: ${secoes ?? 0} secoes e ${itens ?? 0} itens. Ja pode usar o /info.`);
    } catch (e) {
      return textoPc("ERRO ao carregar o Trello: " + (e instanceof Error ? e.message : String(e)));
    }
  }
  if (req.method === "GET") return await retornoLogin(url);
  if (req.method !== "POST") return json({ erro: "metodo invalido" }, 405);
  if (req.headers.get("x-signature-ed25519")) return await interacaoDiscord(req);   // comandos do Discord

  try {
    const corpo = await req.json().catch(() => ({}));
    const qual = String(corpo.acao ?? "");
    const chavePc = req.headers.get("x-chave-pc")?.trim();

    // Programa do PC
    if (qual === "pc_resultado") return json(await pcResultado(String(corpo.estado ?? "")));
    if (qual === "pc_iniciar") return json(await pcIniciar(corpo, chavePc ? await donoDoPc(chavePc) : null));
    if (chavePc) {
      const dono = await donoDoPc(chavePc);
      if (!dono) return json({ erro: "chave do PC invalida, conecte o PC de novo" }, 401);
      if (!["painel", "canais", "escolher", "remover", "participar", "participar_todos", "desligar", "frases", "frase_add", "frase_del"].includes(qual)) return json({ erro: "acao invalida" }, 403);
      return json(await acao(dono, corpo));
    }

    // Site do painel e login do app com Discord (sem conta ainda)
    if (qual === "web_iniciar") return json(await webIniciar());
    if (qual === "app_login_iniciar") return json(await appLoginIniciar());
    const sessaoWeb = req.headers.get("x-sessao-web")?.trim();
    if (sessaoWeb) {
      const dono = await donoDaSessao(sessaoWeb);
      if (!dono) return json({ erro: "sessao expirada", sair: true }, 401);
      if (qual === "web_sair") {
        await supa.from("sessoes_web").delete().eq("token_hash", await sha256(sessaoWeb));
        return json({ ok: true });
      }
      if (!["painel", "canais", "escolher", "remover", "participar", "participar_todos", "desligar", "info_canal", "trello_atualizar", "info_diagnostico", "frases", "frase_add", "frase_del"].includes(qual)) return json({ erro: "acao invalida" }, 403);
      return json(await acao(dono, corpo));
    }

    // App do celular
    const jwt = (req.headers.get("authorization") ?? "").replace(/^Bearer\s+/i, "");
    const { data: quem } = await supa.auth.getUser(jwt);
    if (!quem?.user) return json({ erro: "faca login no app" }, 401);
    return json(await acao(quem.user.id, corpo));
  } catch (e) {
    return json({ erro: e instanceof Error ? e.message : String(e) });
  }
});
