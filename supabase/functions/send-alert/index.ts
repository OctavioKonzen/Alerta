// Alerta Roblox - funcao que recebe o alerta do PC e manda push para o celular.
// Deploy:  supabase functions deploy send-alert --no-verify-jwt
// (o PC se identifica pela chave no cabecalho "x-chave-pc", nao por login)

import { createClient } from "jsr:@supabase/supabase-js@2";

const supa = createClient(
  Deno.env.get("SUPABASE_URL")!,
  Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
);

const MAX_POR_MINUTO = 6;

function resposta(corpo: unknown, status = 200) {
  return new Response(JSON.stringify(corpo), {
    status,
    headers: { "Content-Type": "application/json" },
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
  } catch {
    return null;
  }
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return resposta({ erro: "use POST" }, 405);

  // 1) Quem e o PC?
  const chave = req.headers.get("x-chave-pc")?.trim() ?? "";
  if (!/^rbx_[0-9a-f]{48}$/.test(chave)) return resposta({ erro: "chave invalida" }, 401);
  const { data: pc } = await supa
    .from("pc_keys")
    .select("id, user_id")
    .eq("key_hash", await sha256(chave))
    .maybeSingle();
  if (!pc) return resposta({ erro: "chave invalida" }, 401);

  // 2) Limite contra spam
  const umMinutoAtras = new Date(Date.now() - 60_000).toISOString();
  const { count } = await supa
    .from("alerts")
    .select("id", { count: "exact", head: true })
    .eq("user_id", pc.user_id)
    .gte("created_at", umMinutoAtras);
  if ((count ?? 0) >= MAX_POR_MINUTO) {
    return resposta({ erro: "muitos alertas, espere um pouco" }, 429);
  }

  // 3) Dados do alerta
  let corpo: Record<string, unknown>;
  try {
    corpo = await req.json();
  } catch {
    return resposta({ erro: "JSON invalido" }, 400);
  }
  const alerta = {
    user_id: pc.user_id,
    pc_id: pc.id,
    frase: texto(corpo.frase, 120),
    mensagem: texto(corpo.mensagem, 300),
    jogador: texto(corpo.jogador, 60),
    job_id: texto(corpo.job_id, 64),
    place_id: texto(corpo.place_id, 20),
    link: linkSeguro(corpo.link),
    teste: corpo.teste === true,
  };
  const { data: salvo, error } = await supa.from("alerts").insert(alerta).select("id").single();
  if (error) return resposta({ erro: "falha ao salvar" }, 500);
  await supa.from("pc_keys").update({ last_used_at: new Date().toISOString() }).eq("id", pc.id);

  // 4) Push para todos os celulares da conta
  const { data: tokens } = await supa.from("push_tokens").select("token").eq("user_id", pc.user_id);
  if (!tokens?.length) return resposta({ ok: true, enviados: 0, aviso: "nenhum celular logado" });

  const titulo = alerta.teste ? "Teste do Alerta Roblox" : `🚨 ${alerta.frase ?? "Mensagem detectada"}`;
  const linhas = [
    alerta.mensagem,
    alerta.jogador ? `Jogador: ${alerta.jogador}` : null,
    alerta.job_id ? `Servidor: ${alerta.job_id}` : null,
  ].filter(Boolean);

  const mensagens = tokens.map((t) => ({
    to: t.token,
    title: titulo,
    body: linhas.join("\n") || "Abra o app para ver",
    sound: "default",
    priority: "high",
    channelId: "alertas",
    ttl: 120,
    data: { alerta_id: salvo.id, link: alerta.link },
  }));

  let enviados = 0;
  try {
    const r = await fetch("https://exp.host/--/api/v2/push/send", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(mensagens),
    });
    const tickets = (await r.json())?.data ?? [];
    const mortos: string[] = [];
    tickets.forEach((tk: { status: string; details?: { error?: string } }, i: number) => {
      if (tk.status === "ok") enviados++;
      else if (tk.details?.error === "DeviceNotRegistered") mortos.push(mensagens[i].to);
    });
    if (mortos.length) await supa.from("push_tokens").delete().in("token", mortos);
  } catch (_e) {
    return resposta({ ok: true, enviados: 0, aviso: "alerta salvo, mas o push falhou" });
  }
  return resposta({ ok: true, enviados });
});
