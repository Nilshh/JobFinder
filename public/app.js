// ── State ──
let km = 50, days = 7;
const titles = new Set();
const JOBS = {}; // storeId → job object
let sfFilter = "all";
let allMerged = [], currentPage = 0, renderMeta = {};
const PAGE_SIZE = 20;
let remoteOnly = false;

// ── Auth state ──
let AUTH = { user: null };
let _authMode = "login";      // "login" | "register" | "forgot" | "reset"
let _pendingAction = null;    // callback nach erfolgreichem Login
let _resetToken = null;       // Token aus ?reset=... URL-Parameter

// ── Storage ──
const LS = {
  saved:      () => { try{ return JSON.parse(localStorage.getItem("jf2_saved")||"{}"); }catch(e){return {};} },
  ignored:    () => { try{ return JSON.parse(localStorage.getItem("jf2_ign")||"[]"); }catch(e){return [];} },
  setSaved:   d => { localStorage.setItem("jf2_saved", JSON.stringify(d)); refreshBadge(); syncUserData(); },
  setIgnored: a => { localStorage.setItem("jf2_ign",   JSON.stringify(a)); syncUserData(); }
};

function jobKey(j){ return (j.redirect_url||(j.title+"|"+(j.company?.display_name||""))).slice(0,180); }

function refreshBadge(){
  const n = Object.keys(LS.saved()).length;
  const b = document.getElementById("badge");
  b.textContent = n; b.style.display = n ? "block" : "none";
  document.getElementById("savCntTitle").textContent = n;
}

// ── Tabs ──
function showTab(t){
  document.getElementById("tabSearch").style.display  = t==="search"  ?"block":"none";
  document.getElementById("tabSaved").style.display   = t==="saved"   ?"block":"none";
  document.getElementById("tabPortals").style.display = t==="portals" ?"block":"none";
  document.getElementById("nb1").classList.toggle("on", t==="search");
  document.getElementById("nb2").classList.toggle("on", t==="saved");
  document.getElementById("nb3").classList.toggle("on", t==="portals");
  if(t==="saved")   renderSaved();
  if(t==="portals") renderPortalsTab();
}

// ── Chips ──
document.getElementById("chips").addEventListener("click", e => {
  const btn = e.target.closest(".chip");
  if(!btn) return;
  const t = btn.dataset.t;
  if(titles.has(t)){ titles.delete(t); btn.classList.remove("on"); }
  else             { titles.add(t);    btn.classList.add("on"); }
  renderSelTags();
});

document.getElementById("ftBtn").addEventListener("click", addFt);
document.getElementById("ftInp").addEventListener("keydown", e => { if(e.key==="Enter"){ e.preventDefault(); addFt(); } });

function addFt(){
  const v = document.getElementById("ftInp").value.trim();
  if(!v) return;
  titles.add(v);
  document.getElementById("ftInp").value = "";
  renderSelTags();
}

function renderSelTags(){
  const wrap = document.getElementById("selTags");
  wrap.innerHTML = "";
  titles.forEach(t => {
    const span = document.createElement("span");
    span.className = "stag";
    span.appendChild(document.createTextNode(t));
    const x = document.createElement("button");
    x.type="button"; x.className="stag-x"; x.textContent="×";
    x.addEventListener("click", () => {
      titles.delete(t);
      document.querySelectorAll(".chip").forEach(c=>{ if(c.dataset.t===t) c.classList.remove("on"); });
      renderSelTags();
    });
    span.appendChild(x);
    wrap.appendChild(span);
  });
  document.getElementById("selHint").style.display = titles.size ? "block":"none";
  document.getElementById("selCnt").textContent = titles.size;
}

// ── Radio rows ──
document.getElementById("rrowKm").addEventListener("click", e => {
  const btn = e.target.closest(".rbtn");
  if(!btn) return;
  document.querySelectorAll("#rrowKm .rbtn").forEach(b=>b.classList.remove("on"));
  btn.classList.add("on");
  km = parseInt(btn.dataset.v);
});
document.getElementById("rrowDays").addEventListener("click", e => {
  const btn = e.target.closest(".rbtn");
  if(!btn) return;
  document.querySelectorAll("#rrowDays .rbtn").forEach(b=>b.classList.remove("on"));
  btn.classList.add("on");
  days = parseInt(btn.dataset.v);
});

// ── BA Job Normalizer ──
function normBaJob(j, title){
  const refnr = j.refnr || "";
  const loc   = j.arbeitsort
    ? [j.arbeitsort.ort, j.arbeitsort.region].filter(Boolean).join(", ")
    : "";
  return {
    title:         j.titel       || "",
    company:       { display_name: j.arbeitgeber || "" },
    location:      { display_name: loc },
    redirect_url:  j.externeUrl  || (refnr ? "https://www.arbeitsagentur.de/jobsuche/jobdetail/"+refnr : ""),
    created:       j.aktuelleVeroeffentlichungsdatum || "",
    contract_type: j.befristung===1 ? "permanent" : j.befristung===2 ? "temporary" : undefined,
    salary_min:    undefined,
    salary_max:    undefined,
    _t:            title,
    _source:       "BA"
  };
}

// ── Jobicy Job Normalizer ──
function normJobicyJob(j, title){
  return {
    title:         j.jobTitle    || "",
    company:       { display_name: j.companyName || "" },
    location:      { display_name: j.jobGeo ? j.jobGeo+" (Remote)" : "Remote" },
    redirect_url:  j.url         || "",
    created:       j.pubDate     || "",
    contract_type: j.jobType     || undefined,
    salary_min:    j.annualSalaryMin || undefined,
    salary_max:    j.annualSalaryMax || undefined,
    _t:            title,
    _source:       "Jobicy"
  };
}

// ── Remote toggle ──
document.getElementById("remoteToggle").addEventListener("click", () => {
  remoteOnly = !remoteOnly;
  document.getElementById("remoteToggle").classList.toggle("on", remoteOnly);
  document.getElementById("locOptHint").style.display = remoteOnly ? "inline" : "none";
  const rrowKm = document.getElementById("rrowKm");
  rrowKm.style.opacity = remoteOnly ? "0.35" : "1";
  rrowKm.style.pointerEvents = remoteOnly ? "none" : "";
});

// ── Search ──
document.getElementById("goBtn").addEventListener("click", doSearch);

