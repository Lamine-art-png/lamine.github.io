const PATH="/academy/early-access";
// Call the Render origin directly: calling api.agroai-pilot.com from a same-zone Worker fails to reach it.
const API="https://agroai-api-preview.onrender.com/v1/sales/contact";
const LANGS=new Set(["en","pt-BR","fr","es","other"]);
const ROLES=new Set(["grower","operator","manager","developer","student","other"]);
const PAGE=`<!doctype html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>AGRO-AI Academy | Free Early Access</title>
<meta name="description" content="Register for free early access to AGRO-AI Academy courses."/>
<meta name="robots" content="index,follow"/><link rel="canonical" href="https://agroai-pilot.com/academy/early-access"/>
<link rel="preconnect" href="https://fonts.cdnfonts.com"/><link href="https://fonts.cdnfonts.com/css/glacial-indifference-2" rel="stylesheet"/>
<meta name="theme-color" content="#234224"/>
<style>
*{box-sizing:border-box}body{margin:0;background:#f8faf6;color:#18351e;font-family:"Glacial Indifference",Arial,sans-serif}
a{color:#234224}header{border-bottom:1px solid #dae5da;background:white;padding:20px}nav{max-width:1030px;margin:auto;display:flex;justify-content:space-between;align-items:center;gap:15px}
.brand{font-size:22px;text-decoration:none;font-weight:bold}main{max-width:1030px;margin:60px auto 90px;padding:0 20px;display:grid;grid-template-columns:1.1fr .9fr;gap:55px;align-items:center}
h1{font-size:clamp(40px,5vw,70px);letter-spacing:-.05em;line-height:1.03;margin:15px 0 25px}
.eyebrow{text-transform:uppercase;letter-spacing:.15em;color:#3b7644;font-size:12px;font-weight:700}
.lead{font-size:21px;line-height:1.5;color:#455a49}.tag{display:inline-block;padding:8px 14px;background:#e7f0e7;border-radius:25px;font-weight:bold;font-size:14px}
.cover{margin-top:30px;border:1px solid #dae5da;border-radius:15px;overflow:hidden;background:white}.cover img{display:block;width:100%;height:auto}
form{background:white;border:1px solid #dce7dd;padding:34px;border-radius:20px;box-shadow:0 15px 50px #15351e0d}
h2{margin:0 0 8px}form p,.note{color:#596b5c;line-height:1.55;font-size:15px}
label{display:block;font-size:14px;font-weight:700;margin:15px 0 7px}input,select{font:inherit;width:100%;min-height:47px;border:1px solid #bfcfc0;border-radius:9px;padding:10px;color:#18351e;background:white}
.consent{display:flex;gap:10px;align-items:start;margin:22px 0}.consent input{width:17px;min-height:17px;flex-shrink:0;margin:3px 0 0}.consent label{font-weight:400;margin:0;line-height:1.5}
button{background:#234224;color:white;font:inherit;font-weight:700;padding:16px;width:100%;border:0;border-radius:9px;cursor:pointer}button:disabled{opacity:.6}
.website{display:none}.message{margin-top:16px;font-size:15px;color:#255e32}.error{color:#a33}
@media(max-width:800px){main{grid-template-columns:1fr;margin:45px auto 60px;gap:36px}form{padding:24px}}
</style></head><body><header><nav><a class="brand" href="https://agroai-pilot.com">AGRO-AI Academy</a><a href="https://agroai-pilot.com/news/introducing-agro-ai-academy">Our announcement ↗</a></nav></header>
<main><section><span class="eyebrow">Free agricultural AI education</span><h1>Be first to learn with AGRO-AI Academy.</h1><p class="lead">Practical AI lessons for growers, operators, agricultural managers and developers. Join our early-access list to hear when the first courses are ready.</p><span class="tag">Free · No purchase required</span>
<div class="cover"><img src="https://agroai-pilot.com/news/introducing-agro-ai-academy/cover.svg" alt="AGRO-AI Academy official cover" width="1920" height="1080"/></div>
<p class="note">First Enterprise Portal lessons planned for October 29, 2026, followed by additional agricultural AI and Platform API learning resources.</p></section>
<form id="form"><h2>Register for free early access</h2><p>We'll email you about course availability and related Academy updates.</p>
<label for="name">Full name</label><input name="name" id="name" autocomplete="name" minlength="2" maxlength="120" required/>
<label for="email">Email</label><input name="email" id="email" type="email" autocomplete="email" maxlength="240" required/>
<label for="language">Preferred language</label><select name="language" id="language" required><option value="en">English</option><option value="pt-BR">Português (Brasil)</option><option value="fr">Français</option><option value="es">Español</option><option value="other">Other</option></select>
<label for="role">Your work</label><select name="role" id="role"><option value="grower">Farmer / grower</option><option value="operator">Field operator</option><option value="manager">Agricultural manager</option><option value="developer">Developer / integrator</option><option value="student">Student / researcher</option><option value="other">Other</option></select>
<div class="website"><input name="website" tabindex="-1" autocomplete="off" aria-hidden="true"/></div>
<div class="consent"><input type="checkbox" name="consent" value="yes" id="consent" required/><label for="consent">I agree to receive AGRO-AI Academy course updates by email. I can unsubscribe at any time.</label></div>
<button type="submit" id="submit">Register free</button><div role="status" aria-live="polite" id="status" class="message"></div><p class="note">Registration is free and does not change your AGRO-AI software subscription.</p></form></main>
<script>
(()=>{const f=document.getElementById("form"),b=document.getElementById("submit"),msg=document.getElementById("status");
const l=navigator.language||"en";document.getElementById("language").value=/^pt/i.test(l)?"pt-BR":/^fr/i.test(l)?"fr":/^es/i.test(l)?"es":"en";
f.addEventListener("submit",async e=>{e.preventDefault();if(!f.reportValidity())return;b.disabled=true;msg.textContent="Registering…";msg.className="message";
try{const data=Object.fromEntries(new FormData(f).entries());
const r=await fetch("/academy/early-access",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(data)});
const out=await r.json();if(!r.ok||!out.ok)throw Error(out.error||"failed");
f.querySelectorAll("input,select").forEach(x=>x.disabled=true);b.textContent="Registered";msg.textContent="You're registered. We'll email you when the Academy lessons are available.";}
catch{msg.textContent="Registration is temporarily unavailable. Please try again.";msg.className="message error";b.disabled=false;}});})();
</script></body></html>`;
const response=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{"content-type":"application/json; charset=utf-8","cache-control":"no-store","x-content-type-options":"nosniff"}});
const clean=(x,n)=>String(x??"").replace(/\u0000/g,"").trim().slice(0,n);
async function register(request){
 if(!(request.headers.get("content-type")||"").includes("application/json"))return response({ok:false,error:"invalid_content_type"},415);
 const origin=request.headers.get("origin");if(origin&&origin!=="https://agroai-pilot.com")return response({ok:false,error:"invalid_origin"},403);
 if(Number(request.headers.get("content-length")||0)>8192)return response({ok:false,error:"too_large"},413);
 let p;try{p=await request.json();}catch{return response({ok:false,error:"invalid_json"},400);}
 if(!p||typeof p!=="object"||Array.isArray(p))return response({ok:false,error:"invalid_body"},400);
 if(clean(p.website,100))return response({ok:true},201);
 const name=clean(p.name,120),email=clean(p.email,240).toLowerCase(),language=clean(p.language,15),role=clean(p.role||"other",30);
 if(name.length<2||!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)||!LANGS.has(language)||!ROLES.has(role)||p.consent!=="yes")return response({ok:false,error:"invalid_fields"},422);
 try{
 const body={type:"sales",priority:"low",name,email,role,subject:"AGRO-AI Academy free early-access registration",message:"NEW AGRO-AI ACADEMY REGISTRATION — Free early access. Preferred language: "+language+". Role: "+role+". User explicitly opted in to Academy course availability and educational updates. Registration is not an Enterprise Portal account.",source_page:"academy/early-access",metadata:{campaign:"agro_ai_academy",kind:"free_early_access",email_opt_in:true,language,role,source:"academy_registration"}};
 const r=await fetch(API,{method:"POST",headers:{"content-type":"application/json","accept":"application/json"},body:JSON.stringify(body),redirect:"manual"});
 if(!r.ok){ console.error("Academy registration upstream returned status",r.status);return response({ok:false,error:"upstream_unavailable"},503);}
 const saved=await r.json();if(saved.status!=="received"||!saved.request_id)return response({ok:false,error:"not_saved"},503);
 if(saved.notification_status!=="emailed") console.error("Academy registration saved but operator email not accepted",saved.request_id,saved.notification_status);
 return response({ok:true,registration_id:saved.request_id,notification_sent:saved.notification_status==="emailed"},201);
 }catch(exc){console.error("Academy registration backend fetch failed",String(exc));return response({ok:false,error:"upstream_unavailable"},503);}
}
export default{async fetch(request){
 const path=new URL(request.url).pathname.replace(/\/+$/,"");
 if(path!==PATH)return new Response("Not found",{status:404});
 if(request.method==="GET"||request.method==="HEAD")return new Response(request.method==="HEAD"?null:PAGE,{headers:{"content-type":"text/html; charset=utf-8","x-content-type-options":"nosniff","cache-control":"public,max-age=120","referrer-policy":"strict-origin-when-cross-origin","content-security-policy":"default-src 'none'; style-src 'unsafe-inline' https://fonts.cdnfonts.com; font-src https://fonts.cdnfonts.com; img-src https:; connect-src 'self'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"}});
 if(request.method==="POST")return register(request);
 return new Response("Method not allowed",{status:405,headers:{allow:"GET, HEAD, POST"}});
}};
