// Alerta Roblox - recebe o alerta do PC e manda push (Firebase) para o celular.
// Publicar: Supabase > Edge Functions > (funcao) > Code > cole este arquivo > Deploy
// Em Settings da funcao, deixe "Verify JWT" DESLIGADO (o PC usa a chave "x-chave-pc").
// Segredo necessario (Edge Functions > Secrets):
//   FIREBASE_SERVICE_ACCOUNT = conteudo inteiro do JSON da conta de servico do Firebase
// Opcional (para mandar tambem no Discord, ver supabase/functions/discord-bot):
//   DISCORD_BOT_TOKEN = token do bot do Discord

import { createClient } from "jsr:@supabase/supabase-js@2";

// Chave de servico: a antiga (service_role) ou a nova (SUPABASE_SECRET_KEYS).
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
const supa = createClient(Deno.env.get("SUPABASE_URL")!, chaveServico());
const MAX_POR_MINUTO = 6;

function resposta(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), {
    status, headers: { "Content-Type": "application/json" },
  });
}
async function sha256(texto: string) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(texto));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
function texto(v: unknown, max: number): string | null {
  if (typeof v !== "string") return null;
  const t = v.trim().slice(0, max);
  return t || null;
}
function linkSeguro(v: unknown): string | null {
  const t = texto(v, 500);
  if (!t) return null;
  try {
    const u = new URL(t);
    const ok = u.protocol === "https:" &&
      (u.hostname === "roblox.com" || u.hostname.endsWith(".roblox.com"));
    return ok ? u.toString() : null;
  } catch { return null; }
}

// ---------- Firebase Cloud Messaging (HTTP v1) ----------
type ContaServico = { project_id: string; client_email: string; private_key: string };
let conta: ContaServico | null = null;
let tokenGoogle: { valor: string; expira: number } | null = null;

function b64url(dados: Uint8Array | string) {
  const bytes = typeof dados === "string" ? new TextEncoder().encode(dados) : dados;
  let bin = "";
  bytes.forEach((b) => (bin += String.fromCharCode(b)));
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function acessoGoogle(): Promise<string> {
  if (tokenGoogle && tokenGoogle.expira > Date.now() + 60_000) return tokenGoogle.valor;
  if (!conta) {
    const bruto = Deno.env.get("FIREBASE_SERVICE_ACCOUNT");
    if (!bruto) throw new Error("segredo FIREBASE_SERVICE_ACCOUNT nao configurado");
    conta = JSON.parse(bruto);
  }
  const agora = Math.floor(Date.now() / 1000);
  const cabecalho = b64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const corpo = b64url(JSON.stringify({
    iss: conta!.client_email,
    scope: "https://www.googleapis.com/auth/firebase.messaging",
    aud: "https://oauth2.googleapis.com/token",
    iat: agora,
    exp: agora + 3600,
  }));
  const pem = conta!.private_key.replace(/-----[^-]+-----/g, "").replace(/\s+/g, "");
  const der = Uint8Array.from(atob(pem), (c) => c.charCodeAt(0));
  const chave = await crypto.subtle.importKey(
    "pkcs8", der, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"],
  );
  const assinatura = new Uint8Array(await crypto.subtle.sign(
    "RSASSA-PKCS1-v1_5", chave, new TextEncoder().encode(`${cabecalho}.${corpo}`),
  ));
  const jwt = `${cabecalho}.${corpo}.${b64url(assinatura)}`;
  const r = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion: jwt,
    }),
  });
  const j = await r.json();
  if (!r.ok) throw new Error("Google recusou a conta de servico: " + JSON.stringify(j));
  tokenGoogle = { valor: j.access_token, expira: Date.now() + j.expires_in * 1000 };
  return tokenGoogle.valor;
}

