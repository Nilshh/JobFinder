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
  const GATED = ["saved", "dashboard", "portals", "watch"];
  if(GATED.includes(t) && !AUTH.user){
    _pendingAction = () => showTab(t);
    const hints = { saved:"den Merkzettel", dashboard:"das Dashboard", portals:"die Portale", watch:"den Karriere-Monitor" };
    openAuthModal("Für " + hints[t] + " ist ein Account erforderlich.");
    return;
  }
  document.getElementById("tabSearch").style.display    = t==="search"    ?"block":"none";
  document.getElementById("tabSaved").style.display     = t==="saved"     ?"block":"none";
  document.getElementById("tabDashboard").style.display = t==="dashboard" ?"block":"none";
  document.getElementById("tabPortals").style.display   = t==="portals"   ?"block":"none";
  document.getElementById("tabWatch").style.display     = t==="watch"     ?"block":"none";
  document.getElementById("tabAdmin").style.display     = t==="admin"     ?"block":"none";
  document.getElementById("tabProfile").style.display   = t==="profile"   ?"block":"none";
  document.getElementById("nb1").classList.toggle("on", t==="search");
  document.getElementById("nb2").classList.toggle("on", t==="saved");
  document.getElementById("nb5").classList.toggle("on", t==="dashboard");
  document.getElementById("nb3").classList.toggle("on", t==="portals");
  document.getElementById("nb4").classList.toggle("on", t==="watch");
  const ab = document.getElementById("adminBtn");
  if(ab) ab.classList.toggle("active", t==="admin");
  if(t==="saved")     renderSaved();
  if(t==="dashboard") renderDashboard();
  if(t==="portals")   renderPortalsTab();
  if(t==="watch")     loadWatchTab();
  if(t==="admin")     { loadAdminUsers(); loadBackupList(); }
  if(t==="profile")   loadProfileTab();
}