async function doSearch(){
  const loc = document.getElementById("inpLoc").value.trim();
  const plz = document.getElementById("inpPlz").value.trim();
  const where = plz ? (loc ? plz+" "+loc : plz) : loc;

  if(!titles.size){ showErr("Bitte mindestens einen Jobtitel wählen."); return; }

  hide("errbx"); hide("infobx"); hide("nores"); hide("platbox"); hide("footer"); hide("reshdr");
  document.getElementById("restags").innerHTML = "";
  document.getElementById("joblist").innerHTML = "";
  show("loadbox");
  document.getElementById("goBtn").disabled = true;

  const arr = Array.from(titles);
  const country = where.toLowerCase().includes("wien")||where.toLowerCase().includes("österreich")?"at"
                : where.toLowerCase().includes("zürich")||where.toLowerCase().includes("schweiz")?"ch":"de";
  const displayWhere = remoteOnly ? (where || "Remote") : (where || "Deutschland");
  document.getElementById("stxt").textContent = arr.length>1 ? "Suche nach "+arr.length+" Jobtiteln parallel…" : "Suche nach „"+arr[0]+"\"…";

  try {
    const results = await Promise.all(arr.map(async title => {
      // Adzuna params – "where" nur wenn angegeben
      const azParams = new URLSearchParams({what: remoteOnly ? title+" remote" : title, distance:km, country});
      if(where) azParams.set("where", where);

      // BA params – nur ohne Remote-Modus
      const baParams = new URLSearchParams({what:title, distance:km});
      if(where) baParams.set("where", where);

      const azProm = fetch("/jobs?"+azParams)
        .then(r=>r.json())
        .then(d=>({ list:(d.results||[]).map(j=>({...j,_source:"Adzuna"})), count:d.count||0 }))
        .catch(()=>({ list:[], count:0 }));

      const baProm = (!remoteOnly && country==="de")
        ? fetch("/jobs/ba?"+baParams)
            .then(r=>r.json())
            .then(d=>({ list:(d.stellenangebote||[]).map(j=>normBaJob(j,title)), count:d.maxErgebnisse||0 }))
            .catch(()=>({ list:[], count:0 }))
        : Promise.resolve({ list:[], count:0 });

      const jobicyProm = fetch("/jobs/jobicy?"+new URLSearchParams({what:title,country}))
        .then(r=>r.json())
        .then(d=>({ list:(d.jobs||[]).map(j=>normJobicyJob(j,title)), count:d.jobCount||0 }))
        .catch(()=>({ list:[], count:0 }));

      const [az, ba, jobicy] = await Promise.all([azProm, baProm, jobicyProm]);
      // Im Remote-Modus: nur Jobicy + Adzuna-Remote-Treffer; BA immer ausgefiltert
      const list = remoteOnly
        ? [...az.list.filter(j=>(j.title||"").toLowerCase().includes("remote")||(j.description||"").toLowerCase().includes("remote")||j._source==="Jobicy"), ...jobicy.list]
        : [...az.list,...ba.list,...jobicy.list];
      return { title, list, count:az.count+ba.count+jobicy.count };
    }));

    const saved = LS.saved(), ign = LS.ignored();
    const seen = new Set(), merged = [];
    let total=0, skipSaved=0, skipIgn=0;
    const cutoff = days>0 ? Date.now()-days*86400000 : 0;

    results.forEach(({title,list,count}) => {
      total += count;
      list.forEach(j => {
        if(cutoff>0 && j.created && new Date(j.created)<cutoff) return;
        const k = jobKey(j);
        if(ign.includes(k)){ skipIgn++; return; }
        if(saved[k])        { skipSaved++; return; }
        if(!seen.has(k))    { seen.add(k); merged.push({...j, _t:title}); }
      });
    });
    merged.sort((a,b)=>new Date(b.created||0)-new Date(a.created||0));

    if(skipSaved||skipIgn){
      const parts=[];
      if(skipSaved) parts.push("<b>"+skipSaved+"</b> gespeichert");
      if(skipIgn)   parts.push("<b>"+skipIgn+"</b> ignoriert");
      document.getElementById("infobx").innerHTML="ℹ️ "+parts.join(" · ")+" — nicht mehr angezeigt.";
      show("infobx");
    }

    allMerged = merged;
    renderMeta = {total, arr, where: displayWhere};
    renderPage(0);
  } catch(ex){ showErr("Fehler: "+ex.message); }

  hide("loadbox");
  document.getElementById("goBtn").disabled = false;
}

// ── Pagination ──
function renderPage(page){
  currentPage = page;
  const {total, arr, where} = renderMeta;
  const start = page * PAGE_SIZE;
  renderResults(allMerged.slice(start, start + PAGE_SIZE), total, arr, where);
  window.scrollTo({top:0, behavior:"smooth"});
}

function renderPagination(){
  const el = document.getElementById("pagination");
  const totalPages = Math.ceil(allMerged.length / PAGE_SIZE);
  if(totalPages <= 1){ el.innerHTML = ""; return; }

  const start = currentPage * PAGE_SIZE + 1;
  const end   = Math.min((currentPage + 1) * PAGE_SIZE, allMerged.length);

  let html = '<div class="pgbar">';
  html += '<button class="pgbtn" '+(currentPage===0?"disabled":"")+' onclick="renderPage('+( currentPage-1)+')">← Zurück</button>';
  html += '<span class="pginfo">Seite '+(currentPage+1)+' von '+totalPages+' &nbsp;·&nbsp; Treffer '+start+'–'+end+' von '+allMerged.length+'</span>';
  html += '<button class="pgbtn" '+(currentPage>=totalPages-1?"disabled":"")+' onclick="renderPage('+(currentPage+1)+')">Weiter →</button>';
  html += '</div>';
  el.innerHTML = html;
}

// ── Render results ──
function renderResults(jobs, total, arr, where){
  const dLabel = days===7?"letzte Woche":days===14?"letzte 2 Wochen":days===30?"letzter Monat":"alle Daten";

  if(!allMerged.length){ show("nores"); document.getElementById("pagination").innerHTML=""; }
  else {
    const hdr = document.getElementById("reshdr");
    hdr.innerHTML = "<span class='rc'>"+allMerged.length+"</span> neue Stellen &nbsp;<span class='rt'>("+total.toLocaleString("de-DE")+" gesamt · "+km+" km · "+where+" · "+dLabel+")</span>";
    show("reshdr");

    const rt = document.getElementById("restags");
    rt.innerHTML = "";
    arr.forEach(t => {
      const n = allMerged.filter(j=>j._t===t).length;
      const s = document.createElement("span"); s.className="rtag"; s.textContent=t+": "+n+" Treffer";
      rt.appendChild(s);
    });

    const list = document.getElementById("joblist");
    list.innerHTML = "";
    jobs.forEach(j => {
      const id = "j"+Math.random().toString(36).slice(2,9);
      JOBS[id] = j;
      const sal = fmtSal(j.salary_min,j.salary_max);
      const ct  = j.contract_type==="permanent"?"Festanstellung":j.contract_type==="part_time"?"Teilzeit":j.contract_type||"";
      const desc= (j.description||"").replace(/<[^>]+>/g,"").replace(/\s+/g," ").trim().slice(0,200);
      const card = document.createElement("div");
      card.className="jcard"; card.id="jw"+id;
      card.innerHTML =
        '<div class="jcard-top">'+
          '<div>'+
            '<div class="jtitle">'+esc(j.title||"")+'</div>'+
            '<div class="jco">'+esc(j.company?.display_name||"")+'</div>'+
            '<div class="jmeta">'+
              (j.location?.display_name?'<span class="jmi">📍 '+esc(j.location.display_name)+'</span>':'')+
              (ct?'<span class="jmi">💼 '+ct+'</span>':'')+
              (j.created?'<span class="jmi">🕐 '+ago(j.created)+'</span>':'')+
            '</div>'+
          '</div>'+
          '<div class="jright">'+
            '<span class="jbadge">'+(j._source||"Adzuna")+'</span>'+
            '<span class="jas">'+esc(j._t)+'</span>'+
            (sal?'<span class="jsal">'+sal+'</span>':'')+
          '</div>'+
        '</div>'+
        (desc?'<div class="jdesc">'+esc(desc)+'… <a class="jlink" href="'+esc(j.redirect_url||"")+'" target="_blank" rel="noopener">→ Öffnen</a></div>':'')+
        '<div class="jactions">'+
          '<button type="button" class="savebtn" data-id="'+id+'">💾 Speichern</button>'+
          '<button type="button" class="skipbtn" data-id="'+id+'">🚫 Ignorieren</button>'+
          '<span class="jnote">Wird bei nächster Suche ausgeblendet</span>'+
        '</div>';
      list.appendChild(card);
    });

    renderPagination();
  }

  renderPlats(arr, where);
}

// ── Delegated job list listener (once) ──
document.getElementById("joblist").addEventListener("click", e => {
  const sb = e.target.closest(".savebtn");
  const sk = e.target.closest(".skipbtn");
  if(sb){ e.stopPropagation(); saveJob(sb.dataset.id); }
  if(sk){ e.stopPropagation(); skipJob(sk.dataset.id); }
});

// ── Save / Skip ──
function saveJob(id){
  requireAuth("Zum Speichern bitte anmelden.", () => {
    const j = JOBS[id]; if(!j) return;
    const k = jobKey(j);
    const saved = LS.saved();
    if(!saved[k]){
      saved[k] = {
        key:k, title:j.title||"", company:j.company?.display_name||"",
        location:j.location?.display_name||"", url:j.redirect_url||"",
        salary_min:j.salary_min, salary_max:j.salary_max,
        contract_type:j.contract_type, created:j.created, searchedAs:j._t||"",
        savedAt:new Date().toISOString(), status:"neu", note:""
      };
      LS.setSaved(saved);
    }
    fadeOut("jw"+id);
  });
}
function skipJob(id){
  requireAuth("Zum Ignorieren bitte anmelden.", () => {
    const j = JOBS[id]; if(!j) return;
    const k = jobKey(j);
    const ign = LS.ignored();
    if(!ign.includes(k)){ ign.push(k); LS.setIgnored(ign); }
    fadeOut("jw"+id);
  });
}
function fadeOut(id){
  const el = document.getElementById(id);
  if(el){ el.style.transition="opacity .3s,transform .3s"; el.style.opacity="0"; el.style.transform="scale(0.98)"; setTimeout(()=>el.remove(),320); }
}

