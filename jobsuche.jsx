import { useState } from "react";

const API_BASE = "http://localhost:5000/jobs";

const PLATFORMS = [
  { name: "Indeed",        emoji: "🔍", url: (t,l,r) => `https://de.indeed.com/jobs?q=${t}&l=${l}&radius=${r}` },
  { name: "StepStone",     emoji: "📋", url: (t,l,r) => `https://www.stepstone.de/work/ergebnisliste/?ke=${t}&la=${l}&ws=${r}KM` },
  { name: "LinkedIn",      emoji: "💼", url: (t,l,r) => `https://www.linkedin.com/jobs/search/?keywords=${t}&location=${l}&distance=${r}` },
  { name: "XING",          emoji: "🤝", url: (t,l,r) => `https://www.xing.com/jobs/search?keywords=${t}&location=${l}&radius=${r}` },
  { name: "Monster",       emoji: "👾", url: (t,l,r) => `https://www.monster.de/jobs/suche/?q=${t}&where=${l}&rad=${r}` },
  { name: "Bundesagentur", emoji: "🏛️", url: (t,l,r) => `https://www.arbeitsagentur.de/jobsuche/suche?was=${t}&wo=${l}&umkreis=${r}&angebotsart=1` },
  { name: "Glassdoor",     emoji: "🌐", url: (t,l,r) => `https://www.glassdoor.de/Job/index.htm?sc.keyword=${t}&locName=${l}` },
  { name: "Jooble",        emoji: "⚡", url: (t,l,r) => `https://de.jooble.org/jobs-${t}/${l}` },
];

function timeAgo(d) {
  if (!d) return "";
  const days = Math.round((Date.now() - new Date(d)) / 86400000);
  if (days === 0) return "heute";
  if (days === 1) return "gestern";
  if (days < 30) return `vor ${days} Tagen`;
  return `vor ${Math.round(days/30)} Mon.`;
}

function fmtSalary(min, max) {
  const f = n => new Intl.NumberFormat("de-DE",{style:"currency",currency:"EUR",maximumFractionDigits:0}).format(n);
  if (min && max) return `${f(min)} – ${f(max)}`;
  if (min) return `ab ${f(min)}`;
  if (max) return `bis ${f(max)}`;
  return null;
}