function hideWelcomeHero(){
  localStorage.setItem("jf2_hero_hidden", "1");
  const h = document.getElementById("welcomeHero");
  if(h) h.classList.add("hero-hidden");
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

    const saved = LS.saved(), ignSet = new Set(LS.ignored());
    const seen = new Set(), merged = [];
    let total=0, skipSaved=0, skipIgn=0;
    const cutoff = days>0 ? Date.now()-days*86400000 : 0;

    results.forEach(({title,list,count}) => {
      total += count;
      list.forEach(j => {
        if(cutoff>0 && j.created && new Date(j.created)<cutoff) return;
        const k = jobKey(j);
        if(ignSet.has(k)){ skipIgn++; return; }
        if(saved[k])     { skipSaved++; return; }
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
  _saveSearchHistory(arr, loc, plz, km, days, remoteOnly);
  renderSearchHistory();
}

// ── Suchverlauf ──
const SEARCH_HISTORY_KEY = "jf2_search_history";
const SEARCH_HISTORY_MAX = 15;

function _saveSearchHistory(titlesArr, location, plz, radius, daysVal, remote){
  const hist = _getSearchHistory();
  const entry = {titles:titlesArr, location, plz, km:radius, days:daysVal, remoteOnly:remote, ts:Date.now()};
  // Duplikat-Check: gleiche Titel + Ort → alten Eintrag ersetzen
  const key = JSON.stringify([titlesArr.sort(), location, plz, radius, remote]);
  const filtered = hist.filter(h => JSON.stringify([h.titles.sort(), h.location, h.plz, h.km, h.remoteOnly]) !== key);
  filtered.unshift(entry);
  localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(filtered.slice(0, SEARCH_HISTORY_MAX)));
}

function _getSearchHistory(){
  try { return JSON.parse(localStorage.getItem(SEARCH_HISTORY_KEY) || "[]"); } catch(e){ return []; }
}

function restoreSearch(idx){
  const hist = _getSearchHistory();
  const h = hist[idx];
  if(!h) return;
  titles.clear();
  h.titles.forEach(t => titles.add(t));
  document.querySelectorAll(".chip").forEach(c => c.classList.toggle("on", titles.has(c.dataset.t)));
  renderSelTags();
  document.getElementById("inpLoc").value = h.location || "";
  document.getElementById("inpPlz").value = h.plz || "";
  km = h.km || 50;
  document.querySelectorAll("#rrowKm .rbtn").forEach(b => b.classList.toggle("on", parseInt(b.dataset.v) === km));
  days = h.days ?? 7;
  document.querySelectorAll("#rrowDays .rbtn").forEach(b => b.classList.toggle("on", parseInt(b.dataset.v) === days));
  if(h.remoteOnly !== remoteOnly){
    remoteOnly = !!h.remoteOnly;
    document.getElementById("remoteToggle").classList.toggle("on", remoteOnly);
    document.getElementById("locOptHint").style.display = remoteOnly ? "inline" : "none";
    const rrowKm = document.getElementById("rrowKm");
    rrowKm.style.opacity = remoteOnly ? "0.35" : "1";
    rrowKm.style.pointerEvents = remoteOnly ? "none" : "";
  }
  doSearch();
}

function deleteSearchHistory(idx){
  const hist = _getSearchHistory();
  hist.splice(idx, 1);
  localStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(hist));
  renderSearchHistory();
}

function renderSearchHistory(){
  const box = document.getElementById("searchHistory");
  if(!box) return;
  const hist = _getSearchHistory();
  if(!hist.length){ box.style.display = "none"; return; }
  box.style.display = "block";
  const dLabel = d => d===7?"1W":d===14?"2W":d===30?"1M":"alle";
  box.innerHTML = '<div class="sh-hdr" onclick="this.parentElement.classList.toggle(\'sh-open\')">🕐 Letzte Suchen <span class="sh-cnt">'+hist.length+'</span> <span class="sh-toggle">▾</span></div>'
    + '<div class="sh-list">' + hist.map((h, i) => {
    const age = ago(new Date(h.ts).toISOString());
    const tags = h.titles.map(t => '<span class="sh-tag">'+esc(t)+'</span>').join("");
    const loc = h.location || h.plz || (h.remoteOnly ? "Remote" : "");
    return '<div class="sh-entry" onclick="restoreSearch('+i+')">'
      + '<div class="sh-tags">'+tags+'</div>'
      + '<div class="sh-meta">'+(loc?'📍 '+esc(loc)+' · ':'')+'📡 '+h.km+'km · 📅 '+dLabel(h.days)+' · '+age+'</div>'
      + '<button type="button" class="sh-del" onclick="event.stopPropagation();deleteSearchHistory('+i+')" title="Entfernen">×</button>'
      + '</div>';
  }).join("") + '</div>';
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
// ── Manual Add ──
document.getElementById("manualAddBtn").addEventListener("click", () => {
  requireAuth("Zum Speichern bitte anmelden.", openManualAdd);
});
document.getElementById("exportCsvBtn").addEventListener("click", exportSavedCSV);

function openManualAdd(){
  ["maUrl","maTitle","maCompany","maLocation"].forEach(id => {
    document.getElementById(id).value = "";
    document.getElementById(id).onkeydown = e => { if(e.key==="Enter") submitManualJob(); };
  });
  document.getElementById("maStatus").textContent = "";
  document.getElementById("manualAddModal").style.display = "flex";
  setTimeout(()=>document.getElementById("maTitle").focus(), 50);
}
function closeManualAdd(){
  document.getElementById("manualAddModal").style.display = "none";
}
function submitManualJob(){
  const url     = document.getElementById("maUrl").value.trim();
  const title   = document.getElementById("maTitle").value.trim();
  const company = document.getElementById("maCompany").value.trim();
  const location= document.getElementById("maLocation").value.trim();
  const status  = document.getElementById("maStatus");

  if(!title){ status.style.color="#ff4d6d"; status.textContent="⚠️ Jobtitel ist Pflicht."; return; }

  const k = (url || (title+"|"+company)).slice(0,180);
  const saved = LS.saved();
  if(saved[k]){ status.style.color="#ff4d6d"; status.textContent="⚠️ Diese Stelle ist bereits gespeichert."; return; }

  saved[k] = {
    key:k, title, company, location, url,
    salary_min:undefined, salary_max:undefined,
    contract_type:undefined, created:undefined,
    searchedAs:"manuell", savedAt:new Date().toISOString(), status:"neu", note:""
  };
  LS.setSaved(saved);
  status.style.color="#22c55e"; status.textContent="✅ Gespeichert!";
  setTimeout(closeManualAdd, 800);
  if(document.getElementById("tabSaved").style.display !== "none") renderSaved();
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

document.getElementById("addWatchBtn").addEventListener("click", () => {
  requireAuth("Bitte anmelden, um Unternehmen zu beobachten.", openWatchModal);
});
document.getElementById("markAllReadBtn").addEventListener("click", markAllWatchRead);
document.getElementById("toggleAllWatchBtn").addEventListener("click", toggleAllWatches);
document.getElementById("checkAllWatchBtn").addEventListener("click", checkAllWatches);
document.getElementById("watchSelectBtn").addEventListener("click", toggleWatchSelectMode);
document.getElementById("watchSelAllBtn").addEventListener("click", selectAllWatches);
document.getElementById("watchDeleteSelBtn").addEventListener("click", deleteSelectedWatches);
document.getElementById("csvImportBtn").addEventListener("click", () => {
  document.getElementById("watchCsvFile").click();
});

// ── Karriere-Monitor ──────────────────────────────────────────────

let _watchEditId    = null;
let _watchSelectMode = false;
let _watchSubTab     = "companies";
let _watchJobsMap    = {};   // id → job-Objekt für saveWatchJob
const _watchSelected = new Set();

function openWatchModal(prefill){
  _watchEditId = prefill?.id || null;
  document.getElementById("waName").value     = prefill?.name        || "";
  document.getElementById("waUrl").value      = prefill?.career_url  || "";
  document.getElementById("waKeywords").value = prefill?.keywords    || "";
  document.getElementById("waInterval").value = prefill?.interval    || 24;
  document.getElementById("waStatus").textContent = "";
  document.querySelector("#watchAddModal .modal-title").textContent =
    _watchEditId ? "✏️ Unternehmen bearbeiten" : "👁 Unternehmen beobachten";
  document.querySelector("#watchAddModal .msavebtn").textContent =
    _watchEditId ? "💾 Speichern" : "👁 Beobachten";
  document.getElementById("watchAddModal").style.display = "flex";
  setTimeout(() => document.getElementById("waName").focus(), 50);
}
function closeWatchModal(){
  _watchEditId = null;
  document.getElementById("watchAddModal").style.display = "none";
}

async function submitWatch(){
  const name     = document.getElementById("waName").value.trim();
  const url      = document.getElementById("waUrl").value.trim();
  const kwRaw    = document.getElementById("waKeywords").value.trim();
  const interval = parseInt(document.getElementById("waInterval").value) || 24;
  const status   = document.getElementById("waStatus");
  if(!name){ status.style.color="#ff4d6d"; status.textContent="⚠️ Name ist Pflicht."; return; }
  if(!url) { status.style.color="#ff4d6d"; status.textContent="⚠️ URL ist Pflicht."; return; }
  const keywords = kwRaw ? kwRaw.split(",").map(s=>s.trim()).filter(Boolean) : [];
  status.style.color="#6b6b80"; status.textContent="Wird gespeichert…";
  try {
    const isEdit = !!_watchEditId;
    const r = await fetch(isEdit ? `/watch/companies/${_watchEditId}` : "/watch/companies", {
      method: isEdit ? "PATCH" : "POST",
      credentials:"include",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({name, career_url:url, keywords, check_interval_hours:interval})
    });
    const j = await r.json();
    if(!r.ok){ status.style.color="#ff4d6d"; status.textContent="⚠️ "+j.error; return; }
    closeWatchModal();
    loadWatchTab();
  } catch(e){ status.style.color="#ff4d6d"; status.textContent="⚠️ "+e.message; }
}

async function loadWatchTab(){
  if(!AUTH.user){
    document.getElementById("watchCompanyList").innerHTML = '<div class="savempty">Bitte anmelden, um den Karriere-Monitor zu nutzen.</div>';
    document.getElementById("watchJobFeed").innerHTML = "";
    document.getElementById("watchGlobalKw").innerHTML = "";
    document.getElementById("watchEmpty").style.display = "none";
    return;
  }
  try {
    const [cRes, jRes, kwRes] = await Promise.all([
      fetch("/watch/companies", {credentials:"include"}),
      fetch("/watch/jobs",      {credentials:"include"}),
      fetch("/watch/keywords",  {credentials:"include"})
    ]);
    const companies = cRes.ok  ? await cRes.json()  : [];
    const jobs      = jRes.ok  ? await jRes.json()  : [];
    const kwData    = kwRes.ok ? await kwRes.json() : {keywords: []};
    renderWatchCompanies(companies);
    renderWatchJobs(jobs, companies);
    renderWatchGlobalKw(kwData.keywords || []);
    updateWatchBadge(jobs);
  } catch(e) {
    document.getElementById("watchCompanyList").innerHTML = `<div class="savempty">⚠️ Fehler: ${e.message}</div>`;
  }
}

function updateWatchBadge(jobs){
  const n   = (jobs||[]).filter(j=>j.is_new).length;
  const bdg = document.getElementById("watchBadge");
  bdg.textContent = n;
  bdg.style.display = n ? "block" : "none";
  // Sub-Tab-Label mit Gesamtanzahl
  const tc = document.getElementById("watchJobsTabCount");
  if(tc) tc.textContent = jobs.length ? ` (${jobs.length})` : "";
}

function switchWatchSubTab(tab){
  _watchSubTab = tab;
  document.getElementById("watchPaneCompanies").style.display  = tab === "companies" ? "" : "none";
  document.getElementById("watchPaneJobs").style.display       = tab === "jobs"      ? "" : "none";
  document.getElementById("watchCompanyActions").style.display = tab === "companies" ? "flex" : "none";
  document.getElementById("watchJobActions").style.display     = tab === "jobs"      ? "flex" : "none";
  document.getElementById("wst1").classList.toggle("wstab-active", tab === "companies");
  document.getElementById("wst2").classList.toggle("wstab-active", tab === "jobs");
}

// ── Globale Keywords ──────────────────────────────────────────────

let _watchGlobalKwCache = [];   // cache vermeidet Quote-Problem in onclick-Attributen

function renderWatchGlobalKw(kws){
  _watchGlobalKwCache = kws;
  const box = document.getElementById("watchGlobalKw");
  const kwHtml = kws.length
    ? kws.map(k => `<span class="watch-kw wgkw">${esc(k)}</span>`).join("")
    : '<span class="wgkw-empty">Keine globalen Suchbegriffe gesetzt</span>';
  box.innerHTML = `<div class="watch-gkw-card">
    <div class="wgkw-header">
      <div>
        <div class="wgkw-title">🌐 Globale Suchbegriffe</div>
        <div class="wgkw-sub">Gelten zusätzlich für jedes Unternehmen im Monitor</div>
      </div>
      <button class="wc-btn" id="gkwEditBtn" title="Bearbeiten">✏️</button>
    </div>
    <div class="wc-kws" style="margin-top:10px;">${kwHtml}</div>
  </div>`;
  document.getElementById("gkwEditBtn").addEventListener("click", editWatchGlobalKw);
}

function editWatchGlobalKw(){
  const box = document.getElementById("watchGlobalKw");
  box.innerHTML = `<div class="watch-gkw-card watch-gkw-edit">
    <div class="wgkw-title">🌐 Globale Suchbegriffe</div>
    <div class="wgkw-sub" style="margin-bottom:10px;">Kommagetrennte Begriffe (z. B. CTO, Head of IT, Leiter IT) – gelten für alle Unternehmen</div>
    <div style="display:flex;gap:8px;">
      <input type="text" class="inp" id="gkwInput"
             placeholder="CTO, Head of IT, Leiter IT, …" style="flex:1;">
      <button class="msavebtn" style="width:auto;padding:8px 18px;" id="gkwSaveBtn">Speichern</button>
      <button class="mcancelbtn" style="padding:8px 12px;" id="gkwCancelBtn">✕</button>
    </div>
  </div>`;
  const inp = document.getElementById("gkwInput");
  inp.value = _watchGlobalKwCache.join(", ");
  inp.focus();
  inp.addEventListener("keydown", e => { if(e.key === "Enter") saveWatchGlobalKw(); });
  document.getElementById("gkwSaveBtn").addEventListener("click", saveWatchGlobalKw);
  document.getElementById("gkwCancelBtn").addEventListener("click", () => renderWatchGlobalKw(_watchGlobalKwCache));
}

async function saveWatchGlobalKw(){
  const input = document.getElementById("gkwInput");
  if(!input) return;
  const kws = input.value.split(",").map(k => k.trim()).filter(Boolean);
  try {
    const r = await fetch("/watch/keywords", {
      method:"PATCH", credentials:"include",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({keywords: kws})
    });
    if(r.ok) renderWatchGlobalKw(kws);
  } catch(e){ /* ignore */ }
}

function renderWatchCompanies(list){
  const box = document.getElementById("watchCompanyList");
  document.getElementById("watchEmpty").style.display = list.length ? "none" : "block";
  // Schaltfläche "Alle pausieren / Alle aktivieren" anpassen
  const toggleBtn = document.getElementById("toggleAllWatchBtn");
  if(list.length){
    const allActive = list.every(c => c.active);
    toggleBtn.textContent = allActive ? "⏸ Alle pausieren" : "▶ Alle aktivieren";
  }
  // Select-Mode: Klasse + Auswahl zurücksetzen (nach Re-Render sind Checkboxen weg)
  box.classList.toggle("select-active", _watchSelectMode);
  _watchSelected.clear();
  _updateDeleteSelBtn();
  if(!list.length){ box.innerHTML = ""; return; }
  box.innerHTML = list.map(c => {
    const kw = JSON.parse(c.keywords||"[]");
    const statusDot = c.last_check_status === "ok"
      ? '<span class="sdot sdot-ok" title="Zuletzt erfolgreich geprüft"></span>'
      : c.last_check_status?.startsWith("error")
        ? `<span class="sdot sdot-err" title="${esc(c.last_check_status)}"></span>`
        : '<span class="sdot sdot-idle" title="Noch nicht geprüft"></span>';
    const lastCheck = c.last_checked_at
      ? new Date(c.last_checked_at+"Z").toLocaleString("de-DE",{dateStyle:"short",timeStyle:"short"})
      : "–";
    const kwHtml = kw.map(k=>`<span class="watch-kw">${esc(k)}</span>`).join("");
    return `<div class="watch-company-card" id="wc${c.id}">
      <div class="wc-header">
        <input type="checkbox" class="wc-check" onchange="toggleWatchSelect(${c.id},this)">
        <div class="wc-title">${statusDot}${esc(c.name)}
          ${!c.active ? '<span class="watch-paused">pausiert</span>' : ''}
        </div>
        <div class="wc-actions">
          <button class="wc-btn" onclick="doCheckNow(${c.id})" title="Jetzt prüfen">🔍</button>
          <button class="wc-btn" onclick="editWatch(${c.id})" title="Bearbeiten">✏️</button>
          <button class="wc-btn" onclick="toggleWatchActive(${c.id},${c.active?0:1})" title="${c.active?'Pausieren':'Aktivieren'}">${c.active?"⏸":"▶"}</button>
          <button class="wc-btn wc-del" onclick="deleteWatch(${c.id},'${esc(c.name).replace(/'/g,"\\'")}')">🗑</button>
        </div>
      </div>
      <div class="wc-url"><a href="${esc(c.career_url)}" target="_blank" rel="noopener">${esc(c.career_url)}</a></div>
      <div class="wc-meta">
        <span>Zuletzt geprüft: ${lastCheck}</span>
        <span>· alle ${c.check_interval_hours}h</span>
        <span>· ${c.total_jobs||0} Treffer (${c.new_jobs||0} neu)</span>
      </div>
      ${kwHtml ? `<div class="wc-kws">${kwHtml}</div>` : ""}
    </div>`;
  }).join("");
}

function renderWatchJobs(jobs, companies){
  const box = document.getElementById("watchJobFeed");
  _watchJobsMap = {};
  if(!jobs.length){ box.innerHTML = '<div class="savempty" style="padding:50px 0">Noch keine Stellen gefunden.<br><span style="font-size:13px;">Prüfe Unternehmen manuell oder warte auf die automatische Prüfung.</span></div>'; return; }
  companies.forEach(c => { /* byCompany nicht mehr nötig, company_name steckt im Job */ });
  jobs.forEach(j => _watchJobsMap[j.id] = j);
  const saved = LS.saved();
  box.innerHTML = `<div style="font-size:12px;font-weight:600;color:#6b6b80;text-transform:uppercase;letter-spacing:.06em;margin:0 0 12px;">
      Gefundene Stellen <span style="color:#444;font-weight:400">(${jobs.length})</span>
    </div>`
    + jobs.map(j => {
    const age = j.found_at
      ? new Date(j.found_at+"Z").toLocaleString("de-DE",{dateStyle:"short",timeStyle:"short"})
      : "";
    const jk = (j.url || (j.title+"|"+j.company_name)).slice(0,180);
    const isSaved = !!saved[jk];
    return `<div class="watch-job-card" id="wj${j.id}">
      <div style="display:flex;align-items:flex-start;gap:10px;">
        <div style="flex:1;min-width:0;">
          ${j.is_new ? '<span class="badge-new">Neu</span> ' : ""}
          <a class="wjob-title" href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>
          <div class="wjob-meta">${esc(j.company_name)} · ${age}</div>
        </div>
        <button class="wc-btn wjob-save-btn${isSaved?" wjob-saved":""}" onclick="saveWatchJob(${j.id})" title="${isSaved?"Bereits im Merkzettel":"Auf Merkzettel speichern"}"${isSaved?" disabled":""}>
          ${isSaved?"✓":"💾"}
        </button>
        <button class="wc-btn wc-del" onclick="dismissWatchJob(${j.id})" title="Entfernen">×</button>
      </div>
    </div>`;
  }).join("");
}

function saveWatchJob(id){
  requireAuth("Bitte anmelden, um Stellen zu speichern.", () => {
    const j = _watchJobsMap[id];
    if(!j) return;
    const k = (j.url || (j.title+"|"+j.company_name)).slice(0,180);
    const saved = LS.saved();
    if(!saved[k]){
      saved[k] = {
        key: k,
        title: j.title,
        company: j.company_name || "",
        location: "",
        url: j.url || "",
        salary_min: undefined, salary_max: undefined,
        contract_type: undefined,
        created: j.found_at || new Date().toISOString(),
        searchedAs: "Karriere-Monitor",
        savedAt: new Date().toISOString(),
        status: "neu",
        note: ""
      };
      LS.setSaved(saved);
    }
    // Button-Feedback
    const btn = document.querySelector(`#wj${id} .wjob-save-btn`);
    if(btn){ btn.textContent="✓"; btn.classList.add("wjob-saved"); btn.disabled=true; btn.title="Bereits im Merkzettel"; }
  });
}

async function doCheckNow(id){
  const btn = document.querySelector(`#wc${id} .wc-btn`);
  if(btn) btn.textContent = "⏳";
  try {
    const r = await fetch(`/watch/companies/${id}/check`, {method:"POST", credentials:"include"});
    const j = await r.json();
    if(!r.ok){ alert("Fehler: "+j.error); }
  } catch(e){ alert("Fehler: "+e.message); }
  loadWatchTab();
}

async function toggleWatchActive(id, val){
  await fetch(`/watch/companies/${id}`, {
    method:"PATCH", credentials:"include",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({active: val})
  });
  loadWatchTab();
}

async function deleteWatch(id, name){
  if(!confirm(`Beobachtung von „${name}" und alle gefundenen Stellen löschen?`)) return;
  await fetch(`/watch/companies/${id}`, {method:"DELETE", credentials:"include"});
  loadWatchTab();
}

async function editWatch(id){
  const r = await fetch("/watch/companies", {credentials:"include"});
  if(!r.ok) return;
  const list = await r.json();
  const c = list.find(x => x.id === id);
  if(!c) return;
  openWatchModal({
    id:       c.id,
    name:     c.name,
    career_url: c.career_url,
    keywords: JSON.parse(c.keywords||"[]").join(", "),
    interval: c.check_interval_hours
  });
}

async function dismissWatchJob(id){
  await fetch(`/watch/jobs/${id}`, {method:"DELETE", credentials:"include"});
  document.getElementById("wj"+id)?.remove();
}

async function markAllWatchRead(){
  await fetch("/watch/jobs/read-all", {method:"POST", credentials:"include"});
  loadWatchTab();
}

async function checkAllWatches(){
  const btn  = document.getElementById("checkAllWatchBtn");
  const stat = document.getElementById("watchCheckStatus");
  btn.disabled = true;

  const setStatus = html => { stat.innerHTML = html; stat.style.display = ""; };

  try {
    const r = await fetch("/watch/companies", {credentials:"include"});
    if(!r.ok){ btn.disabled = false; return; }
    const list   = await r.json();
    const active = list.filter(c => c.active);
    if(!active.length){
      setStatus('<span class="wcs-info">Keine aktiven Unternehmen vorhanden.</span>');
      btn.disabled = false;
      setTimeout(() => { stat.style.display = "none"; }, 2500);
      return;
    }

    let errors = 0;
    for(let i = 0; i < active.length; i++){
      const c   = active[i];
      const pct = Math.round((i / active.length) * 100);
      btn.textContent = `⏳ ${i+1}/${active.length}`;
      setStatus(`<div class="wcs-wrap">
        <div class="wcs-bar-track"><div class="wcs-bar" style="width:${pct}%"></div></div>
        <div class="wcs-label">Prüfe <strong>${c.name}</strong> … (${i+1} von ${active.length})</div>
      </div>`);
      try {
        await fetch(`/watch/companies/${c.id}/check`, {method:"POST", credentials:"include"});
      } catch(e){ errors++; }
    }

    const done = `<div class="wcs-wrap">
      <div class="wcs-bar-track"><div class="wcs-bar" style="width:100%"></div></div>
      <div class="wcs-label ${errors ? "wcs-warn" : "wcs-ok"}">
        ${errors ? `⚠️ ${active.length} geprüft, ${errors} mit Fehler.` : `✓ Alle ${active.length} Unternehmen erfolgreich geprüft.`}
      </div></div>`;
    setStatus(done);
    setTimeout(() => { stat.style.display = "none"; }, 4000);
  } catch(e){
    setStatus(`<span class="wcs-warn">⚠️ Fehler: ${e.message}</span>`);
  }

  btn.textContent = "🔍 Alle prüfen";
  btn.disabled = false;
  loadWatchTab();
}

async function toggleAllWatches(){
  const r = await fetch("/watch/companies", {credentials:"include"});
  if(!r.ok) return;
  const list = await r.json();
  if(!list.length) return;
  // Alle aktiv → alle pausieren; sonst alle aktivieren
  const allActive = list.every(c => c.active);
  const newVal = allActive ? 0 : 1;
  const btn = document.getElementById("toggleAllWatchBtn");
  btn.textContent = "⏳";
  await Promise.all(list.map(c =>
    fetch(`/watch/companies/${c.id}`, {
      method:"PATCH", credentials:"include",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({active: newVal})
    })
  ));
  loadWatchTab();
}

function toggleWatchSelectMode(){
  _watchSelectMode = !_watchSelectMode;
  _watchSelected.clear();
  const btn    = document.getElementById("watchSelectBtn");
  const selAll = document.getElementById("watchSelAllBtn");
  const delBtn = document.getElementById("watchDeleteSelBtn");
  if(_watchSelectMode){
    btn.textContent = "✕ Abbrechen";
    btn.style.color = "#ff4d6d";
    selAll.style.display = "";
    delBtn.style.display = "";
  } else {
    btn.textContent = "☑ Auswählen";
    btn.style.color = "";
    selAll.style.display = "none";
    delBtn.style.display = "none";
  }
  document.getElementById("watchCompanyList").classList.toggle("select-active", _watchSelectMode);
  _updateDeleteSelBtn();
}

function toggleWatchSelect(id, cb){
  if(cb.checked) _watchSelected.add(id);
  else _watchSelected.delete(id);
  document.getElementById(`wc${id}`).classList.toggle("wc-selected", cb.checked);
  _updateDeleteSelBtn();
}

function selectAllWatches(){
  document.querySelectorAll(".watch-company-card").forEach(card => {
    const cb = card.querySelector(".wc-check");
    if(!cb) return;
    cb.checked = true;
    const id = parseInt(card.id.replace("wc",""));
    _watchSelected.add(id);
    card.classList.add("wc-selected");
  });
  _updateDeleteSelBtn();
}

function _updateDeleteSelBtn(){
  const btn = document.getElementById("watchDeleteSelBtn");
  const n   = _watchSelected.size;
  btn.textContent = `🗑 Löschen (${n})`;
  btn.disabled    = n === 0;
}

async function deleteSelectedWatches(){
  if(!_watchSelected.size) return;
  const n = _watchSelected.size;
  if(!confirm(`${n} Unternehmen löschen? Diese Aktion kann nicht rückgängig gemacht werden.`)) return;
  await Promise.all([..._watchSelected].map(id =>
    fetch(`/watch/companies/${id}`, {method:"DELETE", credentials:"include"})
  ));
  // Select-Mode beenden
  _watchSelectMode = false;
  _watchSelected.clear();
  document.getElementById("watchSelectBtn").textContent = "☑ Auswählen";
  document.getElementById("watchSelectBtn").style.color = "";
  document.getElementById("watchSelAllBtn").style.display  = "none";
  document.getElementById("watchDeleteSelBtn").style.display = "none";
  loadWatchTab();
}

function downloadWatchTemplate(){
  const content = [
    "# Vorlage für den Karriere-Monitor Import",
    "# Format: Name;URL;Keywords(kommagetrennt);Intervall_Stunden",
    "# - Name und URL sind Pflichtfelder",
    "# - Keywords: kommagetrennte Suchbegriffe (nach denen auf der Karriereseite gesucht wird)",
    "# - Intervall: Prüfhäufigkeit in Stunden (Standard: 24, Maximum: 168 = 1 Woche)",
    "# Zeilen die mit # beginnen werden ignoriert",
    "#",
    "Name;URL;Keywords;Intervall",
    "SAP SE;https://jobs.sap.com/search;CTO,Head of IT,Director;24",
    "BMW Group;https://www.bmwgroup.com/de/karriere.html;CTO,VP Engineering,Leiter IT;48",
    "Deutsche Bank;https://careers.db.com/professionals/search-roles/;CDO,CTO,Head of Technology;24",
  ].join("\r\n");
  const blob = new Blob(["\uFEFF"+content], {type:"text/csv;charset=utf-8"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "karriere-monitor-vorlage.csv";
  a.click();
  URL.revokeObjectURL(a.href);
}

function exportSavedCSV(){
  const all = Object.values(LS.saved());
  if(!all.length){ alert("Keine Stellen zum Exportieren vorhanden."); return; }
  const statusMap = {neu:"Neu",interessant:"Interessant",beworben:"Beworben",abgelehnt:"Abgelehnt",angebot:"Angebot"};
  const csvEsc = v => { const s = String(v||"").replace(/"/g,'""'); return s.includes(";") || s.includes('"') || s.includes("\n") ? '"'+s+'"' : s; };
  const header = "Jobtitel;Unternehmen;Standort;URL;Status;Gehalt;Gespeichert am;Notizen";
  const rows = all.map(j => {
    const sal = fmtSal(j.salary_min, j.salary_max) || "";
    const date = j.savedAt ? new Date(j.savedAt).toLocaleDateString("de-DE") : "";
    return [j.title, j.company, j.location, j.url, statusMap[j.status]||j.status, sal, date, j.note]
      .map(csvEsc).join(";");
  });
  const csv = [header, ...rows].join("\r\n");
  const blob = new Blob(["\uFEFF"+csv], {type:"text/csv;charset=utf-8"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  const ts = new Date().toISOString().slice(0,10);
  a.download = `jobpipeline-merkzettel-${ts}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

async function importWatchCSV(input){
  const file = input.files[0];
  input.value = "";
  if(!file) return;
  requireAuth("Bitte anmelden, um Unternehmen zu importieren.", async () => {
    const text = await file.text();
    // Zeilen aufteilen, leere + Kommentare überspringen
    const lines = text.split(/\r?\n/).map(l => l.trim()).filter(l => l && !l.startsWith("#"));
    if(!lines.length){ alert("CSV ist leer."); return; }

    // Kopfzeile erkennen: erste Zeile ist Header wenn sie keine URL enthält
    const firstCols = lines[0].split(";");
    const hasHeader = !firstCols[1]?.trim().startsWith("http");
    const rows = hasHeader ? lines.slice(1) : lines;
    if(!rows.length){ alert("Keine Datenzeilen gefunden."); return; }

    // Format: Name;URL;Keywords;Intervall(optional)
    let ok = 0, skip = 0, errors = [];
    for(const line of rows){
      const [name, url, kwRaw, intervalRaw] = line.split(";").map(s => s.trim());
      if(!name || !url || !url.startsWith("http")){ skip++; continue; }
      const keywords = kwRaw ? kwRaw.split(",").map(k => k.trim()).filter(Boolean) : [];
      const interval = parseInt(intervalRaw) || 24;
      try {
        const r = await fetch("/watch/companies", {
          method:"POST", credentials:"include",
          headers:{"Content-Type":"application/json"},
          body: JSON.stringify({name, career_url:url, keywords, check_interval_hours:interval})
        });
        if(r.ok) ok++; else { const j=await r.json(); errors.push(`${name}: ${j.error}`); }
      } catch(e){ errors.push(`${name}: ${e.message}`); }
    }

    let msg = `✅ ${ok} Unternehmen importiert.`;
    if(skip)   msg += ` ${skip} Zeilen übersprungen (fehlende Felder).`;
    if(errors.length) msg += `\n⚠️ Fehler:\n${errors.join("\n")}`;
    alert(msg);
    loadWatchTab();
  });
}

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

// ── Dashboard ──
function renderDashboard(){
  const all = Object.values(LS.saved());
  const box = document.getElementById("dashContent");
  const empty = document.getElementById("dashEmpty");
  if(!all.length){ box.innerHTML = ""; empty.style.display = "block"; return; }
  empty.style.display = "none";

  // Kennzahlen
  const counts = {neu:0, interessant:0, beworben:0, abgelehnt:0, angebot:0};
  all.forEach(j => { if(counts[j.status] !== undefined) counts[j.status]++; });
  const total = all.length;
  const applied = counts.beworben + counts.abgelehnt + counts.angebot;
  const rate = applied > 0 ? Math.round((counts.angebot / applied) * 100) : 0;

  // Timeline: Jobs pro Woche (letzte 8 Wochen)
  const weeks = [];
  const now = Date.now();
  for(let i = 7; i >= 0; i--){
    const wStart = now - (i+1) * 7 * 86400000;
    const wEnd   = now - i * 7 * 86400000;
    const label  = new Date(wEnd).toLocaleDateString("de-DE", {day:"2-digit", month:"2-digit"});
    const count  = all.filter(j => { const t = new Date(j.savedAt).getTime(); return t >= wStart && t < wEnd; }).length;
    weeks.push({label, count});
  }
  const maxW = Math.max(...weeks.map(w => w.count), 1);

  // Top-Unternehmen
  const compMap = {};
  all.forEach(j => { const c = j.company || "Unbekannt"; compMap[c] = (compMap[c]||0) + 1; });
  const topCompanies = Object.entries(compMap).sort((a,b) => b[1]-a[1]).slice(0, 5);
  const maxC = topCompanies.length ? topCompanies[0][1] : 1;

  const statusColors = {neu:"#4da3ff", interessant:"#ffd166", beworben:"#22c55e", abgelehnt:"#ff4d6d", angebot:"#c084fc"};
  const statusLabels = {neu:"Neu", interessant:"Interessant", beworben:"Beworben", abgelehnt:"Abgelehnt", angebot:"Angebot"};

  box.innerHTML =
    // KPI-Karten
    '<div class="dash-kpis">'
    + '<div class="dash-kpi"><div class="dash-kpi-n">'+total+'</div><div class="dash-kpi-l">Gespeichert</div></div>'
    + '<div class="dash-kpi"><div class="dash-kpi-n" style="color:#22c55e">'+counts.beworben+'</div><div class="dash-kpi-l">Beworben</div></div>'
    + '<div class="dash-kpi"><div class="dash-kpi-n" style="color:#c084fc">'+counts.angebot+'</div><div class="dash-kpi-l">Angebote</div></div>'
    + '<div class="dash-kpi"><div class="dash-kpi-n" style="color:#ff4d6d">'+counts.abgelehnt+'</div><div class="dash-kpi-l">Abgelehnt</div></div>'
    + '<div class="dash-kpi"><div class="dash-kpi-n" style="color:#ffd166">'+rate+'%</div><div class="dash-kpi-l">Erfolgsquote</div></div>'
    + '</div>'

    // Status-Verteilung
    + '<div class="dash-card"><div class="dash-card-title">Status-Verteilung</div>'
    + '<div class="dash-bar-stack">'
    + Object.entries(counts).filter(([,v])=>v>0).map(([s,v]) =>
        '<div class="dash-bar-seg" style="flex:'+v+';background:'+statusColors[s]+'" title="'+statusLabels[s]+': '+v+'"></div>'
      ).join("")
    + '</div>'
    + '<div class="dash-bar-legend">'
    + Object.entries(counts).map(([s,v]) =>
        '<span class="dash-leg"><span class="dash-leg-dot" style="background:'+statusColors[s]+'"></span>'+statusLabels[s]+' ('+v+')</span>'
      ).join("")
    + '</div></div>'

    // Timeline
    + '<div class="dash-card"><div class="dash-card-title">Gespeichert pro Woche</div>'
    + '<div class="dash-timeline">'
    + weeks.map(w =>
        '<div class="dash-tw">'
        + '<div class="dash-tw-bar" style="height:'+Math.max(Math.round((w.count/maxW)*100), w.count?8:0)+'%"></div>'
        + '<div class="dash-tw-n">'+(w.count||"")+'</div>'
        + '<div class="dash-tw-l">'+w.label+'</div>'
        + '</div>'
      ).join("")
    + '</div></div>'

    // Top-Unternehmen
    + '<div class="dash-card"><div class="dash-card-title">Top-Unternehmen</div>'
    + (topCompanies.length ? topCompanies.map(([name, cnt]) =>
        '<div class="dash-comp">'
        + '<div class="dash-comp-name">'+esc(name)+'</div>'
        + '<div class="dash-comp-bar-wrap"><div class="dash-comp-bar" style="width:'+Math.round((cnt/maxC)*100)+'%"></div></div>'
        + '<div class="dash-comp-cnt">'+cnt+'</div>'
        + '</div>'
      ).join("") : '<div style="color:#555570;font-size:13px;">Keine Daten</div>')
    + '</div>';
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

function updateJiraCfgBtn(){ /* Jira-Button wurde in Profil-Tab integriert */ }

function openJiraSettings(){
  if(!AUTH.user){ openAuthModal("Für die Jira-Einstellungen ist ein Account erforderlich."); return; }
  showTab("profile");
}

function closeJiraSettings(){ /* noop – Jira-Einstellungen sind jetzt im Profil-Tab */ }

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
  if(localStorage.getItem("jf2_hero_hidden")){
    const h = document.getElementById("welcomeHero");
    if(h) h.classList.add("hero-hidden");
  }
}

function updateUserBar(){
  const bar      = document.getElementById("userBar");
  const btn      = document.getElementById("loginBtn");
  const nm       = document.getElementById("uname");
  const adminBtn = document.getElementById("adminBtn");
  if(AUTH.user){
    nm.textContent = AUTH.user.username;
    bar.style.display = "flex";
    btn.style.display = "none";
    adminBtn.style.display = AUTH.user.is_admin ? "" : "none";
  } else {
    bar.style.display = "none";
    btn.style.display = "";
    adminBtn.style.display = "none";
  }
}

// ── Profil ───────────────────────────────────────────────────────
function loadProfileTab(){
  if(!AUTH.user) return;
  document.getElementById("profileUser").value  = AUTH.user.username;
  document.getElementById("profileEmail").value = AUTH.user.email || "";
  document.getElementById("pwCurrent").value = "";
  document.getElementById("pwNew").value     = "";
  document.getElementById("pwConfirm").value = "";
  document.getElementById("profileStatus").innerHTML = "";
  document.getElementById("pwStatus").innerHTML      = "";
  document.getElementById("jiraModalStatus").innerHTML = "";
  const c = JIRA.get();
  document.getElementById("jDomain").value       = c.domain      || "";
  document.getElementById("jEmail").value        = c.email       || "";
  document.getElementById("jToken").value        = c.token       || "";
  document.getElementById("jProject").value      = c.project     || "";
  document.getElementById("jIssueType").value    = c.issueType   || "Task";
  document.getElementById("jUrlField").value     = c.urlField    || "";
  document.getElementById("jCompanyField").value = c.companyField|| "";
  document.getElementById("jUseProxy").checked   = c.useProxy !== false;
  const fb = document.getElementById("jiraFieldsBox");
  if(fb) fb.style.display = "none";
  document.getElementById("notifyStatus").innerHTML = "";
  loadNotifySettings();
}

async function loadNotifySettings(){
  try {
    const r = await fetch("/user/notifications", {credentials:"include"});
    if(!r.ok) return;
    const d = await r.json();
    document.getElementById("notifyEnabled").checked    = d.enabled;
    document.getElementById("notifyFrequency").value    = d.frequency || "instant";
  } catch(e){}
}

async function saveNotifySettings(){
  const enabled   = document.getElementById("notifyEnabled").checked;
  const frequency = document.getElementById("notifyFrequency").value;
  const status    = document.getElementById("notifyStatus");
  status.innerHTML = '<span style="color:#6b6b80">Wird gespeichert…</span>';
  try {
    const r = await fetch("/user/notifications", {
      method:"PATCH", credentials:"include",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({enabled, frequency})
    });
    if(r.ok){
      status.innerHTML = '<span style="color:#22c55e">✓ Gespeichert.</span>';
      setTimeout(()=>{ status.innerHTML=""; }, 2500);
    } else {
      const d = await r.json();
      status.innerHTML = '<span style="color:#ff4d6d">'+esc(d.error||"Fehler")+'</span>';
    }
  } catch(e){
    status.innerHTML = '<span style="color:#ff4d6d">Verbindungsfehler.</span>';
  }
}

async function saveProfile(){
  const email  = document.getElementById("profileEmail").value.trim();
  const status = document.getElementById("profileStatus");
  status.innerHTML = '<span style="color:#6b6b80">Wird gespeichert…</span>';
  const r = await fetch("/user/profile", {
    method:"PATCH", credentials:"include",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({email})
  }).catch(()=>null);
  if(!r){ status.innerHTML = '<span style="color:#ff4d6d">Verbindungsfehler.</span>'; return; }
  const d = await r.json();
  if(d.ok){
    AUTH.user.email = d.email;
    status.innerHTML = '<span style="color:#22c55e">✓ Gespeichert.</span>';
    setTimeout(()=>{ status.innerHTML=""; }, 2500);
  } else {
    status.innerHTML = '<span style="color:#ff4d6d">'+esc(d.error||"Fehler")+'</span>';
  }
}

async function savePassword(){
  const current = document.getElementById("pwCurrent").value;
  const newPw   = document.getElementById("pwNew").value;
  const confirm = document.getElementById("pwConfirm").value;
  const status  = document.getElementById("pwStatus");
  if(!current){ status.innerHTML='<span style="color:#ff4d6d">Bitte aktuelles Passwort eingeben.</span>'; return; }
  if(newPw.length < 8){ status.innerHTML='<span style="color:#ff4d6d">Neues Passwort muss mindestens 8 Zeichen haben.</span>'; return; }
  if(newPw !== confirm){ status.innerHTML='<span style="color:#ff4d6d">Passwörter stimmen nicht überein.</span>'; return; }
  status.innerHTML = '<span style="color:#6b6b80">Wird gespeichert…</span>';
  const r = await fetch("/user/password", {
    method:"POST", credentials:"include",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({current, "new": newPw})
  }).catch(()=>null);
  if(!r){ status.innerHTML = '<span style="color:#ff4d6d">Verbindungsfehler.</span>'; return; }
  const d = await r.json();
  if(d.ok){
    document.getElementById("pwCurrent").value = "";
    document.getElementById("pwNew").value     = "";
    document.getElementById("pwConfirm").value = "";
    status.innerHTML = '<span style="color:#22c55e">✓ Passwort geändert.</span>';
    setTimeout(()=>{ status.innerHTML=""; }, 2500);
  } else {
    status.innerHTML = '<span style="color:#ff4d6d">'+esc(d.error||"Fehler")+'</span>';
  }
}

// ── Admin Panel ──────────────────────────────────────────────────
function openAdminPanel(){ showTab("admin"); }
function closeAdminPanel(){ showTab("search"); }

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
        <td style="font-weight:600">${esc(u.username)}${isSelf ? ' <span style="color:#6b6b80;font-size:11px;">(du)</span>' : ''}</td>
        <td><input class="admin-ipt" data-field="email" value="${esc(u.email||'')}" placeholder="–" onkeydown="if(event.key==='Enter')_adminSaveField(${u.id},this)"></td>
        <td style="color:#6b6b80">${date}</td>
        <td style="text-align:center">${adminBadge}</td>
        <td style="text-align:center">${statusBadge}</td>
        <td style="text-align:right;white-space:nowrap;display:flex;gap:6px;justify-content:flex-end;">
          <button class="admin-action ok" onclick="_adminSaveField(${u.id},this.closest('tr').querySelector('[data-field=email]'))">💾</button>
          ${!isSelf ? `<button class="${lockClass}" onclick="adminToggleLock(${u.id},${u.is_locked?0:1})">${lockLabel}</button>` : ''}
          ${!isSelf ? `<button class="admin-action" style="border-color:rgba(255,77,109,.3);color:#ff4d6d;" onclick="adminDeleteUser(${u.id},'${esc(u.username)}')">Löschen</button>` : ''}
          ${!isSelf ? `<button class="admin-action" onclick="adminToggleAdmin(${u.id},${u.is_admin?0:1})">${u.is_admin ? 'Admin entziehen' : 'Zum Admin'}</button>` : ''}
        </td>
      </tr>`;
    }).join("");
  } catch(e){
    status.innerHTML = `<span class="errbx">Netzwerkfehler: ${e.message}</span>`;
  }
}

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

async function doBackup(){
  const status = document.getElementById("backupStatus");
  status.textContent = "Wird erstellt…";
  try {
    const r = await fetch("/admin/backup", { credentials:"include" });
    if(!r.ok){ const j=await r.json(); status.textContent="⚠️ "+j.error; return; }
    const data = await r.json();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type:"application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const ts = new Date().toISOString().slice(0,16).replace("T","_").replace(/:/g,"-");
    a.href = url;
    a.download = `jobpipeline-backup-${ts}.json`;
    a.click();
    URL.revokeObjectURL(url);
    status.textContent = `✅ ${data.users.length} Benutzer gesichert`;
  } catch(e) {
    status.textContent = "⚠️ Fehler: "+e.message;
  }
}

async function doRestore(input){
  const file = input.files[0];
  input.value = "";
  if(!file) return;
  const status = document.getElementById("backupStatus");
  if(!confirm(`Backup „${file.name}" einspielen? Alle aktuellen Daten werden überschrieben und du wirst abgemeldet.`)) return;
  status.textContent = "Wird eingespielt…";
  try {
    const text = await file.text();
    const data = JSON.parse(text);
    const r = await fetch("/admin/restore", {
      method:"POST", credentials:"include",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify(data)
    });
    const j = await r.json();
    if(!r.ok){ status.textContent="⚠️ "+j.error; return; }
    status.textContent = `✅ ${j.users} Benutzer wiederhergestellt – bitte neu anmelden`;
    setTimeout(()=>{ AUTH.user=null; updateUserBar(); closeAdminPanel(); }, 2000);
  } catch(e) {
    status.textContent = "⚠️ Fehler: "+e.message;
  }
}

async function doManualBackup(){
  const status = document.getElementById("backupStatus");
  status.textContent = "Backup wird erstellt…";
  try {
    const r = await fetch("/admin/backups/trigger", { method:"POST", credentials:"include" });
    const j = await r.json();
    if(!r.ok){ status.textContent="⚠️ "+j.error; return; }
    status.textContent = `✅ ${j.file} erstellt`;
    loadBackupList();
  } catch(e) {
    status.textContent = "⚠️ Fehler: "+e.message;
  }
}

async function loadBackupList(){
  const box = document.getElementById("backupList");
  box.textContent = "Lade…";
  try {
    const r = await fetch("/admin/backups", { credentials:"include" });
    if(!r.ok){ box.textContent = "Keine Backups gefunden."; return; }
    const files = await r.json();
    if(!files.length){ box.innerHTML = '<span style="color:#444">Noch keine automatischen Backups vorhanden.</span>'; return; }
    const fmt = iso => iso.replace("T"," ").slice(0,16)+" UTC";
    const fmtSize = b => b < 1024 ? b+"B" : b < 1048576 ? (b/1024).toFixed(1)+"KB" : (b/1048576).toFixed(1)+"MB";
    box.innerHTML = '<table style="width:100%;border-collapse:collapse;">'
      + files.map(f=>`<tr style="border-top:1px solid #1e1e30;">
          <td style="padding:6px 4px;">${f.name}</td>
          <td style="padding:6px 4px;color:#888;white-space:nowrap;">${fmt(f.mtime)}</td>
          <td style="padding:6px 4px;color:#888;text-align:right;white-space:nowrap;">${fmtSize(f.size)}</td>
          <td style="padding:6px 4px;text-align:right;white-space:nowrap;">
            <a href="/admin/backups/${encodeURIComponent(f.name)}" download="${f.name}"
               style="color:#ffd166;text-decoration:none;font-size:11px;">⬇ herunterladen</a>
          </td>
        </tr>`).join("")
      + '</table>';
  } catch(e) {
    box.textContent = "⚠️ Fehler: "+e.message;
  }
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

let _syncTimer = null;
function syncUserData(){
  if(!AUTH.user) return;
  clearTimeout(_syncTimer);
  _syncTimer = setTimeout(async () => {
    try {
      await fetch("/user/data", {
        method:"POST", credentials:"include",
        headers:{"Content-Type":"application/json"},
        body: JSON.stringify({ saved:LS.saved(), ignored:LS.ignored(), jira:JIRA.get() })
      });
    } catch(e) {}
  }, 1000);
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
    AUTH.user = { username: d.username, is_admin: d.is_admin || false, email: d.email || "" };
  } else {
    const r = await fetch("/auth/login", {
      method:"POST", credentials:"include",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({username, password})
    }).catch(()=>null);
    if(!r){ st.innerHTML='<span style="color:#ff4d6d">Verbindungsfehler.</span>'; btn.disabled=false; return; }
    const d = await r.json();
    if(!r.ok){ st.innerHTML='<span style="color:#ff4d6d">'+esc(d.error||"Fehler")+'</span>'; btn.disabled=false; return; }
    AUTH.user = { username: d.username, is_admin: d.is_admin || false, email: d.email || "" };
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
  showTab("search");
}

// ── Init ──────────────────────────────────────────────────────────
checkAuth();
renderSearchHistory();