// ── Saved view ──
document.getElementById("sfrow").addEventListener("click", e => {
  const btn = e.target.closest(".sfbtn"); if(!btn) return;
  document.querySelectorAll(".sfbtn").forEach(b=>b.classList.remove("on"));
  btn.classList.add("on"); sfFilter=btn.dataset.s; renderSaved();
});
document.getElementById("clrIgnBtn").addEventListener("click", () => {
  if(confirm("Ignorierliste leeren? Diese Stellen erscheinen dann wieder.")) LS.setIgnored([]);
});

function renderSaved(){
  refreshBadge();
  const all = Object.values(LS.saved()).sort((a,b)=>new Date(b.savedAt)-new Date(a.savedAt));
  const list = sfFilter==="all" ? all : all.filter(j=>j.status===sfFilter);
  const el = document.getElementById("savedList");
  const empty = document.getElementById("savEmpty");
  el.innerHTML="";
  if(!list.length){ empty.style.display="block"; return; }
  empty.style.display="none";

  list.forEach(j => {
    const sal = fmtSal(j.salary_min,j.salary_max);
    const date = new Date(j.savedAt).toLocaleDateString("de-DE",{day:"2-digit",month:"2-digit",year:"numeric"});
    const cid = "sc"+Math.random().toString(36).slice(2,9);
    const card = document.createElement("div");
    card.className="scard"; card.id=cid;
    card.innerHTML =
      '<div class="scard-top">'+
        '<div class="scard-info">'+
          '<div class="sc-title"><a href="'+esc(j.url)+'" target="_blank" rel="noopener">'+esc(j.title)+'</a></div>'+
          '<div class="sc-co">'+esc(j.company)+'</div>'+
          '<div class="sc-meta">'+
            (j.location?'<span class="jmi">📍 '+esc(j.location)+'</span>':'')+
            (j.contract_type==="permanent"?'<span class="jmi">💼 Festanstellung</span>':'')+
            (sal?'<span class="jmi">💰 '+sal+'</span>':'')+
            '<span class="sc-date">Gespeichert '+date+'</span>'+
          '</div>'+
        '</div>'+
        '<div class="scard-right">'+
          '<select class="ssel" data-key="'+esc(j.key)+'">'+
            ['neu','interessant','beworben','abgelehnt','angebot'].map(s=>
              '<option value="'+s+'"'+(j.status===s?' selected':'')+'>'+
              {neu:'🔵 Neu',interessant:'⭐ Interessant',beworben:'✅ Beworben',abgelehnt:'❌ Abgelehnt',angebot:'🎉 Angebot'}[s]+'</option>'
            ).join('')+
          '</select>'+
          (sal?'<span class="jsal">'+sal+'</span>':'')+
        '</div>'+
      '</div>'+
      '<textarea class="snote" id="sn'+cid+'" placeholder="Notizen… Ansprechpartner, Gehaltswunsch, Gesprächsnotizen…" rows="3">'+esc(j.note||"")+'</textarea>'+
      '<div class="sactions">'+
        '<button type="button" class="nsavebtn" data-cid="'+cid+'" data-key="'+esc(j.key)+'">💾 Notiz speichern</button>'+
        '<span class="nhint" id="nh'+cid+'">✓ Gespeichert</span>'+
        jiraActionBtn(j)+
        '<button type="button" class="delbtn" data-cid="'+cid+'" data-key="'+esc(j.key)+'">🗑 Entfernen</button>'+
      '</div>';

    el.appendChild(card);
  });

  // Delegated events
  el.addEventListener("change", e => {
    const sel = e.target.closest(".ssel"); if(!sel) return;
    const saved = LS.saved(); if(saved[sel.dataset.key]){ saved[sel.dataset.key].status=sel.value; LS.setSaved(saved); }
  });
  el.addEventListener("click", e => {
    const nb = e.target.closest(".nsavebtn");
    const db = e.target.closest(".delbtn");
    const jb = e.target.closest(".jirabtn[data-key]");
    if(jb){ exportToJira(jb.dataset.key, jb); }
    if(nb){
      const saved=LS.saved(); const cid=nb.dataset.cid; const k=nb.dataset.key;
      const ta=document.getElementById("sn"+cid);
      if(saved[k] && ta){ saved[k].note=ta.value; LS.setSaved(saved); }
      const hint=document.getElementById("nh"+cid);
      if(hint){ hint.style.display="inline"; setTimeout(()=>hint.style.display="none",2000); }
    }
    if(db){
      const saved=LS.saved(); delete saved[db.dataset.key]; LS.setSaved(saved);
      const card=document.getElementById(db.dataset.cid);
      if(card){ card.style.opacity="0"; card.style.transition="opacity .25s"; setTimeout(()=>{ card.remove(); renderSaved(); },260); }
    }
  });
}