async function enviarFcm(token: string, titulo: string, corpo: string, dados: Record<string, string>) {
  const acesso = await acessoGoogle();
  const r = await fetch(
    `https://fcm.googleapis.com/v1/projects/${conta!.project_id}/messages:send`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${acesso}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        message: {
          token,
          notification: { title: titulo, body: corpo },
          data: dados,
          android: {
            priority: "HIGH",
            ttl: "120s",
            notification: {
              channel_id: "alertas",
              sound: "default",
              default_vibrate_timings: true,
              notification_priority: "PRIORITY_MAX",
              visibility: "PUBLIC",
            },
          },
        },
      }),
    },
  );
  if (r.ok) return "ok";
  const erro = await r.json().catch(() => ({}));
  const codigo = JSON.stringify(erro);
  if (r.status === 404 || codigo.includes("UNREGISTERED") || codigo.includes("INVALID_ARGUMENT")) {
    return "morto";
  }
  console.error("FCM falhou", r.status, codigo);
  return "erro";
}

async function enviarPush(userId: string, alertaId: number, alerta: Record<string, any>) {
  const { data: tokens } = await supa.from("push_tokens").select("token").eq("user_id", userId);
  if (!tokens?.length) return { enviados: 0, aviso: "nenhum celular logado" };

  const titulo = alerta.teste ? "Teste do Alerta Roblox" : `🚨 ${alerta.frase ?? "Mensagem detectada"}`;
  const texto_ = [
    resumo(alerta) ? `${alerta.frase ?? "Mensagem"} ${resumo(alerta)}` : null,
    alerta.mensagem ? `Lido no chat: ${alerta.mensagem}` : null,
  ].filter(Boolean).join("\n") || "Abra o app para ver";
  const dados = { alerta_id: String(alertaId), link: alerta.link ?? "" };

  try {
    const resultados = await Promise.all(
      tokens.map((t) => enviarFcm(t.token, titulo, texto_, dados).then((r) => ({ t: t.token, r }))),
    );
    const mortos = resultados.filter((x) => x.r === "morto").map((x) => x.t);
    if (mortos.length) await supa.from("push_tokens").delete().in("token", mortos);
    return { enviados: resultados.filter((x) => x.r === "ok").length };
  } catch (e) {
    console.error(e);
    return { enviados: 0, aviso: "alerta salvo, mas o push falhou: " + String(e) };
  }
}

// "Something feels off no server ABC123 do jogador Fulano" (server e jogador configuraveis no PC).
// O Job ID (codigo interno do Roblox) nao aparece: ele so vai dentro do link "Entrar no servidor".
function servidorDo(a: Record<string, any>) {
  return (a.codigo_servidor as string | null) || null;
}
function resumo(a: Record<string, any>, negrito = false) {
  const b = (t: string) => (negrito ? `**${t.replace(/\*/g, "")}**` : t);
  const partes = [];
  const srv = servidorDo(a);
  if (srv) partes.push(`no server ${b(srv)}`);
  if (a.jogador) partes.push(`do jogador ${b(String(a.jogador))}`);
  let texto = partes.join(" ");
  if (a.mapa) texto += `${texto ? " · " : ""}Mapa: ${b(String(a.mapa))}`;
  return texto;
}

