SETTINGS_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>连接与导入 · 暨南大学学生助手</title>
  <style>
    :root { color-scheme: light; --bg:#f2f4f7; --panel:#fff; --text:#172033; --muted:#667085; --line:#d9e0ea; --brand:#0f6f64; --brand-dark:#09544b; --soft:#ecfdf3; --danger:#b42318; }
    * { box-sizing:border-box; }
    html, body { max-width:100%; overflow-x:hidden; }
    body { margin:0; min-height:100vh; font-family:"Microsoft YaHei","Segoe UI",Arial,sans-serif; background:var(--bg); color:var(--text); }
    header { position:sticky; top:0; z-index:10; border-bottom:1px solid var(--line); background:#fff; }
    .topbar { max-width:1120px; min-height:68px; margin:auto; padding:12px 24px; display:flex; align-items:center; justify-content:space-between; gap:16px; }
    .brand { display:flex; align-items:center; gap:12px; }
    .mark { width:40px; height:40px; display:grid; place-items:center; border-radius:8px; background:var(--brand); color:#fff; font-weight:800; }
    h1 { margin:0; font-size:20px; }
    .brand small { display:block; margin-top:2px; color:var(--muted); font-size:12px; }
    nav { display:inline-flex; gap:4px; padding:3px; border:1px solid var(--line); border-radius:7px; background:#f8fafc; }
    nav a { min-height:34px; display:flex; align-items:center; padding:0 11px; border-radius:5px; color:#475467; font-size:13px; font-weight:700; text-decoration:none; }
    nav a.active { color:#fff; background:var(--brand); }
    main { max-width:1120px; margin:auto; padding:32px 24px 56px; display:grid; grid-template-columns:minmax(0,1fr) 320px; gap:16px; }
    section, aside { background:var(--panel); border:1px solid var(--line); border-radius:8px; }
    section { padding:28px; }
    aside { padding:22px; align-self:start; }
    h2 { margin:0 0 6px; font-size:20px; }
    h3 { margin:26px 0 12px; padding-top:22px; border-top:1px solid var(--line); font-size:16px; }
    p { color:var(--muted); line-height:1.65; }
    .grid { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
    .field { display:grid; gap:7px; }
    .field.full { grid-column:1/-1; }
    label { color:#344054; font-size:13px; font-weight:700; }
    input, select { width:100%; min-height:44px; border:1px solid #b8c2d0; border-radius:6px; padding:0 12px; background:#fff; color:var(--text); font:inherit; }
    input:focus, select:focus { border-color:var(--brand); outline:0; box-shadow:0 0 0 3px rgba(15,111,100,.14); }
    .actions { display:flex; flex-wrap:wrap; gap:10px; margin-top:16px; }
    button { min-height:42px; border:0; border-radius:6px; padding:0 16px; background:var(--brand); color:#fff; font:inherit; font-weight:700; cursor:pointer; }
    button.secondary { border:1px solid var(--line); background:#fff; color:var(--brand-dark); }
    button:disabled { opacity:.55; cursor:wait; }
    .remember { display:flex; align-items:center; gap:8px; color:var(--muted); font-size:13px; }
    .remember input { width:16px; min-height:16px; }
    .status { margin-top:14px; min-height:44px; padding:11px 12px; border:1px solid var(--line); border-radius:6px; color:var(--muted); font-size:13px; line-height:1.55; }
    .status.ok { border-color:#abefc6; background:var(--soft); color:#067647; }
    .status.error { border-color:#fecdca; background:#fef3f2; color:var(--danger); }
    .upload { border:1px dashed #98a2b3; border-radius:6px; padding:18px; background:#f9fafb; }
    .upload input { min-height:auto; border:0; padding:0; background:transparent; }
    .documents { margin-top:14px; display:grid; gap:8px; }
    .document { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:12px; padding:10px 12px; border:1px solid var(--line); border-radius:6px; font-size:13px; }
    .document span:first-child { overflow-wrap:anywhere; }
    .document span:last-child { color:var(--muted); white-space:nowrap; }
    .steps { margin:0; padding-left:20px; color:#475467; font-size:14px; line-height:1.75; }
    .privacy { padding:12px; border-left:3px solid var(--brand); background:#f4fbf9; color:#475467; font-size:13px; line-height:1.6; }
    code { font-family:Consolas,monospace; font-size:12px; }
    @media (max-width:760px) { .topbar { width:100%; min-width:0; align-items:flex-start; flex-direction:column; padding:12px; } main { width:100%; min-width:0; grid-template-columns:minmax(0,1fr); padding:16px 12px 32px; } section, aside { width:100%; min-width:0; padding:20px 16px; } .grid { grid-template-columns:minmax(0,1fr); } .field, .field.full { min-width:0; grid-column:auto; } input, select { max-width:100%; } nav { width:100%; min-width:0; overflow:hidden; } nav a { min-width:0; flex:1; justify-content:center; padding:0 5px; font-size:12px; white-space:nowrap; } }
  </style>
</head>
<body>
<header><div class="topbar">
  <div class="brand"><div class="mark">暨</div><div><h1>暨南大学学生助手</h1><small>团队连接与知识库导入</small></div></div>
  <nav aria-label="主导航"><a href="/">学生助手</a><a href="/pipeline">数据看板</a><a class="active" href="/settings">连接与导入</a></nav>
</div></header>
<main>
  <section>
    <h2>连接你的 RAGFlow</h2>
    <p>每位组员可以使用自己的连接。站点只在当前请求中转发 API Key，不会把它写入服务器文件或 GitHub。</p>
    <div class="grid">
      <div class="field full"><label for="baseUrl">RAGFlow 地址</label><input id="baseUrl" type="url" placeholder="https://ragflow.example.com" autocomplete="url" /></div>
      <div class="field full"><label for="apiKey">API Key</label><input id="apiKey" type="password" placeholder="输入 RAGFlow API Key" autocomplete="off" /></div>
      <div class="field"><label for="dataset">问答知识库</label><select id="dataset"><option value="">连接后选择</option></select></div>
      <div class="field"><label for="noticeDataset">通知补充知识库（可选）</label><select id="noticeDataset"><option value="">不使用</option></select></div>
    </div>
    <div class="actions"><button id="connect">验证并读取知识库</button><button class="secondary" id="forget">清除配置</button></div>
    <label class="remember"><input id="remember" type="checkbox" /> 在这台浏览器记住 API Key（共用电脑不要勾选）</label>
    <div id="connectionStatus" class="status">尚未验证连接。</div>

    <h3>导入项目知识库</h3>
    <p>把 GitHub 版本中已经清洗并归档的数据批量导入到上面所选的 RAGFlow 知识库。已有同名文件会自动跳过。</p>
    <div class="field"><label for="snapshot">项目数据快照</label><select id="snapshot"><option value="">正在读取...</option></select></div>
    <div class="actions"><button id="importSnapshot">开始后台导入</button></div>
    <div id="importStatus" class="status">请选择数据快照；建议先导入“核心服务卡片”。</div>

    <h3>上传并解析文件</h3>
    <div class="upload"><input id="files" type="file" multiple accept=".pdf,.docx,.xlsx,.pptx,.md,.txt,.html,.csv,.json,.png,.jpg,.jpeg,.webp" /></div>
    <div class="actions"><button id="upload">上传到所选知识库</button><button class="secondary" id="refresh">刷新文档状态</button></div>
    <div id="uploadStatus" class="status">支持常用文档、图片和表格；每次最多 10 个文件。</div>
    <div id="documents" class="documents"></div>
  </section>
  <aside>
    <h2>使用条件</h2>
    <ol class="steps"><li>RAGFlow 必须能被本 Web 服务访问。</li><li>远程地址必须启用 HTTPS。</li><li>在 RAGFlow 中先配置 LLM 与 Embedding 模型。</li><li>上传后等待解析完成，再回到助手提问。</li></ol>
    <h3>部署建议</h3>
    <p>团队共用一套云端 RAGFlow 最省事；需要隔离实验时，再让组员连接各自的实例。</p>
    <div class="privacy">API Key 会通过当前站点的 HTTPS 后端转发。请勿在公共电脑勾选“记住”，也不要把 Key 发到群聊或提交到 GitHub。</div>
  </aside>
</main>
<script>
  const $ = id => document.getElementById(id);
  const storageKey = "jnu-ragflow-connection";
  const keyStorage = "jnu-ragflow-api-key";
  function storedConfig() { try { return JSON.parse(localStorage.getItem(storageKey) || "{}"); } catch { return {}; } }
  function connection() { return { base_url: $("baseUrl").value.trim(), api_key: $("apiKey").value.trim(), dataset_id: $("dataset").value, notice_dataset_id: $("noticeDataset").value }; }
  function save() {
    const value = connection();
    localStorage.setItem(storageKey, JSON.stringify({ base_url:value.base_url, dataset_id:value.dataset_id, notice_dataset_id:value.notice_dataset_id }));
    sessionStorage.setItem(keyStorage, value.api_key);
    if ($("remember").checked) localStorage.setItem(keyStorage, value.api_key); else localStorage.removeItem(keyStorage);
  }
  function status(id, text, kind="") { const node=$(id); node.textContent=text; node.className=`status ${kind}`; }
  function options(items, selected, emptyLabel) { return `<option value="">${emptyLabel}</option>` + items.map(item => `<option value="${escapeHtml(item.id)}" ${item.id===selected?"selected":""}>${escapeHtml(item.name)} · ${Number(item.document_count||0)} 份</option>`).join(""); }
  function escapeHtml(value) { const div=document.createElement("div"); div.textContent=String(value||""); return div.innerHTML; }
  async function post(path, body) {
    const response=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    const data=await response.json();
    if(!response.ok || data.ok===false) throw new Error(data.message||data.answer||"请求失败");
    return data;
  }
  async function connect() {
    save(); $("connect").disabled=true; status("connectionStatus","正在连接 RAGFlow...");
    try {
      const current=connection(); const data=await post("/api/ragflow/connect",{connection:current});
      $("dataset").innerHTML=options(data.datasets,current.dataset_id,"请选择问答知识库");
      $("noticeDataset").innerHTML=options(data.datasets,current.notice_dataset_id,"不使用通知补充库");
      save(); status("connectionStatus",`连接成功，共读取到 ${data.datasets.length} 个知识库。`,"ok");
      if($("dataset").value) await refreshDocuments();
    } catch(error) { status("connectionStatus",error.message,"error"); } finally { $("connect").disabled=false; }
  }
  async function filePayload(file) { return new Promise((resolve,reject)=>{ const reader=new FileReader(); reader.onload=()=>resolve({name:file.name,base64:String(reader.result).split(",",2)[1]||""}); reader.onerror=reject; reader.readAsDataURL(file); }); }
  async function upload() {
    const files=[...$("files").files]; if(!files.length) return status("uploadStatus","请先选择文件。","error");
    save(); $("upload").disabled=true; status("uploadStatus",`正在上传 ${files.length} 个文件并启动解析...`);
    try { const encoded=await Promise.all(files.map(filePayload)); const data=await post("/api/ragflow/upload",{connection:connection(),files:encoded}); status("uploadStatus",`已上传 ${data.uploaded.length} 个文件，RAGFlow 已开始解析。`,"ok"); $("files").value=""; await refreshDocuments(); }
    catch(error) { status("uploadStatus",error.message,"error"); } finally { $("upload").disabled=false; }
  }
  async function loadSnapshots() {
    try { const response=await fetch("/api/ragflow/snapshots"); const data=await response.json(); $("snapshot").innerHTML=(data.snapshots||[]).map((item,index)=>`<option value="${escapeHtml(item.id)}" ${item.name.includes("核心服务卡片")?"selected":""}>${escapeHtml(item.name)} · ${Number(item.documents||0)} 份</option>`).join(""); }
    catch { $("snapshot").innerHTML=`<option value="">快照不可用</option>`; }
  }
  async function importSnapshot() {
    save(); if(!$("dataset").value) return status("importStatus","请先连接并选择导入目标知识库。","error");
    if(!$("snapshot").value) return status("importStatus","请选择项目数据快照。","error");
    $("importSnapshot").disabled=true; status("importStatus","正在创建后台导入任务...");
    try { const data=await post("/api/ragflow/import-snapshot",{connection:connection(),snapshot_dataset_id:$("snapshot").value}); await pollImport(data.job_id); }
    catch(error) { status("importStatus",error.message,"error"); $("importSnapshot").disabled=false; }
  }
  async function pollImport(jobId) {
    try { const data=await post("/api/ragflow/import-status",{job_id:jobId}); const job=data.job||{}; if(job.status==="failed") throw new Error(job.message||"导入失败"); if(job.status==="complete") { status("importStatus",`导入完成：新增 ${job.uploaded} 份，跳过同名 ${job.skipped} 份。RAGFlow 正在解析新文件。`,"ok"); $("importSnapshot").disabled=false; await refreshDocuments(); return; } status("importStatus",`后台导入中：已新增 ${job.uploaded||0} / ${job.total||0}，已跳过 ${job.skipped||0}。`); setTimeout(()=>pollImport(jobId),1500); }
    catch(error) { status("importStatus",error.message,"error"); $("importSnapshot").disabled=false; }
  }
  async function refreshDocuments() {
    save(); if(!$("dataset").value) return status("uploadStatus","请先选择问答知识库。","error");
    try { const data=await post("/api/ragflow/documents",{connection:connection()}); const docs=data.documents||[]; $("documents").innerHTML=docs.slice(0,30).map(item=>`<div class="document"><span>${escapeHtml(item.name)}</span><span>${item.run==="DONE"||item.run===3?"解析完成":escapeHtml(item.run||item.status||"等待处理")}</span></div>`).join("") || `<div class="status">该知识库暂无文件。</div>`; status("uploadStatus",`已读取 ${docs.length} 份文档，显示最近 30 份。`,"ok"); }
    catch(error) { status("uploadStatus",error.message,"error"); }
  }
  const initial=storedConfig(); $("baseUrl").value=initial.base_url||""; $("apiKey").value=sessionStorage.getItem(keyStorage)||localStorage.getItem(keyStorage)||""; $("remember").checked=Boolean(localStorage.getItem(keyStorage));
  loadSnapshots(); $("connect").onclick=connect; $("importSnapshot").onclick=importSnapshot; $("upload").onclick=upload; $("refresh").onclick=refreshDocuments;
  $("dataset").onchange=save; $("noticeDataset").onchange=save;
  $("forget").onclick=()=>{ localStorage.removeItem(storageKey); localStorage.removeItem(keyStorage); sessionStorage.removeItem(keyStorage); location.reload(); };
</script>
</body></html>"""
