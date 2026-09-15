(()=>{
  "use strict";
  const OLD_EMAIL="agroaicontact@gmail.com";
  const CURRENT_EMAIL="contact@agroai-pilot.com";
  const LEGAL_PATHS=new Set(["/terms-of-service","/privacy-policy","/pilot-agreement"]);
  const cleanPath=(value)=>value!=="/"?value.replace(/\/+$/,""):value;

  function replaceLegacyEmail(){
    document.querySelectorAll(`a[href^="mailto:${OLD_EMAIL}"]`).forEach((link)=>{
      const href=link.getAttribute("href")||"";
      const suffix=href.slice(`mailto:${OLD_EMAIL}`.length);
      link.setAttribute("href",`mailto:${CURRENT_EMAIL}${suffix}`);
      if((link.textContent||"").includes(OLD_EMAIL)) link.textContent=(link.textContent||"").replaceAll(OLD_EMAIL,CURRENT_EMAIL);
    });
    if(!document.body) return;
    const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
    const matches=[];
    let node;
    while((node=walker.nextNode())){
      if(node.nodeValue&&node.nodeValue.includes(OLD_EMAIL)) matches.push(node);
    }
    matches.forEach((textNode)=>{textNode.nodeValue=(textNode.nodeValue||"").replaceAll(OLD_EMAIL,CURRENT_EMAIL);});
  }

  function legalListItem(href,label){
    const li=document.createElement("li");
    const a=document.createElement("a");
    a.href=href;
    a.textContent=label;
    a.className="text-gray-400 hover:text-white transition-colors";
    li.appendChild(a);
    return li;
  }

  function installFooterTrustLinks(){
    const legalSection=document.querySelector('[data-testid="footer-legal"]');
    if(!legalSection) return false;
    const heading=legalSection.querySelector("h2,h3,h4");
    if(heading&&heading.textContent&&heading.textContent.trim()==="Legal") heading.textContent="Trust & Legal";
    const list=legalSection.querySelector("ul");
    if(!list) return false;
    if(!list.querySelector('a[href="/trust"]')) list.insertBefore(legalListItem("/trust","Trust Center"),list.firstChild);
    if(!list.querySelector('a[href="/trust/data-governance"]')){
      const item=legalListItem("/trust/data-governance","Data Governance");
      const trustLink=list.querySelector('a[href="/trust"]');
      const trustItem=trustLink&&trustLink.closest("li");
      if(trustItem) trustItem.insertAdjacentElement("afterend",item); else list.insertBefore(item,list.firstChild);
    }
    return true;
  }

  function navLink(href,label){
    const a=document.createElement("a");
    a.href=href;
    a.textContent=label;
    if(cleanPath(location.pathname)===cleanPath(href)) a.setAttribute("aria-current","page");
    return a;
  }

  function navGroup(title,links){
    const group=document.createElement("div");
    group.className="agroai-trust-legal-group";
    const label=document.createElement("div");
    label.className="agroai-trust-legal-label";
    label.textContent=title;
    const row=document.createElement("div");
    row.className="agroai-trust-legal-links";
    links.forEach(([href,text])=>row.appendChild(navLink(href,text)));
    group.append(label,row);
    return group;
  }

  function installLegalNavigator(){
    if(!LEGAL_PATHS.has(cleanPath(location.pathname))) return true;
    if(document.getElementById("agroai-trust-legal-nav")) return true;
    const main=document.querySelector("main");
    if(!main) return false;
    const panel=document.createElement("aside");
    panel.id="agroai-trust-legal-nav";
    panel.className="agroai-trust-legal-nav";
    panel.setAttribute("aria-label","AGRO-AI Trust and Legal");
    const top=document.createElement("div");
    top.className="agroai-trust-legal-heading";
    const eyebrow=document.createElement("span");
    eyebrow.textContent="AGRO-AI Trust & Legal";
    const copy=document.createElement("p");
    copy.textContent="Contractual documents and the standards that explain how AGRO-AI governs agricultural, operational and personal data.";
    top.append(eyebrow,copy);
    panel.append(
      top,
      navGroup("Trust & data governance",[["/trust","Trust Center"],["/trust/data-governance","Data Governance"],["/trust/ai-data-use","AI & Model Data Use"],["/trust/security","Security"]]),
      navGroup("Legal documents",[["/terms-of-service","Terms of Service"],["/privacy-policy","Privacy Policy"],["/pilot-agreement","Pilot Agreement"]])
    );
    main.insertBefore(panel,main.firstChild);
    return true;
  }

  function install(){
    replaceLegacyEmail();
    installFooterTrustLinks();
    installLegalNavigator();
  }

  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",install,{once:true}); else install();
  let attempts=0;
  const timer=setInterval(()=>{install();attempts+=1;if(attempts>=40) clearInterval(timer);},250);
  const observer=new MutationObserver(()=>install());
  observer.observe(document.documentElement,{childList:true,subtree:true});
  setTimeout(()=>observer.disconnect(),12000);
})();