// ── Platforms ──
function _buildGRP(t0, l, r){
  return [
    {h:"💻 IT & Tech — Testsieger 2025",hc:"it-hdr",list:[
      {n:"Jobvector",i:"🥇",s:"#1 IT 2025",aw:1,u:()=>`https://www.jobvector.de/jobs/?q=${t0}&l=${l}&radius=${r}`},
      {n:"Heise Jobs",i:"🔴",s:"Dev & Admin",aw:0,u:()=>`https://jobs.heise.de/suche?q=${t0}&l=${l}&radius=${r}`},
      {n:"t3n Jobs",i:"🟠",s:"Digital & Tech",aw:0,u:()=>`https://t3n.de/jobs/search/?q=${t0}&location=${l}`},
      {n:"DEVjobs",i:"⚡",s:"Entwickler",aw:0,u:()=>`https://devjobs.de/jobs?q=${t0}&location=${l}`},
      {n:"GULP",i:"🔧",s:"IT-Freelance",aw:0,u:()=>`https://www.gulp.de/gulp2/g/jobs/search;q=${t0};location=${l}`},
      {n:"Computerwoche",i:"🖥️",s:"IT-Management",aw:0,u:()=>`https://jobs.computerwoche.de/suche?q=${t0}&l=${l}`},
      {n:"ITjobs.de",i:"⚙️",s:"Nur IT",aw:0,u:()=>`https://www.itjobs.de/jobs?q=${t0}&where=${l}&radius=${r}`},
      {n:"Get in IT",i:"🎯",s:"IT-Karriere",aw:0,u:()=>`https://www.get-in-it.de/jobs?q=${t0}&location=${l}`},
      {n:"Stack Overflow",i:"🔶",s:"Entwickler weltweit",aw:0,u:()=>`https://stackoverflow.com/jobs?q=${t0}&l=${l}&d=${r}&u=Km`},
      {n:"ICTJob.de",i:"📡",s:"IT & Telekom",aw:0,u:()=>`https://www.ictjob.de/jobs?keywords=${t0}&location=${l}`},
      {n:"Gallmond",i:"🎯",s:"IT Headhunter 95%",aw:1,u:()=>`https://gallmond.com/headhunter-it`},
      {n:"Wellfound",i:"🚀",s:"Startup-Jobs DE",aw:0,u:()=>`https://wellfound.com/location/germany?q=${t0}`},
      {n:"Talent.io",i:"💡",s:"Tech-Vermittlung",aw:0,u:()=>`https://www.talent.io/p/de-de/jobs?q=${t0}`},
      {n:"Welcome to Jungle",i:"🌿",s:"Modernes Jobboard",aw:0,u:()=>`https://www.welcometothejungle.com/de/jobs?query=${t0}&aroundQuery=${l}`},
    ]},
    {h:"👔 C-Level & Executive Search",hc:"ex-hdr",list:[
      {n:"Korn Ferry",i:"🌍",s:"Global #1",aw:1,u:()=>"https://www.kornferry.com/"},
      {n:"Spencer Stuart",i:"🌐",s:"Global CxO",aw:0,u:()=>"https://de.spencerstuart.com/"},
      {n:"Egon Zehnder",i:"⭐",s:"CxO & Board",aw:0,u:()=>"https://www.egonzehnder.com/de"},
      {n:"Heidrick",i:"💎",s:"Leadership",aw:0,u:()=>"https://www.heidrick.com/de/de"},
      {n:"Russell Reynolds",i:"🔹",s:"C-Suite Global",aw:0,u:()=>"https://www.russellreynolds.com/de"},
      {n:"Odgers",i:"🎯",s:"Intl. C-Level",aw:0,u:()=>"https://www.odgersberndtson.com/de/"},
      {n:"Page Executive",i:"📄",s:"CIO/CTO Europa",aw:0,u:()=>"https://www.pageexecutive.com/de/"},
      {n:"Headgate",i:"🖥️",s:"#1 IT C-Level",aw:1,u:()=>"https://head-gate.de/offene-positionen/"},
      {n:"TechMinds",i:"🤖",s:"IT C-Level 14–30d",aw:1,u:()=>"https://techminds.de/"},
      {n:"Nigel Wright",i:"🇬🇧",s:"CIO/CTO Spezialist",aw:0,u:()=>"https://www.nigelwright.com/de/"},
      {n:"CareerTeam",i:"💡",s:"Digital Executive",aw:0,u:()=>"https://www.careerteam.de/"},
      {n:"MEYHEADHUNTER",i:"⚙️",s:"3× Testsieger",aw:1,u:()=>"https://www.meyheadhunter.de/"},
      {n:"Schaffmann",i:"🏆",s:"SZ Beste 2025",aw:1,u:()=>"https://schaffmann-consultants.de/headhunter-c-level/"},
      {n:"Kienbaum",i:"🔷",s:"DACH Exec Search",aw:0,u:()=>"https://www.kienbaum.com/de/"},
      {n:"Kontrast",i:"🔌",s:"CIO/CTO seit 1993",aw:0,u:()=>"https://www.kontrast-gmbh.de/de/stellenangebote/"},
      {n:"HAPEKO",i:"🔑",s:"C-Level & IT",aw:0,u:()=>"https://www.hapeko.de/"},
      {n:"Experteer",i:"🏢",s:"ab 60k€ Portal",aw:0,u:()=>"https://www.experteer.de/"},
      {n:"LinkedIn Exec",i:"💼",s:"C-Level Filter",aw:0,u:()=>"https://www.linkedin.com/jobs/search/?f_E=5%2C6"},
      {n:"The Ladders",i:"💰",s:"100k+ Jobs",aw:0,u:()=>"https://www.theladders.com/"},
      {n:"Robert Walters",i:"🔵",s:"CIO/CTO Spezialist",aw:0,u:()=>"https://www.robertwalters.de/expertise/information-technologie/cio-cto-jobs.html"},
      {n:"Hays Executive",i:"🏗️",s:"IT Führungskräfte",aw:0,u:()=>"https://www.hays.de/"},
      {n:"Mercuri Urval",i:"🌐",s:"Global Exec Search",aw:0,u:()=>"https://www.mercuriurval.com/de-de/"},
      {n:"i-potentials",i:"⚡",s:"DACH Digital Exec",aw:0,u:()=>"https://i-potentials.de/en/executive-search/"},
    ]},
    {h:"🔍 Generelle Portale",hc:"gn-hdr",list:[
      {n:"StepStone",i:"📋",s:"#1 Generalist",aw:1,u:()=>`https://www.stepstone.de/work/ergebnisliste/?ke=${t0}&la=${l}&ws=${r}KM`},
      {n:"Indeed",i:"🔍",s:"Größte Reichweite",aw:0,u:()=>`https://de.indeed.com/jobs?q=${t0}&l=${l}&radius=${r}`},
      {n:"LinkedIn",i:"💼",s:"Netzwerk & Jobs",aw:0,u:()=>`https://www.linkedin.com/jobs/search/?keywords=${t0}&location=${l}&distance=${r}`},
      {n:"XING",i:"🤝",s:"DACH-Netzwerk",aw:0,u:()=>`https://www.xing.com/jobs/search?keywords=${t0}&location=${l}&radius=${r}`},
      {n:"Jobware",i:"🔧",s:"Top 3 Generalist",aw:1,u:()=>`https://www.jobware.de/jobsuche/?searchString=${t0}&location=${l}&distance=${r}`},
      {n:"Bundesagentur",i:"🏛️",s:"Offizielle Jobbörse",aw:0,u:()=>`https://www.arbeitsagentur.de/jobsuche/suche?was=${t0}&wo=${l}&umkreis=${r}&angebotsart=1`},
      {n:"HeyJobs",i:"✨",s:"KI-Matching #1",aw:1,u:()=>`https://www.heyjobs.co/de-de/jobs?q=${t0}&location=${l}`},
      {n:"Glassdoor",i:"🌐",s:"Bewertungen+Jobs",aw:0,u:()=>`https://www.glassdoor.de/Job/index.htm?sc.keyword=${t0}&locName=${l}`},
      {n:"Kimeta",i:"🔶",s:"Metasuche",aw:1,u:()=>`https://www.kimeta.de/jobs?q=${t0}&where=${l}&radius=${r}`},
      {n:"Jooble",i:"⚡",s:"Aggregator",aw:0,u:()=>`https://de.jooble.org/jobs-${t0}/${l}`},
      {n:"Stellenanzeigen",i:"📰",s:"3,5 Mio/Monat",aw:0,u:()=>`https://www.stellenanzeigen.de/job-suche/${t0}/?q=${t0}&lo=${l}`},
      {n:"Interamt",i:"🏛️",s:"Öffentlicher Dienst",aw:0,u:()=>`https://www.interamt.de/koop/app/stelle?WT.mc_id=1&stelle=alle&q=${t0}`},
    ]},
  ];
}

function _renderGRP(GRP, box, label){
  box.innerHTML="";
  const lbl=document.createElement("div");
  lbl.style.cssText="font-size:12px;color:#6b6b80;font-weight:600;letter-spacing:1px;text-transform:uppercase;margin-bottom:10px;";
  lbl.textContent=label;
  box.appendChild(lbl);
  GRP.forEach(g=>{
    const sec=document.createElement("div"); sec.className="platsec";
    const h=document.createElement("div"); h.className="plathdr "+g.hc; h.textContent=g.h;
    const gr=document.createElement("div"); gr.className="platgrd";
    g.list.forEach(p=>{
      const a=document.createElement("a"); a.href=p.u(); a.target="_blank"; a.rel="noopener"; a.className="plink";
      const i=document.createElement("span"); i.className="pi"; i.textContent=p.i;
      const n=document.createElement("span"); n.textContent=p.n;
      const s=document.createElement("span"); s.className="ps"; s.textContent=p.s;
      a.appendChild(i); a.appendChild(n); a.appendChild(s);
      if(p.aw){ const aw=document.createElement("span"); aw.className="paw"; aw.textContent="⭐ Testsieger"; a.appendChild(aw); }
      gr.appendChild(a);
    });
    sec.appendChild(h); sec.appendChild(gr);
    box.appendChild(sec);
  });
}

function renderPlats(arr, where){
  const t0=encodeURIComponent(arr[0]||""), l=encodeURIComponent(where), r=km;
  _renderGRP(_buildGRP(t0, l, r), document.getElementById("platbox"), "Weitersuchen — mit deiner Suche vorausgefüllt");
  show("platbox"); show("footer");
}

function renderPortalsTab(){
  const loc = document.getElementById("inpLoc").value.trim();
  const plz = document.getElementById("inpPlz").value.trim();
  const where = plz ? (loc ? plz+" "+loc : plz) : loc;
  const arr = titles.size ? Array.from(titles) : [];
  const t0 = encodeURIComponent(arr[0]||"");
  const l = encodeURIComponent(where);
  const label = (where||t0) ? "Mit aktuellen Formular-Werten vorausgefüllt" : "Alle Portale — Suchformular ausfüllen für vorausgefüllte Links";
  _renderGRP(_buildGRP(t0, l, km), document.getElementById("portalTabBox"), label);
}