export default function JobFinder() {
  const [title, setTitle]       = useState("");
  const [location, setLocation] = useState("");
  const [radius, setRadius]     = useState(50);
  const [jobs, setJobs]         = useState([]);
  const [total, setTotal]       = useState(0);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState("");
  const [searched, setSearched] = useState(false);

  const encT = encodeURIComponent(title.trim());
  const encL = encodeURIComponent(location.trim());

  async function search() {
    if (!title.trim()) { setError("Bitte einen Jobtitel eingeben."); return; }
    setLoading(true); setError(""); setJobs([]); setSearched(false);

    const loc = location.toLowerCase();
    const country = loc.includes("wien")||loc.includes("österreich") ? "at"
                  : loc.includes("zürich")||loc.includes("schweiz") ? "ch" : "de";

    const params = new URLSearchParams({
      what: title.trim(), distance: radius, country,
      ...(location.trim() && { where: location.trim() })
    });

    try {
      const res  = await fetch(`${API_BASE}?${params}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data?.exception || data?.error || `HTTP ${res.status}`);
      setJobs(data.results || []);
      setTotal(data.count || 0);
      setSearched(true);
    } catch(e) {
      setError(e.message.includes("fetch") 
        ? "Server nicht erreichbar. Bitte starte start.sh und versuche es erneut."
        : "Fehler: " + e.message);
      setSearched(true);
    }
    setLoading(false);
  }

  const S = {
    app:      { fontFamily:"'Segoe UI',sans-serif", background:"#0a0a0f", minHeight:"100vh", color:"#f0f0f5", padding:"28px 16px" },
    wrap:     { maxWidth:960, margin:"0 auto" },
    logo:     { fontFamily:"Georgia,serif", fontSize:"clamp(34px,7vw,54px)", fontWeight:900, background:"linear-gradient(135deg,#ff4d6d,#ffd166)", WebkitBackgroundClip:"text", WebkitTextFillColor:"transparent", textAlign:"center", marginBottom:6 },
    tag:      { textAlign:"center", color:"#6b6b80", fontSize:12, letterSpacing:3, textTransform:"uppercase", marginBottom:28 },
    card:     { background:"#12121a", border:"1px solid #2a2a3a", borderRadius:16, padding:26, marginBottom:20, position:"relative", overflow:"hidden" },
    stripe:   { position:"absolute", top:0, left:0, right:0, height:2, background:"linear-gradient(90deg,#ff4d6d,#ffd166)" },
    g2:       { display:"grid", gridTemplateColumns:"1fr 1fr", gap:14, marginBottom:14 },
    lbl:      { display:"block", fontSize:11, letterSpacing:2, textTransform:"uppercase", color:"#6b6b80", marginBottom:7, fontWeight:600 },
    inp:      { width:"100%", background:"#0a0a0f", border:"1px solid #2a2a3a", borderRadius:10, color:"#f0f0f5", fontSize:15, padding:"13px 16px", outline:"none", boxSizing:"border-box", fontFamily:"inherit" },
    radRow:   { display:"flex", gap:8, marginBottom:16 },
    radBtn:   (a) => ({ flex:1, background:a?"rgba(255,77,109,0.15)":"#0a0a0f", border:`1px solid ${a?"#ff4d6d":"#2a2a3a"}`, borderRadius:10, color:a?"#ff4d6d":"#6b6b80", cursor:"pointer", fontSize:14, fontWeight:700, padding:"12px 0", fontFamily:"inherit" }),
    btn:      { width:"100%", background:"linear-gradient(135deg,#ff4d6d,#c9184a)", border:"none", borderRadius:10, color:"#fff", cursor:"pointer", fontSize:16, fontWeight:700, letterSpacing:1, padding:"14px 0", fontFamily:"inherit" },
    spinner:  { width:38, height:38, border:"2px solid #2a2a3a", borderTopColor:"#ff4d6d", borderRadius:"50%", margin:"40px auto 12px", animation:"spin .8s linear infinite" },
    statusTxt:{ textAlign:"center", color:"#6b6b80", paddingBottom:32 },
    errBox:   { background:"rgba(255,77,109,.1)", border:"1px solid rgba(255,77,109,.3)", borderRadius:10, color:"#ff4d6d", padding:"14px 18px", marginBottom:14, fontSize:14, lineHeight:1.6 },
    infoBox:  { background:"rgba(255,209,102,0.06)", border:"1px solid rgba(255,209,102,0.2)", borderRadius:10, color:"#a08040", padding:"12px 16px", marginBottom:20, fontSize:13, lineHeight:1.7 },
    resHdr:   { fontSize:18, fontWeight:800, marginBottom:16, display:"flex", alignItems:"center", gap:10, flexWrap:"wrap" },
    jCard:    { background:"#12121a", border:"1px solid #2a2a3a", borderRadius:12, padding:"18px 20px", marginBottom:10, textDecoration:"none", color:"inherit", display:"grid", gridTemplateColumns:"1fr auto", gap:8, transition:"all .15s" },
    jTitle:   { fontSize:16, fontWeight:700, marginBottom:3, lineHeight:1.3 },
    jCo:      { color:"#ffd166", fontSize:13, fontWeight:500, marginBottom:8 },
    jMeta:    { display:"flex", gap:14, flexWrap:"wrap" },
    meta:     { color:"#6b6b80", fontSize:12 },
    srcBadge: { background:"#1a1a26", border:"1px solid #2a2a3a", borderRadius:8, color:"#6b6b80", fontSize:10, fontWeight:700, letterSpacing:1, padding:"4px 9px", textTransform:"uppercase", whiteSpace:"nowrap" },
    sal:      { background:"rgba(255,209,102,.1)", border:"1px solid rgba(255,209,102,.3)", borderRadius:6, color:"#ffd166", fontSize:11, fontWeight:700, padding:"3px 8px", marginTop:5, textAlign:"right" },
    desc:     { gridColumn:"1/-1", color:"#6b6b80", fontSize:13, lineHeight:1.6, borderTop:"1px solid #2a2a3a", paddingTop:10, marginTop:4 },
    noRes:    { textAlign:"center", color:"#6b6b80", padding:"40px 0" },
    secCard:  { background:"#12121a", border:"1px solid #2a2a3a", borderRadius:14, padding:"22px 24px", marginTop:16 },
    secLbl:   { color:"#6b6b80", fontSize:11, letterSpacing:3, textTransform:"uppercase", marginBottom:14, fontWeight:700 },
    linkGrd:  { display:"grid", gridTemplateColumns:"repeat(auto-fill,minmax(155px,1fr))", gap:8 },
    pLink:    { background:"#0a0a0f", border:"1px solid #2a2a3a", borderRadius:10, color:"#f0f0f5", display:"block", fontSize:13, fontWeight:600, padding:"11px 14px", textAlign:"center", textDecoration:"none", transition:"all .15s" },
    footer:   { textAlign:"center", color:"#2a2a3a", fontSize:11, marginTop:20 },
  };

  return (
    <div style={S.app}>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
      <div style={S.wrap}>
        <div style={S.logo}>JobFinder</div>
        <div style={S.tag}>Live-Daten · Echte Stellen · Powered by Adzuna</div>

        <div style={S.infoBox}>
          ⚙️ <strong>Setup erforderlich:</strong> Starte einmalig <code style={{background:"#1a1a10",padding:"1px 6px",borderRadius:4}}>start.sh</code> auf deinem Computer (im Ordner <code style={{background:"#1a1a10",padding:"1px 6px",borderRadius:4}}>jobfinder/</code>) — danach läuft die Suche live.
        </div>

        <div style={S.card}>
          <div style={S.stripe}/>
          <div style={S.g2}>
            <div>
              <label style={S.lbl}>🎯 Jobtitel</label>
              <input style={S.inp} placeholder="z.B. Software Entwickler..." value={title}
                onChange={e=>setTitle(e.target.value)} onKeyDown={e=>e.key==="Enter"&&search()}/>
            </div>
            <div>
              <label style={S.lbl}>📍 Ort</label>
              <input style={S.inp} placeholder="z.B. Berlin, München..." value={location}
                onChange={e=>setLocation(e.target.value)} onKeyDown={e=>e.key==="Enter"&&search()}/>
            </div>
          </div>
          <label style={S.lbl}>📡 Umkreis</label>
          <div style={S.radRow}>
            {[50,100,125].map(r=>(
              <button key={r} style={S.radBtn(radius===r)} onClick={()=>setRadius(r)}>{r} km</button>
            ))}
          </div>
          <button style={S.btn} onClick={search} disabled={loading}>
            {loading ? "Suche läuft…" : "🔍  Echte Stellen suchen"}
          </button>
        </div>

        {error && (
          <div style={S.errBox}>
            ⚠️ {error}
            {error.includes("Server") && (
              <div style={{marginTop:10,fontSize:12,color:"#ff8080"}}>
                Terminal öffnen → in den Ordner <strong>jobfinder/</strong> wechseln → <strong>bash start.sh</strong> ausführen
              </div>
            )}
          </div>
        )}

        {loading && <><div style={S.spinner}/><div style={S.statusTxt}>Lade echte Stellenangebote…</div></>}

        {!loading && searched && jobs.length > 0 && (
          <>
            <div style={S.resHdr}>
              <span><span style={{color:"#ff4d6d"}}>{jobs.length}</span> Stellen geladen</span>
              <span style={{color:"#6b6b80",fontSize:13,fontWeight:400}}>({total.toLocaleString("de-DE")} gesamt · Umkreis {radius} km)</span>
            </div>

            {jobs.map((job,i) => {
              const salary = fmtSalary(job.salary_min, job.salary_max);
              const desc   = job.description?.replace(/<[^>]+>/g,"").replace(/\s+/g," ").trim().slice(0,220);
              const ct     = job.contract_type==="permanent"?"Festanstellung":job.contract_type==="contract"?"Befristet":job.contract_type==="part_time"?"Teilzeit":job.contract_type||"";
              return (
                <a key={i} href={job.redirect_url} target="_blank" rel="noopener" style={S.jCard}
                  onMouseEnter={e=>{e.currentTarget.style.borderColor="#ff4d6d";e.currentTarget.style.transform="translateY(-2px)"}}
                  onMouseLeave={e=>{e.currentTarget.style.borderColor="#2a2a3a";e.currentTarget.style.transform="translateY(0)"}}>
                  <div>
                    <div style={S.jTitle}>{job.title}</div>
                    <div style={S.jCo}>{job.company?.display_name}</div>
                    <div style={S.jMeta}>
                      {job.location?.display_name && <span style={S.meta}>📍 {job.location.display_name}</span>}
                      {ct && <span style={S.meta}>💼 {ct}</span>}
                      {job.created && <span style={S.meta}>🕐 {timeAgo(job.created)}</span>}
                    </div>
                  </div>
                  <div style={{display:"flex",flexDirection:"column",alignItems:"flex-end",gap:4}}>
                    <div style={S.srcBadge}>Adzuna</div>
                    {salary && <div style={S.sal}>{salary}</div>}
                  </div>
                  {desc && <div style={S.desc}>{desc}…</div>}
                </a>
              );
            })}

            <div style={S.secCard}>
              <div style={S.secLbl}>Weitersuchen auf anderen Plattformen</div>
              <div style={S.linkGrd}>
                {PLATFORMS.map(p=>(
                  <a key={p.name} href={p.url(encT,encL,radius)} target="_blank" rel="noopener" style={S.pLink}
                    onMouseEnter={e=>{e.currentTarget.style.borderColor="#ffd166";e.currentTarget.style.color="#ffd166"}}
                    onMouseLeave={e=>{e.currentTarget.style.borderColor="#2a2a3a";e.currentTarget.style.color="#f0f0f5"}}>
                    {p.emoji} {p.name}
                  </a>
                ))}
              </div>
            </div>
            <div style={S.footer}>Powered by Adzuna API</div>
          </>
        )}

        {!loading && searched && jobs.length === 0 && !error && (
          <div style={S.noRes}>😕 Keine Ergebnisse gefunden. Versuche andere Suchbegriffe.</div>
        )}
      </div>
    </div>
  );
}
