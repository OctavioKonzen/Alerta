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
// No Developer Portal > OAuth2 > Redirects, adicione:
//   https://vtyxkowxnesclwtndbog.supabase.co/functions/v1/discord-bot

import { createClient } from "jsr:@supabase/supabase-js@2";

const NOME_FUNCAO = "discord-bot";
const VOLTAR_APP = "alertaroblox://discord";
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
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
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
function linkConvite() {
  return `https://discord.com/oauth2/authorize?client_id=${segredo("DISCORD_CLIENT_ID")}` +
    `&scope=bot&permissions=${PERMISSOES_BOT}`;
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
    const url = "https://discord.com/oauth2/authorize?" + new URLSearchParams({
      client_id: segredo("DISCORD_CLIENT_ID"), response_type: "code",
      scope: "identify guilds", redirect_uri: REDIRECT, state: estado,
    });
    return { url };
  }

  if (qual === "sair") {
    await supa.from("discord_canais").delete().eq("user_id", userId);
    await supa.from("discord_contas").delete().eq("user_id", userId);
    return { ok: true };
  }

  if (qual === "remover") {
    await supa.from("discord_canais").delete().eq("user_id", userId).eq("guild_id", String(corpo.guild_id));
    return { ok: true };
  }

  const pessoa = await tokenDaPessoa(userId);
  if (!pessoa) return { conectado: false, convite: linkConvite() };

  if (qual === "painel") {
    const [servidores, { data: escolhidos }] = await Promise.all([
      servidoresEmComum(pessoa.token),
      supa.from("discord_canais").select("guild_id, channel_id, canal_nome").eq("user_id", userId),
    ]);
    const porServidor = new Map((escolhidos ?? []).map((c) => [c.guild_id, c]));
    return {
      conectado: true, nome: pessoa.nome, convite: linkConvite(),
      servidores: servidores.map((g) => ({
        id: g.id, nome: g.name, admin: ehAdmin(g),
        icone: g.icon ? `https://cdn.discordapp.com/icons/${g.id}/${g.icon}.png?size=64` : null,
        canal: porServidor.has(g.id)
          ? { id: porServidor.get(g.id)!.channel_id, nome: porServidor.get(g.id)!.canal_nome }
          : null,
      })),
    };
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
        content: `✅ Este canal vai receber os alertas do **Alerta Roblox** de ${pessoa.nome ?? "um jogador"}.`,
        allowed_mentions: { parse: [] },
      }),
    });
    if (!teste.ok) {
      console.error("teste falhou", teste.status, JSON.stringify(teste.corpo));
      throw new Error("o bot nao consegue mandar mensagem em #" + canal.nome +
        ". Nas permissoes do canal, deixe o bot Ver canal, Enviar mensagens e Inserir links.");
    }
    await supa.from("discord_canais").upsert({
      user_id: userId, guild_id: guildId, guild_nome: g.name.slice(0, 100),
      channel_id: channelId, canal_nome: canal.nome.slice(0, 100),
    }, { onConflict: "user_id,guild_id" });
    return { ok: true };
  }

  return { erro: "acao desconhecida" };
}

// ---------- Retorno do login com Discord (vem do navegador) ----------
async function retornoLogin(url: URL) {
  const estado = url.searchParams.get("state") ?? "";
  const code = url.searchParams.get("code");
  if (!code) return voltar({ erro: "login cancelado" });

  const { data: pedido } = await supa.from("discord_estados").select("user_id, expira_em")
    .eq("estado", estado).maybeSingle();
  if (!pedido || new Date(pedido.expira_em) < new Date()) return voltar({ erro: "pedido expirado, tente de novo" });
  await supa.from("discord_estados").delete().eq("estado", estado);

  try {
    const t = await trocarToken({ grant_type: "authorization_code", code, redirect_uri: REDIRECT });
    const eu = await discord("/users/@me", `Bearer ${t.access_token}`);
    if (!eu.ok) throw new Error("nao consegui ler sua conta do Discord");
    const u = eu.corpo as { id: string; username: string; global_name?: string };
    await supa.from("discord_contas").upsert({
      user_id: pedido.user_id, discord_id: u.id, nome: (u.global_name || u.username).slice(0, 60),
      access_token: t.access_token, refresh_token: t.refresh_token,
      expira_em: new Date(Date.now() + t.expires_in * 1000).toISOString(),
      updated_at: new Date().toISOString(),
    });
    return voltar({ ok: "1" });
  } catch (e) {
    console.error(e);
    return voltar({ erro: "falha no login com Discord" });
  }
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  const url = new URL(req.url);
  if (req.method === "GET") return await retornoLogin(url);
  if (req.method !== "POST") return json({ erro: "metodo invalido" }, 405);

  const jwt = (req.headers.get("authorization") ?? "").replace(/^Bearer\s+/i, "");
  const { data: quem } = await supa.auth.getUser(jwt);
  if (!quem?.user) return json({ erro: "faca login no app" }, 401);

  try {
    const corpo = await req.json().catch(() => ({}));
    return json(await acao(quem.user.id, corpo));
  } catch (e) {
    return json({ erro: e instanceof Error ? e.message : String(e) });
  }
});