// ── Utils ──
function esc(s){ const d=document.createElement("div"); d.textContent=String(s||""); return d.innerHTML; }
function show(id){ document.getElementById(id).style.display="block"; }
function hide(id){ document.getElementById(id).style.display="none"; }
function showErr(m){ document.getElementById("errbx").textContent="⚠️ "+m; show("errbx"); hide("loadbox"); }
function ago(d){
  const days=Math.round((Date.now()-new Date(d))/86400000);
  if(days===0) return "heute"; if(days===1) return "gestern";
  if(days<30) return "vor "+days+" Tagen";
  return "vor "+Math.round(days/30)+" Mon.";
}
function fmtSal(mn,mx){
  const f=n=>new Intl.NumberFormat("de-DE",{style:"currency",currency:"EUR",maximumFractionDigits:0}).format(n);
  if(mn&&mx) return f(mn)+" – "+f(mx); if(mn) return "ab "+f(mn); if(mx) return "bis "+f(mx); return null;
}

// ── Jira Integration ──
const JIRA = {
  get: () => { try{ return JSON.parse(localStorage.getItem("jf2_jira")||"{}"); }catch(e){return {};} },
  set: d => { localStorage.setItem("jf2_jira", JSON.stringify(d)); syncUserData(); }
};

function jiraConfigured(){ const c=JIRA.get(); return !!(c.domain&&c.email&&c.token&&c.project); }

function updateJiraCfgBtn(){
  const btn = document.getElementById("jiraCfgBtn");
  if(btn) btn.classList.toggle("active", jiraConfigured());
}

function openJiraSettings(){
  if(!AUTH.user){ openAuthModal("Zum Einrichten von Jira bitte anmelden."); return; }
  const c = JIRA.get();
  document.getElementById("jDomain").value    = c.domain    || "";
  document.getElementById("jEmail").value     = c.email     || "";
  document.getElementById("jToken").value     = c.token     || "";
  document.getElementById("jProject").value   = c.project   || "";
  document.getElementById("jIssueType").value   = c.issueType   || "Task";
  document.getElementById("jUrlField").value     = c.urlField     || "";
  document.getElementById("jCompanyField").value = c.companyField || "";
  document.getElementById("jUseProxy").checked   = c.useProxy !== false;
  document.getElementById("jiraFieldsBox").style.display = "none";
  document.getElementById("jiraModalStatus").innerHTML = "";
  document.getElementById("jiraModal").style.display = "flex";
}

function closeJiraSettings(){
  document.getElementById("jiraModal").style.display = "none";
}

