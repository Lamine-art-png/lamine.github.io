const CONTACT_API = "https://api.agroai-pilot.com/v1/sales/contact";
const CONTACT_EMAIL = "contact@agroai-pilot.com";
const MAX_REQUEST_BYTES = 24 * 1024;

const FAEP_HTML = String.raw`<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>AGRO-AI | Sistema FAEP</title>
  <meta name="description" content="Formulário exclusivo para participantes da delegação do Sistema FAEP." />
  <meta name="robots" content="noindex,nofollow" />
  <meta name="theme-color" content="#234224" />
  <link rel="icon" type="image/png" href="/attached_assets/Copy of AGRO-AI (1)_1763408301972.png" />
  <link href="https://fonts.cdnfonts.com/css/glacial-indifference-2" rel="stylesheet" />
  <style>
    :root{--g900:#17321a;--g800:#234224;--g700:#2c6400;--g100:#edf4e9;--ink:#182018;--muted:#667168;--line:#dfe6dc;--paper:#fbfcf8;--white:#fff;--err:#9a2f2f}
    *{box-sizing:border-box}html{background:var(--paper)}body{margin:0;min-height:100vh;color:var(--ink);background:radial-gradient(circle at 10% 0%,rgba(44,100,0,.08),transparent 34%),linear-gradient(180deg,#fbfcf8 0%,#f5f8f2 100%);font-family:"Glacial Indifference",Arial,sans-serif;-webkit-font-smoothing:antialiased}
    .shell{width:min(100% - 32px,760px);margin:0 auto;padding:34px 0 56px}.brand{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:44px}.brand img{width:72px;height:72px;object-fit:contain;display:block}.tag{border:1px solid rgba(44,100,0,.18);background:rgba(255,255,255,.78);color:var(--g800);border-radius:999px;padding:8px 12px;font-size:13px;white-space:nowrap}
    h1{margin:0;max-width:700px;color:var(--g900);font-size:clamp(38px,7vw,58px);line-height:.99;letter-spacing:-.035em;font-weight:700}.lead{margin:20px 0 24px;max-width:650px;color:var(--muted);font-size:19px;line-height:1.5}.time{display:inline-flex;align-items:center;gap:8px;margin-bottom:28px;padding:8px 11px;border-radius:10px;background:var(--g100);color:var(--g800);font-size:14px;font-weight:700}.time:before{content:"";width:8px;height:8px;border-radius:50%;background:var(--g700)}
    .card{background:rgba(255,255,255,.92);border:1px solid var(--line);border-radius:24px;padding:clamp(22px,5vw,38px);box-shadow:0 18px 48px rgba(25,54,27,.06)}.field{margin-bottom:22px}label,legend{display:block;margin-bottom:8px;color:var(--g900);font-size:15px;font-weight:700}.optional{color:#849087;font-weight:400}
    input,select,textarea{width:100%;min-height:50px;border:1px solid #cad4c8;border-radius:12px;background:#fff;color:var(--ink);padding:13px 14px;font:inherit;font-size:16px;outline:none;transition:border-color .15s ease,box-shadow .15s ease}textarea{min-height:108px;resize:vertical;line-height:1.45}input:focus,select:focus,textarea:focus{border-color:var(--g700);box-shadow:0 0 0 3px rgba(44,100,0,.1)}input::placeholder,textarea::placeholder{color:#9aa39b}
    fieldset{border:0;margin:0 0 22px;padding:0}.choices{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.choice{position:relative;display:flex;align-items:center;justify-content:center;min-height:62px;border:1px solid #cad4c8;border-radius:12px;padding:10px 12px;background:#fff;color:#314132;text-align:center;font-size:14px;line-height:1.2;cursor:pointer}.choice input{position:absolute;opacity:0;pointer-events:none}.choice:has(input:checked){border-color:var(--g700);background:var(--g100);color:var(--g900);box-shadow:inset 0 0 0 1px var(--g700);font-weight:700}
    .consent{display:flex;gap:10px;align-items:flex-start;margin:8px 0 24px;color:#68736a;font-size:13px;line-height:1.4;font-weight:400}.consent input{width:18px;min-height:18px;height:18px;margin-top:1px;flex:0 0 auto;accent-color:var(--g700)}button{width:100%;min-height:54px;border:0;border-radius:13px;background:linear-gradient(135deg,var(--g800),var(--g700));color:#fff;padding:14px 18px;font:inherit;font-size:17px;font-weight:700;cursor:pointer;box-shadow:0 10px 24px rgba(44,100,0,.16)}button:disabled{cursor:wait;opacity:.65}.fine{margin:14px 2px 0;color:#889188;text-align:center;font-size:12px;line-height:1.4}.status{display:none;margin-top:16px;border-radius:12px;padding:14px 16px;font-size:14px;line-height:1.4}.status.err{display:block;color:var(--err);background:#fff2f2;border:1px solid #f0caca}
    .success{display:none;text-align:center;padding:26px 4px 8px}.success.active{display:block}.check{display:grid;width:58px;height:58px;place-items:center;margin:0 auto 18px;border-radius:50%;background:var(--g100);color:var(--g700);font-size:28px;font-weight:700}.success h2{margin:0 0 10px;color:var(--g900);font-size:30px}.success p{margin:0 auto;max-width:510px;color:var(--muted);font-size:17px;line-height:1.5}.footer{margin-top:24px;text-align:center;color:#8a948b;font-size:12px}.hp{position:absolute!important;left:-9999px!important;width:1px!important;height:1px!important;overflow:hidden!important}
    @media(max-width:620px){.shell{width:min(100% - 22px,760px);padding-top:20px}.brand{margin-bottom:32px}.brand img{width:60px;height:60px}.tag{font-size:12px}h1{font-size:42px}.lead{font-size:17px}.card{border-radius:20px}.choices{grid-template-columns:1fr}.choice{min-height:50px;justify-content:flex-start;text-align:left;padding-left:16px}}
  </style>
</head>
<body>
  <main class="shell">
    <div class="brand"><a href="https://agroai-pilot.com" aria-label="AGRO-AI"><img src="/attached_assets/Copy of AGRO-AI (1)_1763408301972.png" alt="AGRO-AI" /></a><div class="tag">Sistema FAEP · Paraná</div></div>
    <section><h1>Onde a AGRO-AI pode ajudar na sua operação?</h1><p class="lead">Conte-nos o essencial sobre sua fazenda, sindicato ou cooperativa. Nossa equipe analisará suas informações e entrará em contato diretamente pelo WhatsApp.</p><div class="time">Leva menos de 1 minuto</div></section>
    <section class="card">
      <form id="faep-form" novalidate>
        <div class="field"><label for="nome">Nome completo</label><input id="nome" name="nome" type="text" autocomplete="name" maxlength="120" required /></div>
        <div class="field"><label for="whatsapp">WhatsApp com DDD</label><input id="whatsapp" name="whatsapp" type="tel" inputmode="tel" autocomplete="tel" maxlength="60" placeholder="(41) 99999-9999" required /></div>
        <div class="field"><label for="atividade">Principal atividade</label><select id="atividade" name="atividade" required><option value="" selected disabled>Selecione</option><option>Soja, milho, trigo e outros grãos</option><option>Café</option><option>Frutas / culturas permanentes</option><option>Leite</option><option>Gado de corte</option><option>Suínos / aves</option><option>Horticultura</option><option>Operação diversificada</option><option>Outro</option></select></div>
        <div class="field"><label for="area">Área aproximada <span class="optional">(opcional)</span></label><select id="area" name="area"><option value="" selected>Prefiro não informar</option><option>Até 50 hectares</option><option>51–200 hectares</option><option>201–500 hectares</option><option>501–1.000 hectares</option><option>1.001–5.000 hectares</option><option>Mais de 5.000 hectares</option></select></div>
        <div class="field"><label for="problema">Qual é o principal problema que você gostaria de melhorar?</label><textarea id="problema" name="problema" maxlength="1200" placeholder="Ex.: informações espalhadas, relatórios, acompanhamento de tarefas, manutenção, tomada de decisão..." required></textarea></div>
        <fieldset><legend>Tenho interesse em</legend><div class="choices"><label class="choice"><input type="radio" name="interesse" value="Minha fazenda" required />Minha fazenda</label><label class="choice"><input type="radio" name="interesse" value="Sindicato ou cooperativa" required />Sindicato ou cooperativa</label><label class="choice"><input type="radio" name="interesse" value="Ambos" required />Ambos</label></div></fieldset>
        <div class="hp" aria-hidden="true"><label for="website">Website</label><input id="website" name="website" type="text" tabindex="-1" autocomplete="off" /></div>
        <label class="consent"><input type="checkbox" name="consentimento" value="Autorizado" required /><span>Autorizo a AGRO-AI a usar estas informações para avaliar esta solicitação e entrar em contato comigo pelo WhatsApp.</span></label>
        <button id="submit" type="submit">Enviar informações</button><div id="status" class="status" role="alert" aria-live="polite"></div><p class="fine">Suas informações serão usadas somente para esta conversa com a AGRO-AI.</p>
      </form>
      <div id="success" class="success" aria-live="polite"><div class="check">✓</div><h2>Obrigado.</h2><p id="success-copy">Recebemos suas informações. A equipe AGRO-AI analisará sua operação e entrará em contato pelo WhatsApp.</p></div>
    </section>
    <div class="footer">AGRO-AI Inc. · San Francisco · agroai-pilot.com</div>
  </main>
  <script>
    (()=>{const form=document.getElementById('faep-form'),submit=document.getElementById('submit'),status=document.getElementById('status'),success=document.getElementById('success'),copy=document.getElementById('success-copy');form.addEventListener('submit',async(e)=>{e.preventDefault();status.className='status';status.textContent='';if(!form.reportValidity())return;submit.disabled=true;submit.textContent='Enviando...';const data=Object.fromEntries(new FormData(form).entries());try{const r=await fetch('/api/faep',{method:'POST',headers:{'content-type':'application/json',accept:'application/json'},body:JSON.stringify(data),credentials:'same-origin'});const out=await r.json().catch(()=>({}));if(!r.ok||!out.ok)throw new Error(out.error||'submission_failed');const first=String(data.nome||'').trim().split(/\s+/)[0];form.style.display='none';success.classList.add('active');if(first)copy.textContent=first+', recebemos suas informações. A equipe AGRO-AI analisará sua operação e entrará em contato pelo WhatsApp.';window.scrollTo({top:document.querySelector('.card').offsetTop-20,behavior:'smooth'});}catch(err){console.error(err);status.textContent='Não foi possível enviar agora. Tente novamente em alguns segundos.';status.className='status err';submit.disabled=false;submit.textContent='Enviar informações';}});})();
  </script>
</body></html>`;