// ---------- Discord (canais escolhidos no app, aba Discord) ----------
async function enviarDiscord(userId: string, a: Record<string, unknown>) {
  const token = Deno.env.get("DISCORD_BOT_TOKEN")?.trim();
  if (!token) return 0;
  // Servidores onde a pessoa participa -> canal escolhido pelo administrador de cada um
  const { data: meus } = await supa.from("discord_participantes").select("guild_id").eq("user_id", userId);
  if (!meus?.length) return 0;
  const { data: canais } = await supa.from("discord_servidores").select("guild_id, channel_id")
    .in("guild_id", meus.map((m) => m.guild_id));
  if (!canais?.length) return 0;

  const campos = [
    a.mensagem ? { name: "Lido no chat", value: String(a.mensagem).slice(0, 1000), inline: false } : null,
  ].filter(Boolean);
  const frase = String(a.frase ?? "Mensagem detectada").replace(/\*/g, "");
  const mensagem = {
    allowed_mentions: { parse: [] },
    embeds: [{
      title: a.teste ? "Teste do Alerta Roblox" : `🚨 ${frase}`,
      description: a.teste ? (resumo(a, true) || undefined)
        : `**${frase}** ${resumo(a, true)}`.trim(),
      color: a.teste ? 0x8b93a3 : 0xe53935,
      fields: campos,
      timestamp: new Date().toISOString(),
    }],
    components: a.link ? [{
      type: 1,
      components: [{ type: 2, style: 5, label: "Entrar no servidor", url: String(a.link) }],
    }] : [],
  };

  let enviados = 0;
  await Promise.all(canais.map(async (c) => {
    const r = await fetch(`https://discord.com/api/v10/channels/${c.channel_id}/messages`, {
      method: "POST",
      headers: { Authorization: `Bot ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify(mensagem),
    });
    if (r.ok) { enviados++; return; }
    const erro = await r.json().catch(() => ({}));
    console.error("Discord falhou", r.status, JSON.stringify(erro));
    // 10003 = canal apagado; 10004 = bot saiu do servidor
    if (erro?.code === 10003 || erro?.code === 10004) {
      await supa.from("discord_servidores").delete().eq("guild_id", c.guild_id);
    }
  }));
  return enviados;
}

// ---------- Rota principal ----------
Deno.serve(async (req) => {
  if (req.method !== "POST") return resposta({ erro: "use POST" }, 405);

  // 1) Quem e o PC?
  const chave = req.headers.get("x-chave-pc")?.trim() ?? "";
  if (!/^rbx_[0-9a-f]{48}$/.test(chave)) return resposta({ erro: "chave invalida" }, 401);
  const { data: pc } = await supa.from("pc_keys").select("id, user_id")
    .eq("key_hash", await sha256(chave)).maybeSingle();
  if (!pc) return resposta({ erro: "chave invalida" }, 401);

  // 2) Limite contra spam
  const umMinutoAtras = new Date(Date.now() - 60_000).toISOString();
  const { count } = await supa.from("alerts").select("id", { count: "exact", head: true })
    .eq("user_id", pc.user_id).gte("created_at", umMinutoAtras);
  if ((count ?? 0) >= MAX_POR_MINUTO) return resposta({ erro: "muitos alertas, espere um pouco" }, 429);

  // 3) Salva o alerta
  let corpo: Record<string, unknown>;
  try { corpo = await req.json(); } catch { return resposta({ erro: "JSON invalido" }, 400); }
  const alerta = {
    user_id: pc.user_id, pc_id: pc.id,
    frase: texto(corpo.frase, 120), mensagem: texto(corpo.mensagem, 300),
    jogador: texto(corpo.jogador, 60), job_id: texto(corpo.job_id, 64),
    place_id: texto(corpo.place_id, 20), link: linkSeguro(corpo.link),
    teste: corpo.teste === true,
    mapa: texto(corpo.mapa, 20), codigo_servidor: texto(corpo.codigo_servidor, 200),
  };
  let { data: salvo, error } = await supa.from("alerts").insert(alerta).select("id").single();
  if (error) {
    // Banco ainda sem as colunas mapa/codigo_servidor (SQL 0008 nao rodado): salva sem elas.
    const { mapa: _m, codigo_servidor: _c, ...semNovos } = alerta;
    ({ data: salvo, error } = await supa.from("alerts").insert(semNovos).select("id").single());
  }
  if (error || !salvo) return resposta({ erro: "falha ao salvar" }, 500);
  await supa.from("pc_keys").update({ last_used_at: new Date().toISOString() }).eq("id", pc.id);

  // 4) Push para os celulares e mensagem nos canais do Discord, ao mesmo tempo
  const [celular, discord] = await Promise.all([
    enviarPush(pc.user_id, salvo.id, alerta),
    enviarDiscord(pc.user_id, alerta).catch((e) => { console.error(e); return 0; }),
  ]);
  return resposta({ ok: true, ...celular, discord });
});