function saveJiraSettings(){
  const domain    = document.getElementById("jDomain").value.trim().replace(/^https?:\/\//,"").replace(/\/+$/,"");
  const email     = document.getElementById("jEmail").value.trim();
  const token     = document.getElementById("jToken").value.trim();
  const project   = document.getElementById("jProject").value.trim().toUpperCase();
  const issueType    = document.getElementById("jIssueType").value.trim() || "Task";
  const urlField     = document.getElementById("jUrlField").value.trim();
  const companyField = document.getElementById("jCompanyField").value.trim();
  const useProxy     = document.getElementById("jUseProxy").checked;
  const st           = document.getElementById("jiraModalStatus");

  if(!domain||!email||!token||!project){
    st.innerHTML = '<span style="color:#ff4d6d">\u26A0\uFE0F Bitte alle Pflichtfelder ausf\u00FCller.</span>';
    return;
  }
  JIRA.set({domain, email, token, project, issueType, urlField, companyField, useProxy});
  st.innerHTML = '<span style="color:#22c55e">\u2713 Einstellungen gespeichert</span>';
  updateJiraCfgBtn();
  setTimeout(closeJiraSettings, 1200);
}

function jiraActionBtn(j){
  if(j.jiraKey){
    const cfg = JIRA.get();
    const url = cfg.domain ? "https://"+cfg.domain+"/browse/"+esc(j.jiraKey) : "#";
    return '<a href="'+url+'" target="_blank" rel="noopener" class="jirabtn ok">\u2713 '+esc(j.jiraKey)+'</a>';
  }
  return '<button type="button" class="jirabtn" data-key="'+esc(j.key)+'">\u26A1 Nach Jira</button>';
}

async function exportToJira(key, btn){
  const cfg = JIRA.get();
  if(!cfg.domain||!cfg.email||!cfg.token||!cfg.project){ openJiraSettings(); return; }

  const saved = LS.saved();
  const job   = saved[key];
  if(!job) return;

  if(btn){ btn.disabled=true; btn.textContent="\u23F3 Exportiere\u2026"; }

  const auth    = btoa(cfg.email+":"+cfg.token);
  const summary = (job.title||"Job")+" @ "+(job.company||"");

  // Atlassian Document Format (ADF)
  const para = (parts) => ({ type:"paragraph", content:parts });
  const bold = (t)     => ({ type:"text", text:t, marks:[{type:"strong"}] });
  const text = (t)     => ({ type:"text", text:t });
  const link = (t,u)   => ({ type:"text", text:t, marks:[{type:"link",attrs:{href:u}}] });

  const rows = [];
  rows.push(para([bold("Jobtitel: "),       text(job.title||"\u2013")]));
  rows.push(para([bold("Unternehmen: "),    text(job.company||"\u2013")]));
  if(job.location) rows.push(para([bold("Standort: "),      text(job.location)]));
  const sal = fmtSal(job.salary_min, job.salary_max);
  if(sal)          rows.push(para([bold("Gehalt: "),        text(sal)]));
  if(job.url)      rows.push(para([bold("Stellenanzeige: "), link(job.url, job.url)]));
  if(job.searchedAs) rows.push(para([bold("Gesucht als: "), text(job.searchedAs)]));
  if(job.note){
    rows.push({ type:"rule" });
    rows.push(para([bold("Notizen:")]));
    rows.push(para([text(job.note)]));
  }

  const fields = {
    project:     { key: cfg.project },
    summary:     summary,
    description: { type:"doc", version:1, content:rows },
    issuetype:   { name: cfg.issueType||"Task" }
  };
  if(cfg.urlField     && job.url)     fields[cfg.urlField]     = job.url;
  if(cfg.companyField && job.company) fields[cfg.companyField] = job.company;
  const useProxy = cfg.useProxy !== false;
  const apiUrl   = useProxy
    ? "/jira/issue"
    : "https://"+cfg.domain+"/rest/api/3/issue";
  const hdrs = {
    "Authorization": "Basic "+auth,
    "Content-Type":  "application/json",
    "Accept":        "application/json"
  };
  if(useProxy) hdrs["X-Jira-Domain"] = cfg.domain;

  const doFetch = (f) => fetch(apiUrl, { method:"POST", headers:hdrs, body:JSON.stringify({fields:f}) });

  function jiraErrMsg(err, status){
    if(status===401) return "Zugangsdaten ungültig — E-Mail oder API Token falsch";
    if(status===403) return "Keine Berechtigung für dieses Projekt";
    if(status===404) return "Projekt-Key nicht gefunden";
    if(err.errors && Object.keys(err.errors).length)
      return Object.entries(err.errors).map(([k,v])=>k+": "+v).join(" | ");
    return (err.errorMessages&&err.errorMessages[0]) || err.message || ("HTTP "+status);
  }

  function jiraSuccess(data, btn){
    const sv = LS.saved();
    if(sv[key]){ sv[key].jiraKey = data.key; LS.setSaved(sv); }
    if(btn){
      const url = "https://"+cfg.domain+"/browse/"+data.key;
      const a = document.createElement("a");
      a.href=url; a.target="_blank"; a.rel="noopener";
      a.className="jirabtn ok"; a.textContent="\u2713 "+data.key;
      btn.replaceWith(a);
    }
  }

  try {
    let resp = await doFetch(fields);

    // If 400 and custom fields are configured → retry without them
    if(resp.status===400 && (cfg.urlField||cfg.companyField)){
      const fallback = {...fields};
      delete fallback[cfg.urlField];
      delete fallback[cfg.companyField];
      const resp2 = await doFetch(fallback);
      if(resp2.ok){
        const data = await resp2.json();
        jiraSuccess(data, btn);
        const warn = document.createElement("div");
        warn.style.cssText = "position:fixed;bottom:1rem;right:1rem;background:#f59e0b;color:#fff;padding:.75rem 1rem;border-radius:.5rem;z-index:9999;font-size:.85rem;max-width:22rem;line-height:1.4";
        warn.textContent = "\u26A0\uFE0F Ticket erstellt, aber Custom Fields konnten nicht gesetzt werden \u2014 Felder im Jira-Screen des Issue-Typs aktivieren oder Field-IDs pr\u00FCfen";
        document.body.appendChild(warn);
        setTimeout(()=>warn.remove(), 7000);
        return;
      }
      // fallback also failed — show that error
      const err2 = await resp2.json().catch(()=>({}));
      const msg2 = jiraErrMsg(err2, resp2.status);
      if(btn){ btn.disabled=false; btn.textContent="\u26A0\uFE0F Fehler"; btn.classList.add("err"); btn.title=msg2; }
      return;
    }

    if(resp.ok){
      const data = await resp.json();
      jiraSuccess(data, btn);
    } else {
      const err = await resp.json().catch(()=>({}));
      const msg = jiraErrMsg(err, resp.status);
      if(btn){ btn.disabled=false; btn.textContent="\u26A0\uFE0F Fehler"; btn.classList.add("err"); btn.title=msg; }
    }
  } catch(ex){
    const isProxy = (JIRA.get().useProxy !== false);
    const hint = isProxy ? " (läuft server.py / Docker?)" : "";
    if(btn){ btn.disabled=false; btn.textContent="\u26A0\uFE0F Nicht erreichbar"; btn.classList.add("err"); btn.title=ex.message+hint; }
  }
}

async function loadJiraFields(){
  const domain   = document.getElementById("jDomain").value.trim().replace(/^https?:\/\//,"").replace(/\/+$/,"");
  const email    = document.getElementById("jEmail").value.trim();
  const token    = document.getElementById("jToken").value.trim();
  const project  = document.getElementById("jProject").value.trim().toUpperCase();
  const useProxy = document.getElementById("jUseProxy").checked;
  const box      = document.getElementById("jiraFieldsBox");

  if(!domain||!email||!token||!project){
    box.style.display="block";
    box.innerHTML='<span style="color:#ff4d6d">\u26A0\uFE0F Bitte zuerst Domain, E-Mail, Token und Projekt-Key eingeben.</span>';
    return;
  }
  box.style.display="block";
  box.innerHTML='<span style="color:#6b6b80">\u23F3 Lade Felder\u2026</span>';

  const auth = btoa(email+":"+token);
  const hdrs = { "Authorization":"Basic "+auth, "Accept":"application/json" };
  let url;
  if(useProxy){ url=`/jira/fields?project=${encodeURIComponent(project)}`; hdrs["X-Jira-Domain"]=domain; }
  else         { url=`https://${domain}/rest/api/3/issue/createmeta/${encodeURIComponent(project)}/issuetypes`; }

  try {
    const resp = await fetch(url, { headers:hdrs });
    const data = await resp.json().catch(()=>({}));
    if(!resp.ok){
      box.innerHTML='<span style="color:#ff4d6d">\u274C '+(data.errorMessages?.[0]||data.error||"HTTP "+resp.status)+'</span>';
      return;
    }
    // Fetch fields for first issue type
    const types = data.issueTypes || data.values || [];
    if(!types.length){ box.innerHTML='<span style="color:#6b6b80">Keine Issue-Typen gefunden.</span>'; return; }
    const typeId = types[0].id;
    const furl = useProxy
      ? `/jira/fields?project=${encodeURIComponent(project)}&issuetype=${typeId}`
      : `https://${domain}/rest/api/3/issue/createmeta/${encodeURIComponent(project)}/issuetypes/${typeId}`;
    const fr = await fetch(furl, { headers:hdrs });
    const fd = await fr.json().catch(()=>({}));
    const fieldMap = fd.fields || {};
    const rows = Object.entries(fieldMap)
      .filter(([id])=>id.startsWith("customfield_")||["summary","description","url","labels"].includes(id))
      .sort((a,b)=>(a[1].name||a[0]).localeCompare(b[1].name||b[0]));
    if(!rows.length){ box.innerHTML='<span style="color:#6b6b80">Keine Custom Fields gefunden.</span>'; return; }

    // Auto-detect URL and Unternehmen fields by name
    const urlKw     = ["url","link","webseite","website","stellenanzeige"];
    const companyKw = ["unternehmen","company","firma","arbeitgeber","organisation"];
    const urlInp     = document.getElementById("jUrlField");
    const companyInp = document.getElementById("jCompanyField");
    let autoUrl="", autoCompany="";
    for(const [id,f] of rows){
      const n = (f.name||"").toLowerCase();
      if(!autoUrl     && urlKw.some(k=>n.includes(k)))     { autoUrl=id; }
      if(!autoCompany && companyKw.some(k=>n.includes(k))) { autoCompany=id; }
    }
    const didUrl     = autoUrl     && !urlInp.value;
    const didCompany = autoCompany && !companyInp.value;
    if(didUrl)     urlInp.value     = autoUrl;
    if(didCompany) companyInp.value = autoCompany;

    const autoHint = (didUrl||didCompany)
      ? `<div style="color:#22c55e;margin-bottom:6px;">\u2713 Automatisch erkannt: ${[didUrl?"URL ("+autoUrl+")":"",didCompany?"Unternehmen ("+autoCompany+")":""].filter(Boolean).join(", ")}</div>`
      : "";

    box.innerHTML = autoHint+
      '<div style="color:#ffd166;font-weight:700;margin-bottom:6px;">Alle Felder — Klick auf ID zum Kopieren:</div>'+
      rows.map(([id,f])=>{
        const isAuto = id===autoUrl||id===autoCompany;
        return `<div style="display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid #1a1a26;${isAuto?"background:rgba(34,197,94,0.05);":""}">`+
          `<span style="color:${isAuto?"#22c55e":"#f0f0f5"};">${esc(f.name||id)}</span>`+
          `<code style="color:#ffd166;cursor:pointer;" onclick="navigator.clipboard.writeText('${id}')" title="Kopieren">${id}</code>`+
          `</div>`;
      }).join('');
  } catch(ex){
    box.innerHTML='<span style="color:#ff4d6d">\u274C Nicht erreichbar.</span>';
  }
}

async function testJiraConnection(){
  const domain   = document.getElementById("jDomain").value.trim().replace(/^https?:\/\//,"").replace(/\/+$/,"");
  const email    = document.getElementById("jEmail").value.trim();
  const token    = document.getElementById("jToken").value.trim();
  const useProxy = document.getElementById("jUseProxy").checked;
  const st       = document.getElementById("jiraModalStatus");
  const btn      = document.getElementById("jTestBtn");

  if(!domain||!email||!token){
    st.innerHTML = '<span style="color:#ff4d6d">\u26A0\uFE0F Bitte Domain, E-Mail und Token eingeben.</span>';
    return;
  }

  st.innerHTML = '<span style="color:#6b6b80">\u23F3 Teste Verbindung\u2026</span>';
  btn.disabled = true;

  const auth = btoa(email+":"+token);
  const hdrs = { "Authorization":"Basic "+auth, "Accept":"application/json" };
  let testUrl;
  if(useProxy){ testUrl="/jira/test"; hdrs["X-Jira-Domain"]=domain; }
  else         { testUrl="https://"+domain+"/rest/api/3/myself"; }

  try {
    const resp = await fetch(testUrl, { headers:hdrs });
    const data = await resp.json().catch(()=>({}));
    if(resp.ok){
      const name = data.displayName || data.emailAddress || "OK";
      st.innerHTML = '<span style="color:#22c55e">\u2713 Verbunden als: <b>'+esc(name)+'</b></span>';
    } else if(resp.status===401){
      st.innerHTML = '<span style="color:#ff4d6d">\u274C Zugangsdaten ungültig (401) — E-Mail oder API Token prüfen.</span>';
    } else {
      const msg = (data.errorMessages&&data.errorMessages[0]) || data.message || ("HTTP "+resp.status);
      st.innerHTML = '<span style="color:#ff4d6d">\u274C '+esc(msg)+'</span>';
    }
  } catch(ex){
    const hint = useProxy ? " Läuft der Docker-Container / server.py?" : "";
    st.innerHTML = '<span style="color:#ff4d6d">\u274C Nicht erreichbar.'+esc(hint)+'</span>';
  }
  btn.disabled = false;
}

// ── Auth functions ────────────────────────────────────────────────

async function checkAuth(){
  // Passwort-Reset-Token aus der URL lesen
  const params = new URLSearchParams(window.location.search);
  const resetToken = params.get("reset");
  if(resetToken){
    _resetToken = resetToken;
    _authMode   = "reset";
    _updateAuthModal();
    document.getElementById("authPw").value  = "";
    document.getElementById("authPw2").value = "";
    document.getElementById("authStatus").innerHTML = "";
    document.getElementById("authModal").style.display = "flex";
    setTimeout(()=>document.getElementById("authPw").focus(), 50);
    return; // Kein Session-Check nötig beim Reset
  }

  try {
    const r = await fetch("/auth/me", { credentials:"include" });
    const d = await r.json();
    if(d.user){
      AUTH.user = d.user;
      await loadUserData();
    }
  } catch(e) { /* Server nicht erreichbar – App funktioniert trotzdem */ }
  updateUserBar();
  refreshBadge();
  updateJiraCfgBtn();
}

function updateUserBar(){
  const bar      = document.getElementById("userBar");
  const btn      = document.getElementById("loginBtn");
  const nm       = document.getElementById("uname");
  const adminBtn = document.getElementById("adminBtn");
  if(AUTH.user){
    nm.textContent = "👤 "+AUTH.user.username;
    bar.style.display = "flex";
    btn.style.display = "none";
    adminBtn.style.display = AUTH.user.is_admin ? "" : "none";
  } else {
    bar.style.display = "none";
    btn.style.display = "";
    adminBtn.style.display = "none";
  }
}

// ── Admin Panel ──────────────────────────────────────────────────
function openAdminPanel(){
  document.getElementById("adminModal").style.display = "flex";
  loadAdminUsers();
}

function closeAdminPanel(){
  document.getElementById("adminModal").style.display = "none";
}

async function loadAdminUsers(){
  const tbody = document.getElementById("adminTbody");
  const status = document.getElementById("adminStatus");
  tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:24px;color:#6b6b80;">Wird geladen…</td></tr>';
  status.innerHTML = "";
  try {
    const r = await fetch("/admin/users", { credentials:"include" });
    if(!r.ok){ status.innerHTML = `<span class="errbx">Fehler: ${(await r.json()).error}</span>`; return; }
    const users = await r.json();
    if(!users.length){
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:24px;color:#6b6b80;">Keine Benutzer vorhanden.</td></tr>';
      return;
    }
    tbody.innerHTML = users.map(u => {
      const isSelf = u.id === AUTH.user.id;
      const date   = u.created_at ? u.created_at.slice(0,10) : "–";
      const statusBadge = u.is_locked
        ? '<span class="admin-badge locked">Gesperrt</span>'
        : '<span class="admin-badge active">Aktiv</span>';
      const adminBadge = u.is_admin
        ? '<span class="admin-badge admin">Admin</span>'
        : '<span style="color:#6b6b80;font-size:11px;">–</span>';
      const lockLabel  = u.is_locked ? "Entsperren" : "Sperren";
      const lockClass  = u.is_locked ? "admin-action ok" : "admin-action";
      return `<tr data-uid="${u.id}">
        <td style="font-weight:600">${_esc(u.username)}${isSelf ? ' <span style="color:#6b6b80;font-size:11px;">(du)</span>' : ''}</td>
        <td><input class="admin-ipt" data-field="email" value="${_esc(u.email||'')}" placeholder="–" onkeydown="if(event.key==='Enter')_adminSaveField(${u.id},this)"></td>
        <td style="color:#6b6b80">${date}</td>
        <td style="text-align:center">${adminBadge}</td>
        <td style="text-align:center">${statusBadge}</td>
        <td style="text-align:right;white-space:nowrap;display:flex;gap:6px;justify-content:flex-end;">
          <button class="admin-action ok" onclick="_adminSaveField(${u.id},this.closest('tr').querySelector('[data-field=email]'))">💾</button>
          ${!isSelf ? `<button class="${lockClass}" onclick="adminToggleLock(${u.id},${u.is_locked?0:1})">${lockLabel}</button>` : ''}
          ${!isSelf ? `<button class="admin-action" style="border-color:rgba(255,77,109,.3);color:#ff4d6d;" onclick="adminDeleteUser(${u.id},'${_esc(u.username)}')">Löschen</button>` : ''}
          ${!isSelf ? `<button class="admin-action" onclick="adminToggleAdmin(${u.id},${u.is_admin?0:1})">${u.is_admin ? 'Admin entziehen' : 'Zum Admin'}</button>` : ''}
        </td>
      </tr>`;
    }).join("");
  } catch(e){
    status.innerHTML = `<span class="errbx">Netzwerkfehler: ${e.message}</span>`;
  }
}

function _esc(s){ const d=document.createElement("div"); d.textContent=String(s||""); return d.innerHTML; }

async function _adminPatch(uid, payload){
  const r = await fetch(`/admin/users/${uid}`, {
    method:"PATCH", credentials:"include",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify(payload)
  });
  return r;
}

async function _adminSaveField(uid, input){
  const val = input.value.trim();
  const r = await _adminPatch(uid, { email: val });
  const status = document.getElementById("adminStatus");
  if(r.ok){
    status.innerHTML = '<span style="color:#22c55e">✓ E-Mail gespeichert</span>';
    setTimeout(()=>status.innerHTML="", 2500);
  } else {
    const j = await r.json();
    status.innerHTML = `<span class="errbx">${j.error}</span>`;
  }
}

async function adminToggleLock(uid, newVal){
  const r = await _adminPatch(uid, { is_locked: newVal });
  if(r.ok){ loadAdminUsers(); }
  else { const j=await r.json(); document.getElementById("adminStatus").innerHTML=`<span class="errbx">${j.error}</span>`; }
}

async function adminToggleAdmin(uid, newVal){
  if(!confirm(newVal ? "Diesem Benutzer Adminrechte geben?" : "Adminrechte entziehen?")) return;
  const r = await _adminPatch(uid, { is_admin: newVal });
  if(r.ok){ loadAdminUsers(); }
  else { const j=await r.json(); document.getElementById("adminStatus").innerHTML=`<span class="errbx">${j.error}</span>`; }
}

async function adminDeleteUser(uid, username){
  if(!confirm(`Benutzer „${username}" und alle zugehörigen Daten unwiderruflich löschen?`)) return;
  const r = await fetch(`/admin/users/${uid}`, { method:"DELETE", credentials:"include" });
  if(r.ok){ loadAdminUsers(); }
  else { const j=await r.json(); document.getElementById("adminStatus").innerHTML=`<span class="errbx">${j.error}</span>`; }
}

async function loadUserData(){
  try {
    const r = await fetch("/user/data", { credentials:"include" });
    if(!r.ok) return;
    const d = await r.json();
    localStorage.setItem("jf2_saved", JSON.stringify(d.saved   || {}));
    localStorage.setItem("jf2_ign",   JSON.stringify(d.ignored || []));
    localStorage.setItem("jf2_jira",  JSON.stringify(d.jira    || {}));
  } catch(e) {}
}

async function syncUserData(){
  if(!AUTH.user) return;
  try {
    await fetch("/user/data", {
      method:"POST", credentials:"include",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ saved:LS.saved(), ignored:LS.ignored(), jira:JIRA.get() })
    });
  } catch(e) {}
}

function requireAuth(hint, action){
  if(AUTH.user){ action(); return; }
  _pendingAction = action;
  openAuthModal(hint);
}

function openAuthModal(hint){
  _authMode = "login";
  _updateAuthModal();
  const h = document.getElementById("authHint");
  if(hint){ h.textContent = hint; h.style.display = "block"; }
  else { h.style.display = "none"; }
  document.getElementById("authStatus").innerHTML = "";
  document.getElementById("authUser").value  = "";
  document.getElementById("authEmail").value = "";
  document.getElementById("authPw").value    = "";
  document.getElementById("authPw2").value   = "";
  document.getElementById("authModal").style.display = "flex";
  setTimeout(()=>document.getElementById("authUser").focus(), 50);
}

function closeAuthModal(){
  document.getElementById("authModal").style.display = "none";
  _pendingAction = null;
}

function _updateAuthModal(){
  const m = _authMode;
  const show = (id, v) => document.getElementById(id).style.display = v ? "" : "none";
  const titles = {
    login:    "🔐 Anmelden",
    register: "🆕 Registrieren",
    forgot:   "🔑 Passwort vergessen",
    reset:    "🔒 Neues Passwort"
  };
  const subs = {
    login:    "Melde dich an, um Stellen zu speichern und Jira zu nutzen.",
    register: "Erstelle dein Konto für JobPipeline.",
    forgot:   "Gib deine E-Mail ein – du erhältst einen Reset-Link.",
    reset:    "Vergib ein neues Passwort für dein Konto."
  };
  const btnTxt = { login:"Anmelden", register:"Registrieren", forgot:"Link senden", reset:"Passwort speichern" };
  const toggleTxt = {
    login:    "Noch kein Konto? → Registrieren",
    register: "Bereits ein Konto? → Anmelden",
    forgot:   "← Zurück zur Anmeldung",
    reset:    ""
  };
  document.getElementById("authTitle").textContent     = titles[m];
  document.getElementById("authSub").textContent       = subs[m];
  document.getElementById("authSubmitBtn").textContent = btnTxt[m];
  document.getElementById("authToggle").textContent    = toggleTxt[m];
  show("authToggle",    m !== "reset");
  show("authUserWrap",  m === "login" || m === "register");
  show("authEmailWrap", m === "register" || m === "forgot");
  show("authPwWrap",    m === "login" || m === "register" || m === "reset");
  show("authPw2Wrap",   m === "register" || m === "reset");
  show("authForgotLink",m === "login");
  document.getElementById("authEmailLabel").textContent =
    m === "register" ? "✉️ E-Mail (für Passwort-Reset)" : "✉️ E-Mail-Adresse";
  document.getElementById("authPwLabel").textContent =
    m === "reset" ? "🔑 Neues Passwort" : "🔑 Passwort";
}

function toggleAuthMode(){
  _authMode = (_authMode === "login") ? "register" : "login";
  _updateAuthModal();
  document.getElementById("authStatus").innerHTML = "";
}

function switchToForgot(){
  _authMode = "forgot";
  _updateAuthModal();
  document.getElementById("authStatus").innerHTML = "";
  document.getElementById("authEmail").value = "";
  setTimeout(()=>document.getElementById("authEmail").focus(), 50);
}

async function doAuth(){
  if(_authMode === "forgot") { await doForgot(); return; }
  if(_authMode === "reset")  { await doReset();  return; }

  const username = document.getElementById("authUser").value.trim();
  const password = document.getElementById("authPw").value;
  const st  = document.getElementById("authStatus");
  const btn = document.getElementById("authSubmitBtn");
  if(!username || !password){
    st.innerHTML = '<span style="color:#ff4d6d">Bitte alle Felder ausfüllen.</span>'; return;
  }
  btn.disabled = true;

  if(_authMode === "register"){
    const pw2   = document.getElementById("authPw2").value;
    const email = document.getElementById("authEmail").value.trim();
    if(password !== pw2){
      st.innerHTML = '<span style="color:#ff4d6d">Passwörter stimmen nicht überein.</span>';
      btn.disabled = false; return;
    }
    const r = await fetch("/auth/register", {
      method:"POST", credentials:"include",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({username, password, email: email||undefined})
    }).catch(()=>null);
    if(!r){ st.innerHTML='<span style="color:#ff4d6d">Verbindungsfehler.</span>'; btn.disabled=false; return; }
    const d = await r.json();
    if(!r.ok){ st.innerHTML='<span style="color:#ff4d6d">'+esc(d.error||"Fehler")+'</span>'; btn.disabled=false; return; }
    AUTH.user = { username: d.username, is_admin: d.is_admin || false };
  } else {
    const r = await fetch("/auth/login", {
      method:"POST", credentials:"include",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({username, password})
    }).catch(()=>null);
    if(!r){ st.innerHTML='<span style="color:#ff4d6d">Verbindungsfehler.</span>'; btn.disabled=false; return; }
    const d = await r.json();
    if(!r.ok){ st.innerHTML='<span style="color:#ff4d6d">'+esc(d.error||"Fehler")+'</span>'; btn.disabled=false; return; }
    AUTH.user = { username: d.username, is_admin: d.is_admin || false };
    await loadUserData();
  }
  updateUserBar();
  refreshBadge();
  updateJiraCfgBtn();
  closeAuthModal();
  if(_pendingAction){ const fn=_pendingAction; _pendingAction=null; fn(); }
}

async function doForgot(){
  const email = document.getElementById("authEmail").value.trim();
  const st  = document.getElementById("authStatus");
  const btn = document.getElementById("authSubmitBtn");
  if(!email){ st.innerHTML='<span style="color:#ff4d6d">Bitte E-Mail eingeben.</span>'; return; }
  btn.disabled = true;
  const r = await fetch("/auth/forgot", {
    method:"POST", credentials:"include",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({email})
  }).catch(()=>null);
  btn.disabled = false;
  if(!r){ st.innerHTML='<span style="color:#ff4d6d">Verbindungsfehler.</span>'; return; }
  const d = await r.json();
  if(!r.ok){ st.innerHTML='<span style="color:#ff4d6d">'+esc(d.error||"Fehler")+'</span>'; return; }
  st.innerHTML = '<span style="color:#22c55e">✓ Falls ein Konto existiert, wurde ein Reset-Link gesendet.</span>';
  btn.disabled = true;
}

async function doReset(){
  const password = document.getElementById("authPw").value;
  const pw2      = document.getElementById("authPw2").value;
  const st  = document.getElementById("authStatus");
  const btn = document.getElementById("authSubmitBtn");
  if(!password){ st.innerHTML='<span style="color:#ff4d6d">Bitte Passwort eingeben.</span>'; return; }
  if(password !== pw2){ st.innerHTML='<span style="color:#ff4d6d">Passwörter stimmen nicht überein.</span>'; return; }
  btn.disabled = true;
  const r = await fetch("/auth/reset", {
    method:"POST", credentials:"include",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({token: _resetToken, password})
  }).catch(()=>null);
  if(!r){ st.innerHTML='<span style="color:#ff4d6d">Verbindungsfehler.</span>'; btn.disabled=false; return; }
  const d = await r.json();
  if(!r.ok){ st.innerHTML='<span style="color:#ff4d6d">'+esc(d.error||"Fehler")+'</span>'; btn.disabled=false; return; }
  st.innerHTML = '<span style="color:#22c55e">✓ Passwort gespeichert. Du kannst dich jetzt anmelden.</span>';
  _resetToken = null;
  history.replaceState({}, document.title, window.location.pathname);
  setTimeout(()=>{ _authMode="login"; _updateAuthModal(); document.getElementById("authStatus").innerHTML=""; }, 2500);
}

async function doLogout(){
  await fetch("/auth/logout", { method:"POST", credentials:"include" }).catch(()=>{});
  AUTH.user = null;
  updateUserBar();
  localStorage.removeItem("jf2_saved");
  localStorage.removeItem("jf2_ign");
  localStorage.removeItem("jf2_jira");
  refreshBadge();
  updateJiraCfgBtn();
  if(document.getElementById("tabSaved").style.display !== "none") renderSaved();
}

// ── Init ──────────────────────────────────────────────────────────
checkAuth();