function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "x-agroai-faep-intake": "active",
      ...extra,
    },
  });
}

function page() {
  return new Response(FAEP_HTML, {
    status: 200,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store, max-age=0",
      "x-content-type-options": "nosniff",
      "x-frame-options": "SAMEORIGIN",
      "referrer-policy": "strict-origin-when-cross-origin",
      "x-robots-tag": "noindex, nofollow",
      "x-agroai-faep-intake": "active",
    },
  });
}

function clean(value, max = 1200) {
  return String(value ?? "").replace(/\u0000/g, "").trim().slice(0, max);
}

async function submit(request) {
  const declared = Number(request.headers.get("content-length") || 0);
  if (Number.isFinite(declared) && declared > MAX_REQUEST_BYTES) {
    return json({ ok: false, error: "submission_too_large" }, 413);
  }

  let payload;
  try {
    const bytes = await request.arrayBuffer();
    if (bytes.byteLength > MAX_REQUEST_BYTES) return json({ ok: false, error: "submission_too_large" }, 413);
    payload = JSON.parse(new TextDecoder().decode(bytes) || "{}");
  } catch {
    return json({ ok: false, error: "invalid_submission" }, 400);
  }

  if (clean(payload.website, 120)) return json({ ok: true, status: "received" }, 201);

  const nome = clean(payload.nome, 120);
  const whatsapp = clean(payload.whatsapp, 60);
  const atividade = clean(payload.atividade, 160);
  const area = clean(payload.area, 100) || "Não informado";
  const problema = clean(payload.problema, 1200);
  const interesse = clean(payload.interesse, 100);
  const consentimento = clean(payload.consentimento, 40);
  const digits = whatsapp.replace(/\D/g, "");

  if (!nome || digits.length < 10 || !atividade || !problema || !interesse || !consentimento) {
    return json({ ok: false, error: "missing_or_invalid_required_fields" }, 400);
  }

  const allowed = new Set(["Minha fazenda", "Sindicato ou cooperativa", "Ambos"]);
  if (!allowed.has(interesse)) return json({ ok: false, error: "invalid_interest" }, 400);

  const message = [
    "Novo interesse — Delegação Sistema FAEP / AGRO-AI",
    "",
    `Nome: ${nome}`,
    `WhatsApp: ${whatsapp}`,
    `Principal atividade: ${atividade}`,
    `Área aproximada: ${area}`,
    `Interesse: ${interesse}`,
    "",
    "Principal problema que gostaria de melhorar:",
    problema,
    "",
    `Consentimento para contato pelo WhatsApp: ${consentimento}`,
    "Origem: agroai-pilot.com/faep",
  ].join("\n");

  const lead = {
    type: "sales",
    priority: "high",
    name: nome,
    email: null,
    company: interesse === "Minha fazenda" ? "FAEP — propriedade rural" : `FAEP — ${interesse}`,
    role: "Participante da Delegação Sistema FAEP",
    subject: `FAEP Paraná — ${nome} — ${atividade}`.slice(0, 180),
    message: message.slice(0, 4000),
    source_page: "faep-parana",
    metadata: {
      faep_intake: true,
      whatsapp,
      atividade,
      area,
      interesse,
      consentimento,
    },
  };

  let response;
  try {
    response = await fetch(CONTACT_API, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json",
        "x-agroai-source": "faep-intake-worker",
      },
      body: JSON.stringify(lead),
    });
  } catch {
    return json({ ok: false, error: "notification_network_error" }, 502);
  }

  const result = await response.json().catch(() => ({}));
  const emailed = response.ok && result.status === "received" && typeof result.notification_status === "string" && result.notification_status.startsWith("emailed:");
  if (!emailed) {
    return json({ ok: false, error: "notification_delivery_failed" }, 502);
  }

  return json({
    ok: true,
    status: "received",
    request_id: result.request_id || null,
    message: "Recebemos suas informações. A equipe AGRO-AI entrará em contato pelo WhatsApp.",
  }, 201, {
    "x-agroai-notification": "delivered",
  });
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    if (path === "/faep") {
      if (request.method !== "GET" && request.method !== "HEAD") return new Response("Method not allowed", { status: 405, headers: { allow: "GET, HEAD" } });
      return page();
    }

    if (path === "/api/faep") {
      if (request.method === "GET") {
        return json({ ok: true, status: "live", notification_recipient: CONTACT_EMAIL, language: "pt-BR" });
      }
      if (request.method !== "POST") return json({ ok: false, error: "method_not_allowed" }, 405, { allow: "GET, POST" });
      return submit(request);
    }

    return new Response("Not found", { status: 404 });
  },
};
